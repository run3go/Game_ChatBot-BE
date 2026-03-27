from langchain_core.prompts import ChatPromptTemplate
from output_types import QuestionAnalysis

class AnalysisGenerator:
    def __init__(self, llm):
        self.llm = llm

    def analyze(self, question: str, history: list[dict] | None = None, candidates: list[str] | None = None) -> QuestionAnalysis:

        prompt = ChatPromptTemplate.from_template("""
        너는 로스트아크 질문 분석기야.

        [INTENT]
        - CHARACTER: 특정 캐릭터의 데이터 조회
        - COMPLEX: 계산, 비교, 필터링 등 추가 처리 필요
        - TRADING: 거래소 / 경매장 가격 관련
        - GENERAL: DB 조회 없이 게임 지식으로 답할 수 있는 질문, 또는 일반 대화

        [UI_TYPE]
        - EXPEDITION: 원정대
        - SKILL, ENGRAVING, AVATAR, ARK_GRID, ARK_PASSIVE, COLLECTIBLE
        - MARKET_ITEMS, AUCTION_ITEMS
        - PROFILE: 사용자가 명시적으로 "프로필", "레벨", "능력치" 등을 언급했을 때만 사용.
        - TOTAL_INFO: 특정 카테고리 언급 없이 닉네임만 있거나 포괄적인 정보를 요청할 때의 기본 UI 타입.
        - ETC: INTENT가 "COMPLEX"이면 UI_TYPE은 반드시 "ETC".

        [닉네임 추출]
        - DB에서 찾은 후보 닉네임: {candidates}
        - 후보가 있으면 후보 중에서만 선택. 질문 맥락상 실제 닉네임이 아닌 것(지시어, 우연히 일치한 단어)은 제외.
        - 후보가 없으면 조사 제거(은,는,이,가,을,를,의 등) 후 직접 추출. 여러 명 가능.
        - 현재 질문에 닉네임이 없으면 반드시 이전 대화를 확인해서 가장 최근에 언급된 닉네임 하나만 가져와. 후속 질문("작열은?", "그럼 스킬은?", "다른 건?")은 항상 이전 대화의 닉네임을 이어받아야 해. 그래도 없으면 []
        - 히스토리에 닉네임이 여러 개 있어도, 현재 질문에 닉네임이 명시되지 않았다면 반드시 가장 마지막에 언급된 닉네임 하나만 반환해. 절대 히스토리의 여러 닉네임을 모두 담지 마.

        [아이템명 추출]
        - TRADING 질문일 때만 추출, 가능한 경우 정식 명칭으로 변환

        [판단 규칙]
        1. 아래 중 하나라도 해당하면 → COMPLEX
           - 개수/수량을 묻는 질문 (표현 무관: "몇", "개수", "갯수", "몇 개", "얼마나 많", "총 몇" 등)
           - 두 캐릭터 이상을 비교하는 질문
           - 조건 필터링 후 결과가 필요한 질문 ("~인 것만", "~보다 높은", "~중에서" 등)
           - 집계, 합산, 평균 등 계산이 필요한 질문
        2. 가격/거래 관련 표현이 있으면 → TRADING ("가격", "시세", "거래소", "경매장", "얼마" 등)
        3. 특정 카테고리 언급 시 → CHARACTER ("스킬", "보석", "각인", "아바타", "장비", "아크그리드", "아크패시브", "능력치", "카드" 등)
        4. 닉네임만 있거나 포괄적인 정보 요청 → TOTAL_INFO (intent: CHARACTER)
        5. DB 없이 게임 지식으로 답 가능하거나 일반 대화 → GENERAL
        6. 애매하면 COMPLEX

        [aggregation_type]
        - DISPLAY: 닉네임+카테고리 조합이거나 데이터를 화면에 보여주는 경우 기본값. ("황로드유 스킬", "첫번째도구 각인", "각인 뭐 있어?")
        - COMPARE: 두 명 이상 비교 ("A랑 B 비교해줘")
        - COUNT: 단일 개수 ("몇 개야?") — 이전 대화가 COUNT였고 후속 질문이면 COUNT 유지
        - COUNT_LIST: 항목별 개수 목록 ("스킬별 보석 개수는?")
        - VALUE: 특정 수치 하나 ("전투력이 얼마야?")

        [후속 질문 처리]
        - 현재 질문이 닉네임만 바뀐 후속 질문이면("황로드유는?", "황로드유는 몇 개야?") 이전 대화의 주제(무엇을 묻고 있었는지)를 그대로 이어받아.
        - 예시: 이전 대화가 "작열 몇 개야?" → AI "3개야" 흐름이었다면, "황로드유는 몇 개야?"는 "황로드유의 작열 개수"로 해석해.
        - 질문을 해석할 때 이전 대화 맥락 전체를 참고해서 생략된 주제를 복원해.

        [이전 대화]
        {history}

        [사용자 질문]
        {question}

        """)

        structured_llm = self.llm.with_structured_output(QuestionAnalysis)
        chain = prompt | structured_llm
        
        history_text = ""
        if history:
            lines = [
                f"{'사용자' if m['role'] == 'user' else 'AI'}: {m['content']}"
                for m in history[-6:]
            ]
            history_text = "\n".join(lines)

        return chain.invoke({
            "question": question,
            "history": history_text or "없음",
            "candidates": candidates or [],
            })

        