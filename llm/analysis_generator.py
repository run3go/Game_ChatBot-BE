import time
from langchain_core.prompts import ChatPromptTemplate
from output_types import QuestionAnalysis
from game_knowledge import GAME_KNOWLEDGE
from utils.chat_utils import format_history
from constants import DISPLAY_TRIGGERS
from llm.llm_monitor import log_llm_call, TokenCountCallback


def _format_display_triggers() -> str:
    lines = []
    for category, words in DISPLAY_TRIGGERS.items():
        lines.append(f"            - {category}: {', '.join(sorted(words))}")
    return "\n".join(lines)

class AnalysisGenerator:
    def __init__(self, llm):
        self.llm = llm
        self.model_name = getattr(llm, "model_name", getattr(llm, "model", "unknown"))

    def analyze(self, question: str, history: list[dict] | None = None, candidates: list[str] | None = None, embedding_context: str = "") -> QuestionAnalysis:

        prompt = ChatPromptTemplate.from_template("""
        너는 로스트아크 질문 분석기야.

        [CATEGORY_TYPE]
        카테고리 힌트의 타입 + 닉네임 유무로 결정:
        - 닉네임 있음 → SKILL / ENGRAVING / ARK_PASSIVE / ARK_GRID / COLLECTIBLE / PROFILE / AVATAR
        - 닉네임 없음 → GLOBAL_SKILL / GLOBAL_ENGRAVING / GLOBAL_ARK_PASSIVE / GLOBAL_ARK_GRID / GLOBAL_PROFILE
        ⚠️ candidates가 비어있지 않으면 embedding_context 결과와 무관하게 반드시 GLOBAL_이 아닌 카테고리를 사용해야 함.
          예) candidates=["첫번째도구"], nicknames=["첫번째도구"] → category=SKILL (GLOBAL_SKILL ❌)
              "닉네임을 언급하며 스킬을 물어봤으므로 GLOBAL_SKILL" 같은 추론은 완전히 잘못된 것. 닉네임이 있으면 GLOBAL_ 절대 불가.
        ⚠️ 치명타 비율·신속 비율·스탯 분포("치신 비율", "치명 얼마나", "신속 비율") 질문은 아크패시브 관련 질문처럼 보여도 반드시 GLOBAL_PROFILE로 분류. stat_crit·stat_swift 같은 스탯 수치는 armory_profile_tb에 있으므로 GLOBAL_ARK_PASSIVE로 분류하면 잘못된 테이블을 조회하게 됨.
        ⚠️ 질문에 "보석"이 포함되고 가격·시세 키워드가 없으면 → 반드시 SKILL. "장착한 보석", "끼고 있는 보석", "다른 보석", "보석 개수" 등 어떤 수식이 붙어도 SKILL. PROFILE로 분류 금지.
          예) "황로드유가 장착한 다른 보석 개수" → SKILL, "끼고 있는 보석이 뭐야" → SKILL

        힌트 없는 특수 케이스:
        - TOTAL_INFO: 닉네임만 있고 카테고리 힌트 없는 포괄적 요청
        - EXPEDITION: 원정대 전체 정보

        ※ 가격·시세 관련 질문은 아래 순서로 판별:
          1단계) 장신구(목걸이·귀걸이·반지·팔찌) 또는 레벨형 보석이 언급되면 → 무조건 AUCTION. MARKET 검토 불필요.
          2단계) 1단계 해당 없으면 → MARKET 여부 검토.

        - MARKET: 거래소 아이템 시세 조회. 트리거: {{시세, 가격, 최저가, 전일가, 어제가, 실거래가, 최근가, 가성비, 비싼, 저렴한, 올랐어, 내렸어, 거래소}} 중 하나 + 아이템명(강화 재료·각인서·아바타·소모품·혼돈의 젬 등 레벨 없는 재료형 아이템). 닉네임 유무 무관.
          예) "운명의 파괴석 시세", "유물 각인서 가격", "황로드유 각인 올리는 데 비용 얼마야", "혼돈의 젬 종류별 최저가" → MARKET
          ⚠️ 아바타 관련 가격 질문은 반드시 MARKET으로 분류. 아바타를 AUCTION으로 분류하지 마.
        - AUCTION: 경매장 장신구(목걸이·귀걸이·반지·팔찌) 또는 레벨형 보석(겁화·작열·멸화·홍염·분노·절멸 등 "N레벨 보석명" 형태) 매물 조회. 트리거: {{입찰가, 즉구가, 즉시구매가, 매물, 경매장}} 또는 장신구·레벨형 보석 + {{시세, 가격, 최저가, 싸, 싼, 비싼, 저렴, 합성}} 중 하나. 닉네임 유무 무관.
          예) "치명 반지 최저가", "상하 목걸이 시세", "고대 귀걸이 입찰가", "팔찌 시세", "신속 팔찌 가격", "9레벨 겁화 시세", "8레벨 작열 가격", "황로드유 보석 총 가격", "8레벨 겁화 3개 합성 vs 9레벨 겁화 1개 뭐가 싸?" → AUCTION
        ⚠️ 장신구(목걸이·귀걸이·반지·팔찌) + 가격 관련 키워드(시세, 가격, 최저가, 싸, 싼, 비싼, 저렴) → embedding_context 힌트와 무관하게 항상 AUCTION. PROFILE이나 MARKET으로 분류 절대 금지.
          예) "첫번째도구가 장착한 귀걸이의 시세" → embedding_context에 "귀걸이 → PROFILE"이 있어도 AUCTION.
        ⚠️ 역할 표현(딜러·서폿·서포터) + 옵션등급 표현(상중·중중·상단일·중단일 등) + 장신구 종류 조합 → 항상 AUCTION. 아이템 이름으로 오인하거나 MARKET으로 분류 절대 금지.
          예) "딜러 상단일 고대 귀걸이", "서폿 중중 목걸이 시세", "딜러 상중 반지 최저가" → AUCTION
        ⚠️ 레벨형 보석(N레벨 겁화·작열·멸화·홍염·분노·절멸 등) + 가격·비용 관련 키워드(가격, 시세, 싸, 싼, 비싼, 저렴, 합성) → 항상 AUCTION. embedding_context에 해당 보석명이 SKILL로 표시되어 있어도 무관. MARKET·SKILL로 분류 금지.
        ⚠️ 캐릭터 장착 보석의 가격·비용을 묻는 질문(예: "황로드유 보석 총 가격", "끼고 있는 보석을 N레벨로 바꾸려면") → AUCTION. 단, 질문에 "보석"이 명시되지 않고 "각인" 또는 "각인서"가 포함되어 있으면 이 규칙 적용 금지.
        ⚠️ "각인 레벨 올리기" / "각인 레벨을 올리는 데 비용" / "캐릭터 장착 각인 레벨업 비용" → 각인서(각인 책) 가격 조회이므로 반드시 MARKET. "보석"이 명시되지 않으면 AUCTION 분류 금지.
          예) "황로드유가 장착한 유물 각인 중 남은 레벨을 올리는 데 비용이 가장 적게 드는 게 뭐야?" → MARKET (각인서 가격 조회, 보석 무관)
        ⚠️ 가격, 시세같은 키워드가 포함된 질문은 닉네임이 있어도 MARKET 또는 AUCTION으로 분류. PROFILE·SKILL 등으로 분류 금지.
        - GENERAL: 인사·일반 대화, 게임 시스템 개념 설명 (DB 조회 불필요). 특정 데이터 조회가 필요하면 GLOBAL_*로 분류.
          ⚠️ 직업명·아크패시브 클래스 등 구체적인 집계 기준 없이 막연하게 "어떤 스킬이 있어?", "스킬 목록 보여줘" 같은 질문은 GLOBAL_*가 아니라 GENERAL로 분류. 특정 집계 기준(직업, 아크패시브 클래스, 각인 조합 등)이 명시돼야 GLOBAL_*가 될 수 있음.

        [닉네임 추출]
        ⚠️ 닉네임 판별 전 반드시 먼저 확인:
        - [카테고리 힌트]에 등장하는 모든 단어(- 앞의 단어, 약어 포함)는 게임 용어이며 닉네임이 절대 아님. candidates에 있든 없든, 문장에서 소유격("의") 앞에 오든 무관하게 즉시 제외.
          예) embedding_context에 "이보크 → SKILL"이 있으면 "이보크의 트라이포드"에서 이보크는 스킬명이지 닉네임이 아님.
        - 클래스·직업명(워로드, 버서커, 소서리스 등) 및 아크패시브 클래스 유형(고독한 기사, 전투 태세 등)과 그 약어는 닉네임이 아님.
        - 역할 표현(딜러, 딜, 서폿, 서포터, 서포트)은 닉네임이 아님. 장신구 검색 질문(예: "딜러 상중 귀걸이", "서폿 목걸이 시세")에서 절대 닉네임으로 추출 금지.

        - DB에서 찾은 후보 닉네임: {candidates}
        - 후보가 있으면 후보 중에서만 선택. 질문 맥락상 실제 닉네임이 아닌 것(지시어, 우연히 일치한 단어)은 제외.
        - 후보가 없으면(candidates=[]) 질문의 단어는 게임 용어일 가능성이 높음. nicknames=[].
        - 현재 질문에 닉네임이 없을 때: 먼저 닉네임 없이 질문을 처리할 수 있는지 판단.
          닉네임 없이 처리 가능하면(예: 독립적인 시세·가격·합성 비교 등) nicknames=[] 그대로.
          닉네임 없이는 의도를 파악하기 어려운 경우(주어가 불명확한 후속 질문: "작열은?", "그럼 스킬은?", "다른 건?")에만 이전 대화에서 가장 최근에 언급된 닉네임 하나를 가져와. 그래도 없으면 []
        - 히스토리에 닉네임이 여러 개 있어도, 현재 질문에 닉네임이 명시되지 않았다면 반드시 가장 마지막에 언급된 닉네임 하나만 반환해. 절대 히스토리의 여러 닉네임을 모두 담지 마.
        - ⚠️ 단, 현재 질문에서 두 캐릭터를 명시적으로 비교("A와 B 비교", "A랑 B 차이")하는 경우 두 닉네임을 모두 반환해. candidates에 두 닉네임이 모두 있으면 둘 다 선택해야 함.
        - nicknames가 비어있지 않으면 category는 반드시 GLOBAL_이 아닌 쪽으로 분류. GLOBAL_*와 닉네임은 절대 함께 올 수 없음.
        - nicknames=[]이면 category는 GLOBAL_*로 분류.

        [카테고리 힌트 - embedding 검색 결과]
        {embedding_context}

        [게임 지식]
        {game_knowledge}

        [response_format]
        - DISPLAY 판단 방법: 질문에서 닉네임, 단순 요청 표현(보여줘, 알려줘, 알려줘라, 알려주세요, 뭐야, 뭐가 있어, 뭐있어, 어때, 보여, 줘, 있어, 목록 등), 그리고 한국어 조사(의, 을, 를, 이, 가, 은, 는, 에, 에서, 이랑, 랑 등) 및 어미(라, 요, 야 등)를 모두 제거했을 때 아래 트리거 단어 목록 중 하나만 남으면 DISPLAY.
          그 외 단어가 하나라도 남으면 DISPLAY가 아님.
          ⚠️ 트리거 단어는 아래 목록에 있는 단어 그 자체여야 함. 스킬명·각인명·아이템명 등 구체적인 게임 콘텐츠 이름은 트리거 단어가 아님.
          ⚠️ "보여줘" 같은 요청 표현이 없어도, 닉네임·조사·어미 제거 후 트리거 단어 하나만 남으면 DISPLAY.
          ⚠️ embedding_context에 구체적인 스킬명·각인명이 보이더라도, 질문 자체가 "닉네임 + 트리거 단어"만으로 이루어져 있으면 DISPLAY. LIST로 분류하지 말 것.
          예) "펜토르 스킬 보여줘" → 제거 후 "스킬" → DISPLAY  ← "스킬"이 트리거 목록에 있음
              "황로드유 스킬" → 제거 후 "스킬" → DISPLAY  ← 요청 표현 없어도 트리거 단어만 남으면 DISPLAY
              "첫번째도구 스킬" → 제거 후 "스킬" → DISPLAY  ← embedding_context에 극멸권·별 같은 스킬명이 있어도 무관
              "첫번째도구의 스킬을 알려줘" → 닉네임·조사(의, 을)·요청표현(알려줘)·어미(라) 제거 후 "스킬" → DISPLAY
              "황로드유 정보" → 제거 후 "정보" → TOTAL_INFO + DISPLAY  ← "정보"가 TOTAL_INFO 트리거
              "펜토르 집중 보여줘" → 제거 후 "집중" → DISPLAY 아님  ← "집중"은 스킬 관련 단어이지 트리거 단어가 아님
              "버프받아가 전설 집중 꼈나?" → 제거 후 "전설 집중" → DISPLAY 아님 → TEXT
              "펜토르 카운터 스킬 뭐야" → 제거 후 "카운터 스킬" → DISPLAY 아님
          DISPLAY 트리거 단어 전체 목록:
          {display_triggers}
          ※ 반지·귀걸이·목걸이·장신구는 PROFILE 트리거 단어가 아님. "황로드유 반지가 뭐야?" 같은 질문은 LIST 또는 TEXT로 처리.
        - LIST: 결과가 여러 행(항목)으로 나열되는 상세 조회. 트라이포드·보석 목록처럼 한 스킬/아이템에 딸린 하위 항목이 여럿인 경우.
          예) "다크 리저렉션 트포 알려줘", "배쉬 트라이포드 뭐야?", "리턴 스킬 보석 알려줘"
          ※ DISPLAY는 카테고리 전체 목록, LIST는 특정 항목의 하위 항목 목록.
          ※ 결과가 텍스트 한 줄(효과 설명, 단일 수치 등)이면 LIST가 아니라 TEXT.
          ※ MARKET·AUCTION 카테고리에서 아이템 목록 나열 요청(최저가 찾아줘, 매물 보여줘, 시세 어때, 입찰가 순으로 보여줘 등) → LIST. 계산·비교·분석이 필요한 경우(합성 비용 비교, 효율 계산, 가격 차이 추론 등)만 TEXT.
        - COMPARE: 두 명 이상 비교 ("A랑 B 비교해줘"), 또는 동일 캐릭터의 시점 간 변화 비교 ("최근에 바뀐 거 있어?", "트포 바뀐 거 있어?", "이전이랑 달라진 게 있어?", "각인 바꾼 적 있어?", "각인 바뀐 거 있어?", "보석 바뀐 거 있어?", "장비 바뀐 게 있어?")
          ※ "[카테고리 주제] + 바꾼/바뀐/변경/달라진" 패턴은 항상 해당 카테고리 + COMPARE로 분류. PROFILE로 올리지 말 것.
        - COUNT: 단일 개수 ("몇 개야?") — 이전 대화가 COUNT였고 후속 질문이면 COUNT 유지
          ⚠️ "성장은 빠른 편인가?", "성장 속도가 어떻게 돼?", "성장 추이" 같은 질문은 COUNT가 아니라 TEXT. 데이터 포인트 개수가 아니라 시계열 변화를 보여줘야 함.
        - COUNT_LIST: 항목별 개수 목록 ("스킬별 보석 개수는?", "가장 많이 쓰는 ~가 뭐야?", "~별 통계")
        - VALUE: 단순 수치 하나를 묻는 질문. ("전투력이 얼마야?", "리턴 스킬 레벨이 몇이야?")
          "가장 높은/낮은 ~가 뭐야?", "어떤 ~?" 처럼 특정 대상(행/스킬/아이템)을 찾는 질문은 VALUE가 아니라 GLOBAL_*.

        [후속 질문 처리]
        - 현재 질문이 닉네임만 바뀐 후속 질문이면("황로드유는?", "황로드유는 몇 개야?") 이전 대화의 주제를 그대로 이어받아.
        - 예시: 이전 대화가 "작열 몇 개야?" → AI "3개야" 흐름이었다면, "황로드유는 몇 개야?"는 "황로드유의 작열 개수"로 해석해.
        - 질문을 해석할 때 이전 대화 맥락 전체를 참고해서 생략된 주제를 복원해.

        [이전 대화]
        {history}

        [사용자 질문]
        {question}

        """)

        structured_llm = self.llm.with_structured_output(QuestionAnalysis)
        chain = (prompt | structured_llm).with_retry(stop_after_attempt=2)

        history_text = format_history(history, max_ai_length=200) if history else ""

        inputs = {
            "question": question,
            "history": history_text or "없음",
            "candidates": candidates or [],
            "game_knowledge": GAME_KNOWLEDGE,
            "embedding_context": embedding_context or "없음",
            "display_triggers": _format_display_triggers(),
        }

        start_time = time.time()
        cb = TokenCountCallback()
        detail = {
            "input": {
                "embedding_context": embedding_context or "없음",
                "candidates": candidates or [],
            },
            "output": {},
        }

        try:
            result = chain.invoke(inputs, config={"callbacks": [cb]})

            if result is None:
                raise ValueError("질문 분석 결과가 없습니다.")

            detail["output"] = {
                "nicknames": result.nicknames,
                "response_format": result.response_format,
                "category": result.category,
                "reason": result.reason,
            }

            log_llm_call(
                generator_type="analysis",
                model_name=self.model_name,
                start_time=start_time,
                callback=cb,
                detail=detail,
            )
            return result

        except Exception as e:
            log_llm_call(
                generator_type="analysis",
                model_name=self.model_name,
                start_time=start_time,
                callback=cb,
                success=False,
                error_message=str(e),
                detail=detail,
            )
            raise
