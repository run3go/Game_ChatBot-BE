from sqlalchemy import text

from sql.schema_store import SCHEMA_STORE
from llm.sql_generator import SQLGenerator, UI_TABLE_MAP
from llm.analysis_generator import AnalysisGenerator
from llm.answer_generator import AnswerGenerator

from utils.text_parser import extract_nicknames


class AIService:

    def __init__(self, llm, db):
        self.db = db
        self.sql_generator = SQLGenerator(llm)
        self.analysis_generator = AnalysisGenerator(llm)
        self.answer_generator = AnswerGenerator(llm)


    # 메인 함수
    def ask(self, question: str, pending: dict | None = None, history: list[dict] | None = None):
        if pending:
            return self._resolve_pending(question, pending)

        table_info = SCHEMA_STORE.search(question)
        candidates = extract_nicknames(self.db, question)
        analysis = self.analysis_generator.analyze(question, history, candidates)

        nicknames = analysis.nicknames or candidates

        # 현재 질문에 닉네임이 없어서 히스토리에서 가져온 경우, 최근 1개로 제한
        if not candidates and len(nicknames) > 1:
            nicknames = nicknames[-1:]

        if analysis.intent == "GENERAL":
            return self.answer_generator.answer_general(question, history)

        if analysis.intent == "CHARACTER":
            return self._handle_character(question, nicknames, analysis, history)

        return self._handle_complex(question, analysis, history, table_info)

    # 캐릭터 관련 질문
    def _handle_character(self, question: str, nicknames: list, analysis, history: list[dict] | None = None):
        if not nicknames:
            return self.answer_generator.answer_general(question, history)

        ui_type = analysis.ui_type
        tables = UI_TABLE_MAP.get(ui_type, UI_TABLE_MAP["PROFILE"])

        if len(nicknames) == 1 and analysis.aggregation_type == "COMPARE":
            return {
                "ui_type": "FOLLOW_UP",
                "message": f"**{nicknames[0]}** 말고 비교할 다른 캐릭터 닉네임을 알려주세요!",
                "pending": {"ui_type": ui_type, "tables": tables},
            }

        if analysis.aggregation_type != "DISPLAY":
            queries = self.sql_generator.generate_character_json([nicknames[0]], tables)
            row = self.db.execute(text(queries[0]["sql"])).mappings().fetchone()
            data = [dict(row)] if row else []
            return self.answer_generator.answer(question, data, history)

        return self._fetch_character_data(nicknames[0], tables, ui_type)

    # 재질문 응답 처리
    def _resolve_pending(self, answer: str, pending: dict):
        nicknames = extract_nicknames(self.db, answer)
        target = nicknames[0] if nicknames else answer.strip()
        return self._fetch_character_data(target, pending["tables"], pending["ui_type"])

    # DB 접근 후 데이터 반환
    def _fetch_character_data(self, nickname: str, tables: list, ui_type: str) -> dict:
        queries = self.sql_generator.generate_character_json([nickname], tables)
        row = self.db.execute(text(queries[0]["sql"])).mappings().fetchone()
        return {"ui_type": ui_type, "data": dict(row) if row else {}, "nickname": nickname}

    # 복잡한 질문 처리
    def _handle_complex(self, question: str, analysis, history: list[dict], table_info: dict):
        schema = SCHEMA_STORE.get_schema(list(table_info.keys()))
        sql = self.sql_generator.generate(question, analysis, schema)
        self._validate_tables(sql, schema)
        result = self.db.execute(text(sql)).mappings().all()
        return self.answer_generator.answer(question, result, history)

    # 할루시네이션 예외 처리
    def _validate_tables(self, sql: str, schema: dict):
        allowed = set(schema.keys())
        used = {word.split(".")[-1] for word in sql.split() if "lostark." in word}
        hallucinated = used - allowed
        if hallucinated:
            raise ValueError(f"LLM이 허용되지 않은 테이블을 사용했습니다: {hallucinated}")
