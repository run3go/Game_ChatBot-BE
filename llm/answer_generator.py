import json
import logging
from datetime import datetime, date
from langchain_core.prompts import ChatPromptTemplate
from utils.chat_utils import format_history

logger = logging.getLogger(__name__)

def _json_default(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    return float(obj)

class AnswerGenerator:

    def __init__(self, llm):
        self.llm = llm

    def answer_general(self, question: str, history: list[dict] | None = None):
        prompt = ChatPromptTemplate.from_template("""
            너는 로스트아크 AI 비서야.
            DB 조회 없이 게임 지식을 바탕으로 질문에 답해.
            답변은 간결하고 정확하게 마크다운 형식으로 작성해.
            이전 대화 맥락을 반드시 참고해서 답해.

            [이전 대화]
            {history}

            [질문]
            {question}
        """)
        history_text = format_history(history, limit=10) if history else ""

        chain = (prompt | self.llm).with_retry(stop_after_attempt=2)
        try:
            for chunk in chain.stream({"question": question, "history": history_text or "없음"}):
                yield chunk.content
        except Exception:
            logger.exception("answer_general 스트리밍 실패")
            yield "잠시 후 다시 시도해 주세요."

    def answer_display(self, question: str, ui_type: str, data: dict, history: list[dict] | None = None):
        prompt = ChatPromptTemplate.from_template("""
            너는 로스트아크 AI 비서야.
            아래 데이터는 이미 UI로 화면에 표시됐어.
            UI 내용을 그대로 나열하지 말고, 핵심 포인트나 주목할 점을 간결하게 코멘트해줘.
            답변은 마크다운 형식으로 작성해.
            이전 대화 맥락을 반드시 참고해서 답해.

            [UI 타입]
            {ui_type}

            [이전 대화]
            {history}

            [질문]
            {question}

            [데이터(JSON)]
            {data}
        """)
        history_text = format_history(history, limit=10) if history else ""

        chain = (prompt | self.llm).with_retry(stop_after_attempt=2)
        try:
            for chunk in chain.stream({
                "question": question,
                "ui_type": ui_type,
                "data": json.dumps(data, ensure_ascii=False, default=_json_default),
                "history": history_text or "없음",
            }):
                yield chunk.content
        except Exception:
            logger.exception("answer_display 스트리밍 실패")
            yield "잠시 후 다시 시도해 주세요."

    def answer(self, question: str, data, history: list[dict] | None = None):
        data = [dict(row) for row in data]

        prompt = ChatPromptTemplate.from_template("""
            너는 로스트아크 AI 비서야.
            데이터를 기반으로 자연스럽게 설명해.

            [판단 지침]
            - 데이터가 배열일 경우, 결과에 모든 원소를 포함해.
            - 데이터가 빈 배열일 경우, 사용자에게 해당하는 데이터가 없음을 나타내.

            [UI 적용 가이드]
            - 수치/능력치 비교: 반드시 표를 사용하고, 더 높은 값에 볼드체. 비교 수치가 하나일 때만 차잇값 표시. 표는 하나로 통합.
            - 스킬 비교: 차이가 있는 스킬만 ### 스킬명 섹션으로 출력. 각 섹션 안에서 다른 항목(트라이포드·룬 이름·룬 등급·스킬 레벨)만 불렛으로 나열. 형식: `- 항목: **캐릭터A** 값A / **캐릭터B** 값B`. 모든 항목이 같은 스킬은 출력하지 마.
            - 시점 간 변화 비교(is_changed 컬럼이 있는 경우): 변경된 항목(is_changed = 'O')만 ### 항목명 섹션으로 출력.
              변경 시점은 항목명 바로 아래에 `> 📅 MM월 DD일 → MM월 DD일 변경` 형식으로 표시 (인용구 스타일).
              그 아래 prev_* 컬럼(이전값)과 current_*/현재 컬럼(현재값)을 대응시켜 변경된 필드만 불렛으로 나열. 형식: `- 필드명: 이전값 → **현재값**`. NULL이면 (없음)으로 표시. 변경 없는 항목은 출력하지 마.
            - 아크 그리드: 👤 닉네임을 제목으로 쓰고 슬롯 분류/코어 이름/등급/포인트 표로 출력. 비교 시 캐릭터별 각각 작성.
            - 각인: 불렛 포인트로 나열 (어빌리티 스톤 0레벨 제외)
            - 아크 패시브 비교: 두 캐릭터의 깨달음 1티어 효과명을 대조.
                - 같을 경우: 아래 두 표를 순서대로 출력.
                    1) 포인트/레벨 통합 표: 컬럼은 반드시 `구분 | 캐릭터 | 진화 (P/Lv) | 깨달음 (P/Lv) | 도약 (P/Lv)` 형식. 포인트와 레벨은 `/`로 합쳐 한 셀에 표시 (예: 140 / 6랭크 26Lv). 더 높은 포인트 또는 더 높은 레벨 값에 볼드체.
                    2) 상세 효과 비교: 진화/깨달음/도약 순으로 번호 섹션(1. 진화, 2. 깨달음, 3. 도약). 각 섹션은 `티어 | 캐릭터A | 캐릭터B` 컬럼의 표로 모든 티어를 출력. 효과는 불렛(•)으로 표시. 한 셀에 여러 효과가 있을 경우 `<br>`로 구분해. 같은 티어에서 서로 다른 효과에만 볼드체. 효과명 옆에 괄호치고 레벨 표시 (Lv.2).
                - 다를 경우: 포인트/레벨 통합 표만 출력. 볼드체 금지.
            - 이외 추가 분석 금지.

            [금지]
            - "판단", "비교한 결과", "효과가 달라서", "~만 비교했습니다" 사용 금지
            - 분석 과정/필터링 기준 설명 금지
            - 처음부터 해당 데이터만 존재했던 것처럼 담백하게 출력
            - 응답을 코드블록(```)으로 감싸지 마. 마크다운을 직접 출력.

            [이전 대화]
            {history}

            [질문]
            {question}

            [데이터(JSON)]
            {data}
        """)

        history_text = format_history(history, limit=10) if history else ""

        chain = (prompt | self.llm).with_retry(stop_after_attempt=2)

        try:
            for chunk in chain.stream({
                "question": question,
                "data": json.dumps(data, ensure_ascii=False, default=_json_default),
                "history": history_text or "없음",
            }):
                yield chunk.content

        except Exception:
            logger.exception("answer 스트리밍 실패")
            yield "잠시 후 다시 시도해 주세요."