from langchain_core.prompts import ChatPromptTemplate
from output_types import QuestionAnalysis
from game_knowledge import GAME_KNOWLEDGE
from utils.chat_utils import format_history

class AnalysisGenerator:
    def __init__(self, llm):
        self.llm = llm

    def analyze(self, question: str, history: list[dict] | None = None, candidates: list[str] | None = None) -> QuestionAnalysis:

        prompt = ChatPromptTemplate.from_template("""
        너는 로스트아크 질문 분석기야.

        [CATEGORY_TYPE]
        캐릭터 카테고리 조회 (닉네임 필요):
        - SKILL: 스킬, 보석
        - ENGRAVING: 각인
        - AVATAR: 아바타
        - ARK_GRID: 아크그리드 전체, 코어 중심 질문 ("아크그리드 보여줘", "고대 코어", "질서 코어")
        - ARK_PASSIVE: 아크패시브, 진화, 깨달음, 도약
        - COLLECTIBLE: 수집품, 내실
        - PROFILE: 프로필, 레벨, 능력치, 장비
        - TOTAL_INFO: 특정 카테고리 없이 닉네임만 있거나 포괄적 정보 요청
        - EXPEDITION: 원정대 전체 정보

        거래/시세:
        - MARKET_ITEMS: 거래소 시세
        - AUCTION_ITEMS: 경매장 시세

        기타 (닉네임 없이 DB 조회):
        - GLOBAL_SKILL: 닉네임 없이 게임 공통 스킬/트라이포드/룬 정보 조회.
          예) "배쉬 트라이포드 알려줘", "배쉬에 대부분 무슨 룬 넣어?", "리턴 스킬 레벨이 뭐야?"
        - GLOBAL_ARK_PASSIVE: 닉네임 없이 아크패시브 공통 효과/구성 조회.
          예) "달인 효과가 뭐야?", "진화 4티어 효과가 뭐야?", "깨달음 효과 목록이 뭐야?"
          ※ 아크패시브 효과명(달인, 고독한 기사, 결투사 등)은 캐릭터 닉네임이 아님.
        - GLOBAL_ARK_GRID: 닉네임 없이 아크그리드 공통 코어/효과 조회.
          예) "질서 코어 효과 알려줘", "혼돈 코어 구성이 어떻게 돼?", "고독한 기사 코어에 뭐가 있어?"
          ※ 코어 이름(질서 코어, 혼돈 코어 등)은 캐릭터 닉네임이 아님.
        - GLOBAL_ENGRAVING: 닉네임 없이 각인 공통 효과/레벨 정보 조회.
          예) "달인 각인 효과가 뭐야?", "바리케이드 각인 레벨별 효과 알려줘"
        - GLOBAL_PROFILE: 닉네임 없이 전체 유저 대상 집계/통계/프로필 조회.
          예) "평균 전투력이 얼마야?", "가장 많이 쓰는 각인이 뭐야?", "전투력 상위 유저 알려줘"
          ※ 질문에 캐릭터 닉네임이 포함되면 GLOBAL_* 대신 해당 캐릭터 카테고리로 분류.
        - GENERAL: DB 조회 없이 답 가능한 질문. 일반 대화/인사, 게임 시스템·기능 개념 설명 질문.
          예) "아크그리드가 뭐야?", "아크그리드 코어가 뭐야?", "트라이포드가 뭐야?", "아크패시브가 뭐야?" → 게임 시스템/기능 자체를 설명하는 질문
          예) "안녕", "고마워", "로스트아크가 뭐야?"
          ※ "~가 뭐야?" 형태라도 특정 아이템/스킬/효과의 DB 데이터를 조회해야 하면 GLOBAL_*. ("달인 효과가 뭐야?" → GLOBAL_ARK_PASSIVE, "아크패시브가 뭐야?" → GENERAL)
          ※ 애매하면 GLOBAL_PROFILE.

        [닉네임 추출]
        - DB에서 찾은 후보 닉네임: {candidates}
        - 후보가 있으면 후보 중에서만 선택. 질문 맥락상 실제 닉네임이 아닌 것(지시어, 우연히 일치한 단어)은 제외.
        - 후보가 없으면 조사 제거(은,는,이,가,을,를,의 등) 후 직접 추출. 여러 명 가능.
        - 현재 질문에 닉네임이 없으면 반드시 이전 대화를 확인해서 가장 최근에 언급된 닉네임 하나만 가져와. 후속 질문("작열은?", "그럼 스킬은?", "다른 건?")은 항상 이전 대화의 닉네임을 이어받아야 해. 그래도 없으면 []
        - 히스토리에 닉네임이 여러 개 있어도, 현재 질문에 닉네임이 명시되지 않았다면 반드시 가장 마지막에 언급된 닉네임 하나만 반환해. 절대 히스토리의 여러 닉네임을 모두 담지 마.
        - 클래스(워로드, 버서커, 소서리스 등 game_knowledge의 직업명, 아크 패시브 클래스)이 포함된 표현은 빌드 유형을 나타내며 닉네임이 아님. nicknames=[]로 처리.

        [게임 은어 규칙]
        {game_knowledge}
        - keywords: 닉네임을 제외한 질문의 핵심 개념들을 정식 명칭으로 분리해서 추출. 은어·약어가 있으면 위 규칙으로 확장. 질문에 없는 정보는 추가하지 말 것.
          각 개념은 SQL 조건 힌트가 될 수 있도록 구체적으로 작성.
          복합 개념은 반드시 개별 개념으로 쪼개서 나열할 것. 상위 개념(스킬, 보석, 각인 등)도 항상 별도로 포함해서 관련 테이블이 넓게 검색되도록 할 것.
          예) "9겁 개수" → ["보석", "9레벨 겁화의 보석", "보석 개수"]
          예) "9겁 달린 스킬" → ["스킬", "보석", "9레벨 겁화의 보석", "보석이 적용된 스킬"]
          예) "리턴 스킬 레벨" → ["스킬", "스킬 레벨", "리턴"]
          SKILL + COMPARE이면 keywords에 반드시 "보석"을 포함할 것.

        [response_format]
        - DISPLAY: 닉네임과 아래 트리거 단어 단 하나만으로 이루어진 질문일 때만 해당. 트리거 단어 외에 어떤 단어도 추가되면 절대 DISPLAY가 아님.
          DISPLAY 트리거 단어 전체 목록:
            - SKILL: 스킬, 보석
            - ENGRAVING: 각인
            - AVATAR: 아바타
            - ARK_GRID: 아크그리드, 코어
            - ARK_PASSIVE: 아크패시브, 진화, 깨달음, 도약
            - COLLECTIBLE: 내실, 수집품
            - PROFILE: 장비, 프로필, 레벨, 능력치
            - EXPEDITION: 원정대
          ※ 반지·귀걸이·목걸이·장신구는 PROFILE 트리거 단어가 아님. "황로드유 반지가 뭐야?" 같은 질문은 LIST 또는 TEXT로 처리.
        - LIST: 결과가 여러 행(항목)으로 나열되는 상세 조회. 트라이포드·보석 목록처럼 한 스킬/아이템에 딸린 하위 항목이 여럿인 경우.
          예) "다크 리저렉션 트포 알려줘", "배쉬 트라이포드 뭐야?", "리턴 스킬 보석 알려줘"
          ※ DISPLAY는 카테고리 전체 목록, LIST는 특정 항목의 하위 항목 목록.
          ※ 결과가 텍스트 한 줄(효과 설명, 단일 수치 등)이면 LIST가 아니라 TEXT.
        - COMPARE: 두 명 이상 비교 ("A랑 B 비교해줘"), 또는 동일 캐릭터의 시점 간 변화 비교 ("최근에 바뀐 거 있어?", "트포 바뀐 거 있어?", "이전이랑 달라진 게 있어?")
        - COUNT: 단일 개수 ("몇 개야?") — 이전 대화가 COUNT였고 후속 질문이면 COUNT 유지
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

        history_text = format_history(history) if history else ""

        result = chain.invoke({
            "question": question,
            "history": history_text or "없음",
            "candidates": candidates or [],
            "game_knowledge": GAME_KNOWLEDGE,
            })
        
        if result is None:
            raise ValueError("질문 분석 결과가 없습니다.")
        return result