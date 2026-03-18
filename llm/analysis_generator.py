from langchain_core.prompts import ChatPromptTemplate
from output_types import QuestionAnalysis
from llm.sql_generator import UI_TABLE_MAP

class AnalysisGenerator:
    def __init__(self, llm):
        self.llm = llm

    def analyze(self, question: str, table_info: str):

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
        - CHARACTER: 캐릭터 정보 단순 조회 (목록 그대로 보여주면 되는 경우)
        - COMPLEX: 계산, 비교, 필터링 등 추가 처리 필요
        - TRADING: 거래소 / 경매장 가격 관련

        --------------------------------------

        [UI_TYPE]
        - SKILL, ENGRAVING, AVATAR, ARK_GRID, ARK_PASSIVE, COLLECTIBLE
        - MARKET_ITEMS, AUCTION_ITEMS
        - PROFILE: 사용자가 명시적으로 "프로필", "레벨", "능력치" 등을 언급했을 때만 사용.
        - TOTAL_INFO: 특정 카테고리(스킬 등) 언급 없이 닉네임만 있거나 "정보"를 요청할 때의 **기본 UI 타입**.
        - ETC: INTENT가 "COMPLEX"일 경우 UI_TYPE은 반드시 "ETC"이다.

        --------------------------------------

        [TABLE 선택 기준]
        1. UI_TYPE이 'ETC'라면 아래 테이블 설명을 참고해서 필요한 테이블을 선택해.
        (여러 개 가능)

        {table_info}
        
        2. UI_TYPE이 'ETC'가 아니라면 아래 테이블 맵에서 매칭되는 테이블을 전부 가져와.

        {ui_table_map}

        --------------------------------------

        [닉네임 추출 규칙]
        - 조사 제거 (은,는,이,가,을,를,의 등)
        - 여러 명 가능
        - 없으면 []

        --------------------------------------

        [아이템명 추출]
        - MARKET 질문일 때만 추출
        - 가능한 경우 정식 명칭으로 변환

        --------------------------------------

        [판단 규칙]
        1. "몇", "갯수", "비교", "더", "높" → COMPLEX
        2. "가격", "시세", "거래소", "경매장", "얼마" → TRADING
        3. "스킬", "보석", "각인", "아바타", "장비", "아크그리드", "아크패시브", "능력치", "카드" → CHARACTER
        4. 애매하면 COMPLEX

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

        [사용자 질문]
        {question}
                                                  
        """)

        structured_llm = self.llm.with_structured_output(QuestionAnalysis)
        chain = prompt | structured_llm
        
        return chain.invoke({
            "question": question, 
            "table_info": table_info, 
            "ui_table_map": UI_TABLE_MAP
            })
        