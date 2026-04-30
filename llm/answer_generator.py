import json
import time
import logging
from datetime import datetime, date
from langchain_core.prompts import ChatPromptTemplate
from utils.chat_utils import format_history
from game_knowledge import GAME_KNOWLEDGE
from llm.llm_monitor import log_llm_call, TokenCountCallback

logger = logging.getLogger(__name__)

def _json_default(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    return float(obj)

def _strip_datetime_to_date(data: list[dict]) -> list[dict]:
    return [
        {k: v.date() if isinstance(v, datetime) else v for k, v in row.items()}
        for row in data
    ]

class AnswerGenerator:

    def __init__(self, llm):
        self.llm = llm
        self.model_name = getattr(llm, "model_name", getattr(llm, "model", "unknown"))

    def _chain(self, prompt):
        return (prompt | self.llm).with_retry(stop_after_attempt=2)

    def _history(self, history, limit=10) -> str:
        return format_history(history, limit=limit) if history else "없음"

    def _stream_with_monitor(self, chain, inputs: dict, label: str, detail: dict):
        start_time = time.time()
        collected_chunks = []
        cb = TokenCountCallback()

        try:
            for chunk in chain.stream(inputs, config={"callbacks": [cb]}):
                collected_chunks.append(chunk.content)
                yield chunk.content

            log_llm_call(
                generator_type="answer",
                model_name=self.model_name,
                start_time=start_time,
                callback=cb,
                detail={
                    **detail,
                    "output": {
                        "answer_length": sum(len(c) for c in collected_chunks),
                        "chunk_count": len(collected_chunks),
                    },
                },
            )
        except Exception as e:
            logger.exception("%s 스트리밍 실패", label)
            log_llm_call(
                generator_type="answer",
                model_name=self.model_name,
                start_time=start_time,
                callback=cb,
                success=False,
                error_message=str(e),
                detail=detail,
            )
            yield "잠시 후 다시 시도해 주세요."

    def answer_general(self, question: str, history: list[dict] | None = None):
        prompt = ChatPromptTemplate.from_template("""
            너는 로스트아크 AI 비서야.
            DB 조회 없이 게임 지식을 바탕으로 질문에 답해.
            답변은 간결하고 정확하게 마크다운 형식으로 작성해.
            이전 대화 맥락을 반드시 참고해서 답해.

            [게임 은어/약어]
            {game_knowledge}

            [이전 대화]
            {history}

            [질문]
            {question}
        """)
        detail = {
            "input": {"data": "없음 (GENERAL)"},
            "method": "answer_general",
        }
        yield from self._stream_with_monitor(self._chain(prompt), {
            "question": question,
            "history": self._history(history),
            "game_knowledge": GAME_KNOWLEDGE,
        }, "answer_general", detail)

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
        data_json = json.dumps(data, ensure_ascii=False, default=_json_default)
        detail = {
            "input": {"data_size": len(data_json)},
            "method": "answer_display",
        }
        yield from self._stream_with_monitor(self._chain(prompt), {
            "question": question,
            "ui_type": ui_type,
            "data": data_json,
            "history": self._history(history),
        }, "answer_display", detail)

    def answer(self, question: str, data, history: list[dict] | None = None, category: str = ""):
        data = [dict(row) for row in data]
        if category in {"MARKET", "AUCTION"}:
            data = _strip_datetime_to_date(data)

        prompt = ChatPromptTemplate.from_template("""
            너는 로스트아크 AI 비서야.
            데이터를 기반으로 자연스럽게 설명해.

            [게임 은어/약어]
            {game_knowledge}

            [판단 지침]
            - 제공된 데이터는 이미 DB에서 조회된 최종 결과야. 질문의 표현("첫번째", "특정 캐릭터" 등)을 근거로 데이터를 추가 필터링하거나 일부 행만 선택하지 마.
            - 데이터가 배열일 경우, 결과에 모든 원소를 포함해.
            - 데이터가 빈 배열일 경우, 사용자에게 해당하는 데이터가 없음을 나타내.
            - 질문이 개수·수치·특정 필드만 묻더라도, 관련 항목의 목록·세부 내용을 함께 출력해. 숫자만 단독으로 답하지 마.

            [UI 적용 가이드]
            - 수치/능력치 비교: 반드시 표 하나로 통합. 더 높은 값에 볼드체. 비교 수치가 하나일 때만 차잇값 표시.
            - 장비 비교:
                - 무기/상의/어깨/장갑/투구/하의: 강화(재련)와 품질만 비교. 나머지 항목은 출력 금지.
                - 반지/귀걸이/목걸이: 이름과 체력을 제외한 모든 항목 비교.
                - 위 두 분류 외 장비(예: 보주 등): 모든 항목 그대로 비교.
            - 스킬 비교: 차이 있는 스킬만 ### 스킬명 섹션으로 출력. 다른 항목(트라이포드·룬 이름·룬 등급·스킬 레벨)만 불렛 나열. 형식: `- 항목: **캐릭터A** 값A / **캐릭터B** 값B`. 모든 항목 동일한 스킬은 출력 금지.
            - 시점 간 변화 비교(is_changed 컬럼이 있는 경우): 변경된 항목(is_changed = 'O')만 ### 항목명 섹션으로 출력.
              섹션 아래 `> 📅 기간: MM월 DD일 HH시 → MM월 DD일 HH시` (이른 시작 ~ 늦은 끝 시각) 한 줄 표시.
              각 변경 시점을 `- **MM월 DD일 HH시**` (끝 시각 기준) 불렛으로 나열, 변경된 필드만 `  - 필드명: 이전값 → **현재값**` 들여쓰기. NULL이면 (없음).
            - 아크 그리드: 👤 닉네임을 제목으로, 슬롯 분류/코어 이름/등급/포인트 표 출력. 비교 시 캐릭터별 각각 작성.
            - 각인: 반드시 하나의 표로 통합하여 비교.
                - 컬럼: `각인명 | 캐릭터A | 캐릭터B`
                - [볼드체 규칙] — 반드시 테이블 셀 안에 `**...**`를 직접 삽입:
                    - 양쪽 보유 시: Lv. 숫자 먼저 비교. Lv.가 같으면 돌 숫자 비교. 더 높은 셀에만 `**...**` 적용.
                    - 한쪽 보유 시: 보유한 쪽 셀에만 `**...**` 적용.
                    - Lv.와 돌 숫자까지 완전히 동일하면 볼드체 절대 금지.
                - [형식]: 등급 Lv.숫자 (돌: 숫자) 형태 유지.
                - [출력 예시]:
                  | 각인명 | 캐릭터A | 캐릭터B |
                  |---|---|---|
                  | 원한 | **유물 Lv.4 (돌: 없음)** | 유물 Lv.3 (돌: 2) |
                  | 슈퍼 차지 | 유물 Lv.4 (돌: 없음) | 유물 Lv.4 (돌: 없음) |
                  | 결투의 대가 | 유물 Lv.4 (돌: 없음) | **유물 Lv.4 (돌: 2)** |
                  | 마나 효율 증가 | (없음) | **유물 Lv.4 (돌: 없음)** |
                  | 저주받은 인형 | **유물 Lv.4 (돌: 2)** | (없음) |
            - 아크 패시브 비교: 두 캐릭터의 깨달음 1티어 효과명을 대조.
                - 같을 경우: ①포인트/레벨 통합 표 (컬럼: `구분|캐릭터|진화 (P/Lv)|깨달음 (P/Lv)|도약 (P/Lv)`, 포인트·레벨 `/`로 한 셀에, 더 높은 값 볼드체), ②상세 효과 비교 (진화/깨달음/도약 순 번호 섹션, 각 섹션은 `티어|캐릭터A|캐릭터B` 표, 효과는 •로 표시·여러 효과 `<br>` 구분, 다른 효과에만 볼드체, 효과명 뒤 레벨 표시 (Lv.2)).
                - 다를 경우: 포인트/레벨 통합 표만 출력. 볼드체 금지.
            - 레벨 조회: 아이템 레벨과 캐릭터 레벨을 항상 함께 출력.
            - 이외 추가 분석 금지.

            [금지]
            - "판단", "비교한 결과", "효과가 달라서", "~만 비교했습니다" 사용 금지
            - 분석 과정/필터링 기준 설명 금지
            - 처음부터 해당 데이터만 존재했던 것처럼 담백하게 출력
            - 응답을 코드블록(```)으로 감싸지 마. 마크다운을 직접 출력.
            - 가격·수치 단위는 항상 "골드"로 표시. "원" 사용 금지.

            [후속 질문 제안]
            답변이 끝난 뒤, 사용자가 자연스럽게 이어서 궁금해할 만한 질문이 있으면 1개만 제안해.
            - 개수·수치 답변(예: "6개입니다") 뒤에 목록 확인 질문, 단순 조회 뒤 상세 질문 등 맥락상 유용한 경우에만 추가.
            - 답변이 이미 충분히 상세하거나(비교·목록·분석 결과), 제안할 만한 질문이 딱히 없으면 생략.
            - 캐릭터명이 있으면 반드시 포함해서 구체적으로 작성.
            - 반드시 반말·구어체로 작성. 예) "황로드유의 차징 목록은 어떤게 있어?", "황로드유의 다른 스킬 개수는 어떻게 돼?"
            형식 (제안할 때만):
            ---
            이런 것도 물어볼 수 있어요
            - [질문 1]

            [이전 대화]
            {history}

            [질문]
            {question}

            [데이터(JSON)]
            {data}
        """)
        data_json = json.dumps(data, ensure_ascii=False, default=_json_default)
        detail = {
            "input": {
                "data_row_count": len(data),
                "data_size": len(data_json),
            },
            "method": "answer",
        }
        yield from self._stream_with_monitor(self._chain(prompt), {
            "question": question,
            "data": data_json,
            "history": self._history(history),
            "game_knowledge": GAME_KNOWLEDGE,
        }, "answer", detail)
