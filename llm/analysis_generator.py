from langchain_core.prompts import ChatPromptTemplate
from output_types import QuestionAnalysis
from game_knowledge import GAME_KNOWLEDGE
from utils.chat_utils import format_history

class AnalysisGenerator:
    def __init__(self, llm):
        self.llm = llm

    def analyze(self, question: str, history: list[dict] | None = None, candidates: list[str] | None = None, embedding_context: str = "", excluded_nickname_terms: list[str] | None = None) -> QuestionAnalysis:

        prompt = ChatPromptTemplate.from_template("""
        너는 로스트아크 질문 분석기야.

        [CATEGORY_TYPE]
        카테고리 힌트의 타입 + 닉네임 유무로 결정:
        - 닉네임 있음 → SKILL / ENGRAVING / ARK_PASSIVE / ARK_GRID / COLLECTIBLE / PROFILE / AVATAR
        - 닉네임 없음 → GLOBAL_SKILL / GLOBAL_ENGRAVING / GLOBAL_ARK_PASSIVE / GLOBAL_ARK_GRID / GLOBAL_PROFILE
        ⚠️ candidates가 비어있지 않으면 embedding_context 결과와 무관하게 반드시 GLOBAL_이 아닌 카테고리를 사용해야 함.

        힌트 없는 특수 케이스:
        - TOTAL_INFO: 닉네임만 있고 카테고리 힌트 없는 포괄적 요청
        - EXPEDITION: 원정대 전체 정보
        - MARKET_ITEMS: 거래소 시세
        - AUCTION_ITEMS: 경매장 시세
        - GENERAL: 인사·일반 대화, 게임 시스템 개념 설명 (DB 조회 불필요). 특정 데이터 조회가 필요하면 GLOBAL_*로 분류.

        [닉네임 추출]
        ⚠️ 아래 단어들은 클래스·직업명이므로 절대 닉네임이 아님. candidates에 있더라도 제외:
        {excluded_nickname_terms}

        ⚠️ 닉네임 판별 전 반드시 먼저 확인:
        - [카테고리 힌트]에 등장하는 모든 약어·정식 명칭은 게임 용어이며 닉네임이 아님. candidates 여부와 무관하게 즉시 제외.
        - 클래스·직업명(워로드, 버서커, 소서리스 등) 및 아크패시브 클래스 유형(고독한 기사, 전투 태세 등)과 그 약어는 닉네임이 아님.

        - DB에서 찾은 후보 닉네임: {candidates}
        - 후보가 있으면 후보 중에서만 선택. 질문 맥락상 실제 닉네임이 아닌 것(지시어, 우연히 일치한 단어)은 제외.
        - 후보가 없으면(candidates=[]) 질문의 단어는 게임 용어일 가능성이 높음. nicknames=[]. 이전 대화에서도 닉네임을 찾을 것.
        - 현재 질문에 닉네임이 없으면 반드시 이전 대화를 확인해서 가장 최근에 언급된 닉네임 하나만 가져와. 후속 질문("작열은?", "그럼 스킬은?", "다른 건?")은 항상 이전 대화의 닉네임을 이어받아야 해. 그래도 없으면 []
        - 히스토리에 닉네임이 여러 개 있어도, 현재 질문에 닉네임이 명시되지 않았다면 반드시 가장 마지막에 언급된 닉네임 하나만 반환해. 절대 히스토리의 여러 닉네임을 모두 담지 마.
        - nicknames가 비어있지 않으면 category는 반드시 GLOBAL_이 아닌 쪽으로 분류. GLOBAL_*와 닉네임은 절대 함께 올 수 없음.
        - nicknames=[]이면 category는 GLOBAL_*로 분류.

        [카테고리 힌트 - embedding 검색 결과]
        {embedding_context}

        [게임 지식]
        {game_knowledge}

        [response_format]
        - DISPLAY 판단 방법: 질문에서 닉네임과 단순 요청 표현(보여줘, 알려줘, 뭐야, 뭐가 있어, 뭐있어, 어때, 보여, 줘, 있어, 목록 등)을 제거했을 때 트리거 단어 하나만 남으면 DISPLAY.
          그 외 단어가 하나라도 남으면 DISPLAY가 아님.
          예) "펜토르 스킬 보여줘" → 제거 후 "스킬" → DISPLAY
              "펜토르 카운터 스킬 뭐야" → 제거 후 "카운터 스킬" → DISPLAY 아님
              "펜토르 차징 스킬은?" → 제거 후 "차징 스킬" → DISPLAY 아님
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
            "embedding_context": embedding_context or "없음",
            "excluded_nickname_terms": ", ".join(excluded_nickname_terms) if excluded_nickname_terms else "없음",
            })
        
        if result is None:
            raise ValueError("질문 분석 결과가 없습니다.")
        return result