from langchain_core.prompts import ChatPromptTemplate
from output_types import QuestionAnalysis, CharacterQueryType
from llm.sql_generator import UI_TABLE_MAP

class AnalysisGenerator:
    def __init__(self, llm):
        self.llm = llm

    def analyze(self, question: str, table_info: str, history: list[dict] | None = None) -> QuestionAnalysis:

        prompt = ChatPromptTemplate.from_template("""
        너는 로스트아크 질문 분석기야.
        질문을 분석해서 아래 JSON 형식으로만 답해.

        [목표]
        - intent 분류
        - UI 타입 결정
        - 닉네임 추출
        - 아이템명 추출
        - 필요한 테이블 선택

        --------------------------------------

        [INTENT 종류]
        - CHARACTER: 특정 캐릭터의 데이터 조회
        - COMPLEX: 계산, 비교, 필터링 등 추가 처리 필요
        - TRADING: 거래소 / 경매장 가격 관련
        - API: 실시간으로 API를 통해 데이터 요청
        - GENERAL: DB 조회 없이 게임 지식으로 답할 수 있는 질문, 또는 일반 대화

        --------------------------------------

        [UI_TYPE]
        - EXPEDITION: 원정대
        - SKILL, ENGRAVING, AVATAR, ARK_GRID, ARK_PASSIVE, COLLECTIBLE
        - MARKET_ITEMS, AUCTION_ITEMS
        - PROFILE: 사용자가 명시적으로 "프로필", "레벨", "능력치" 등을 언급했을 때만 사용.
        - TOTAL_INFO: 특정 카테고리(스킬 등) 언급 없이 닉네임만 있거나, "정보", "통합 정보", "전체 정보" 등 포괄적인 정보를 요청할 때의 **기본 UI 타입**.
        - ETC: INTENT가 "COMPLEX"일 경우 UI_TYPE은 반드시 "ETC"이다.

        --------------------------------------

        [TABLE 선택 기준]
        1. UI_TYPE이 'ETC'라면 아래 테이블 설명을 참고해서 필요한 테이블을 선택해.
        (여러 개 가능)

        {table_info}
        
        2. UI_TYPE이 'ETC'가 아니라면 아래 테이블 맵에서 매칭되는 테이블을 전부 가져와.

        {ui_table_map}

        3. UI_TYPE이 'EXPEDTION'라면 테이블은 빈 테이블을 반환해.

        --------------------------------------

        [닉네임 추출 규칙]
        - 조사 제거 (은,는,이,가,을,를,의 등)
        - 여러 명 가능
        - 현재 질문에 없으면 이전 대화에서 언급된 닉네임을 가져와
        - 그래도 없으면 []

        --------------------------------------

        [아이템명 추출]
        - MARKET 질문일 때만 추출
        - 가능한 경우 정식 명칭으로 변환

        --------------------------------------

        [판단 규칙]
        1. "몇", "갯수", "비교", "더", "높" → COMPLEX
        2. "가격", "시세", "거래소", "경매장", "얼마" → TRADING
        3. "스킬", "보석", "각인", "아바타", "장비", "아크그리드", "아크패시브", "능력치", "카드" → CHARACTER
        4. "원정대" → API
        5. 닉네임만 있거나, "정보", "통합 정보", "전체 정보" 등 특정 카테고리 없이 포괄적으로 묻는 경우 → TOTAL_INFO (intent: CHARACTER)
        6. DB 조회 없이 게임 지식으로 답할 수 있는 질문, 또는 "안녕" 같은 일반 대화 → GENERAL
        7. 애매하면 COMPLEX

        [is_specific_question 판단]
        - False: 데이터를 화면에 표시하길 원하는 경우 ("첫번째도구 스킬", "황로드유 각인 보여줘")
        - True: 특정 질문의 답변을 원하는 경우 ("카운터 스킬이 뭐야", "가장 높은 각인 레벨이 얼마야")

        --------------------------------------

        [출력 형식(JSON)]
        {{
        "intent": "...",
        "ui_type": "...",
        "relevant_tables": ["..."],
        "nicknames": ["..."],
        "item_name": "...",
        "is_comparison": true/false
        }}

        --------------------------------------

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
            "table_info": table_info,
            "ui_table_map": UI_TABLE_MAP,
            "history": history_text or "없음",
            })

        