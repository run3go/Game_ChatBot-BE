from langchain_core.prompts import ChatPromptTemplate
from langchain_core.exceptions import OutputParserException
from output_types import QuestionAnalysis
from sql.game_knowledge import SLANG_RULES
from utils.chat_utils import format_history

class AnalysisGenerator:
    def __init__(self, llm):
        self.llm = llm

    def analyze(self, question: str, history: list[dict] | None = None, candidates: list[str] | None = None) -> QuestionAnalysis:

        prompt = ChatPromptTemplate.from_template("""
        너는 로스트아크 질문 분석기야.

        [QUERY_TYPE]
        캐릭터 카테고리 조회 (닉네임 필요):
        - SKILL: 스킬, 보석
        - ENGRAVING: 각인
        - AVATAR: 아바타
        - ARK_GRID: 아크그리드
        - ARK_PASSIVE: 아크패시브
        - COLLECTIBLE: 수집품, 내실
        - PROFILE: 프로필, 레벨, 능력치, 장비
        - TOTAL_INFO: 특정 카테고리 없이 닉네임만 있거나 포괄적 정보 요청
        - EXPEDITION: 원정대 전체 정보

        거래/시세:
        - MARKET_ITEMS: 거래소 시세
        - AUCTION_ITEMS: 경매장 시세

        분석/계산:
        - COMPLEX: 개수, 비교, 필터링, 집계 등 추가 처리가 필요한 질문. 아래 중 하나라도 해당하면 COMPLEX.
            - 개수/수량 ("몇", "개수", "갯수", "총 몇" 등)
            - 두 캐릭터 이상 비교
            - 조건 필터링 ("~인 것만", "~보다 높은", "어느/어떤 ~에" 등)
            - 특정 조건의 항목 탐색 ("9겁이 어느 스킬에", "9겁이 장착된 스킬" 등 두 카테고리를 조건부로 연결하는 탐색)
            - 집계, 합산, 평균

        기타:
        - GENERAL: DB 조회 없이 게임 지식으로 답 가능하거나 일반 대화. 애매하면 COMPLEX.

        [닉네임 추출]
        - DB에서 찾은 후보 닉네임: {candidates}
        - 후보가 있으면 후보 중에서만 선택. 질문 맥락상 실제 닉네임이 아닌 것(지시어, 우연히 일치한 단어)은 제외.
        - 후보가 없으면 조사 제거(은,는,이,가,을,를,의 등) 후 직접 추출. 여러 명 가능.
        - 현재 질문에 닉네임이 없으면 반드시 이전 대화를 확인해서 가장 최근에 언급된 닉네임 하나만 가져와. 후속 질문("작열은?", "그럼 스킬은?", "다른 건?")은 항상 이전 대화의 닉네임을 이어받아야 해. 그래도 없으면 []
        - 히스토리에 닉네임이 여러 개 있어도, 현재 질문에 닉네임이 명시되지 않았다면 반드시 가장 마지막에 언급된 닉네임 하나만 반환해. 절대 히스토리의 여러 닉네임을 모두 담지 마.

        [게임 은어 규칙]
        {slang_rules}
        - keywords: 닉네임을 제외한 질문의 핵심 개념들을 정식 명칭으로 분리해서 추출. 은어·약어가 있으면 위 규칙으로 확장. 질문에 없는 정보는 추가하지 말 것.
          각 개념은 SQL 조건 힌트가 될 수 있도록 구체적으로 작성.
          예) "9겁 개수" → ["9레벨 겁화의 보석", "보석 개수"]
          예) "9겁 달린 스킬" → ["9레벨 겁화의 보석", "보석이 적용된 스킬"]
          TRADING이면 keywords에 아이템 정식 명칭을 포함할 것.

        [response_format]
        - DISPLAY: 닉네임+카테고리 조합이거나 데이터를 화면에 보여주는 경우 기본값. ("황로드유 스킬", "첫번째도구 각인")
        - COMPARE: 두 명 이상 비교 ("A랑 B 비교해줘")
        - COUNT: 단일 개수 ("몇 개야?") — 이전 대화가 COUNT였고 후속 질문이면 COUNT 유지
        - COUNT_LIST: 항목별 개수 목록 ("스킬별 보석 개수는?")
        - VALUE: 특정 수치 하나 ("전투력이 얼마야?")

        [후속 질문 처리]
        - 현재 질문이 닉네임만 바뀐 후속 질문이면("황로드유는?", "황로드유는 몇 개야?") 이전 대화의 주제를 그대로 이어받아.D이 프롬프트
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
            "slang_rules": SLANG_RULES,
            })
        
        if result is None:
            raise ValueError("질문 분석 결과가 없습니다.")
        return result