from sqlalchemy import text

from sql.schema_store import SCHEMA_STORE
from llm.sql_generator import SQLGenerator, UI_TABLE_MAP
from llm.analysis_generator import AnalysisGenerator
from llm.answer_generator import AnswerGenerator
from utils.text_parser import extract_nicknames

CHARACTER_TYPES = set(UI_TABLE_MAP.keys())


class AIService:

    def __init__(self, llm, db):
        self.db = db
        self.sql_generator = SQLGenerator(llm)
        self.analysis_generator = AnalysisGenerator(llm)
        self.answer_generator = AnswerGenerator(llm)

    def ask(self, question: str, pending: dict | None = None, history: list[dict] | None = None):
        # 비교 재질문 처리
        if pending:
            nicknames = extract_nicknames(self.db, question)
            target = nicknames[0] if nicknames else question.strip()
            return self._fetch_display(target, pending["tables"], pending["ui_type"])

        candidates = extract_nicknames(self.db, question)
        analysis = self.analysis_generator.analyze(question, history, candidates)

        nicknames = analysis.nicknames or candidates
        if not candidates and len(nicknames) > 1:
            nicknames = nicknames[-1:]

        if analysis.query_type == "GENERAL":
            return self.answer_generator.answer_general(question, history)

        if analysis.query_type in CHARACTER_TYPES:
            if not nicknames:
                return self.answer_generator.answer_general(question, history)

            query_type = analysis.query_type
            tables = UI_TABLE_MAP.get(query_type, UI_TABLE_MAP["PROFILE"])

            # 비교인데 캐릭터가 1명뿐이면 재질문
            if len(nicknames) == 1 and analysis.aggregation_type == "COMPARE":
                return {
                    "ui_type": "FOLLOW_UP",
                    "message": f"**{nicknames[0]}** 말고 비교할 다른 캐릭터 닉네임을 알려주세요!",
                    "pending": {"ui_type": query_type, "tables": tables},
                    "nicknames": analysis.nicknames,
                    "keywords": analysis.keywords,
                }

            # COUNT/VALUE/COMPARE → 전체 데이터 fetch 후 LLM 텍스트 답변
            if analysis.aggregation_type not in ("DISPLAY"):
                data = self._fetch_character_data(nicknames[0], tables)
                return self.answer_generator.answer(question, [data] if data else [], history)

        result = self._handle_complex(question, nicknames, analysis, history)
        if isinstance(result, dict):
            result['nicknames'] = analysis.nicknames
            result['keywords'] = analysis.keywords
        return result

    def _handle_complex(self, question: str, nicknames: list, analysis, history: list[dict]):
        table_info = SCHEMA_STORE.search(analysis.keywords)
        schema = SCHEMA_STORE.get_schema(list(table_info.keys()))

        # CHARACTER 카테고리(DISPLAY/LIST)는 카테고리 테이블 전체를 schema에 보강
        if analysis.query_type in CHARACTER_TYPES and analysis.aggregation_type == "DISPLAY":
            required = UI_TABLE_MAP.get(analysis.query_type, [])
            extra = SCHEMA_STORE.get_schema([t for t in required if t not in schema])
            schema.update(extra)

        # 캐릭터 데이터가 필요한데 닉네임이 없으면 재질문
        needs_character = any(
            col["column"] == "character_name"
            for t in schema.values()
            for col in t.get("columns", [])
        )
        if not nicknames and needs_character:
            return {"ui_type": "FOLLOW_UP", "message": "어떤 캐릭터에 대해 알고 싶으신가요? 닉네임을 알려주세요!", "pending": None}

        sql, ui_type = self.sql_generator.generate(question, analysis, schema, nicknames)

        # 할루시네이션 방지
        used = {w.split(".")[-1] for w in sql.split() if "lostark." in w}
        if used - set(schema.keys()):
            raise ValueError(f"LLM이 허용되지 않은 테이블을 사용했습니다: {used - set(schema.keys())}")

        # DISPLAY/LIST 카테고리: LLM SQL 결과 사용, 누락 테이블은 보충
        if ui_type != "TEXT" and nicknames and ui_type in UI_TABLE_MAP:
            row = self.db.execute(text(sql)).mappings().fetchone()
            data = dict(row) if row else {}

            # SQL 필터 조건에 맞는 결과가 없으면 텍스트 답변으로 처리 (보충 전에 확인)
            if data and all(isinstance(v, list) and len(v) == 0 for v in data.values()):
                return self.answer_generator.answer(question, [], history)

            missing = [t for t in UI_TABLE_MAP[ui_type] if t not in data]
            if missing:
                data.update(self._fetch_character_data(nicknames[0], missing))

            return {"ui_type": ui_type, "data": data, "nickname": nicknames[0]}

        result = self.db.execute(text(sql)).mappings().all()
        return self.answer_generator.answer(question, result, history)

    def _fetch_character_data(self, nickname: str, tables: list) -> dict:
        queries = self.sql_generator.generate_character_json([nickname], tables)
        row = self.db.execute(text(queries[0]["sql"])).mappings().fetchone()
        return dict(row) if row else {}

    def _fetch_display(self, nickname: str, tables: list, ui_type: str) -> dict:
        return {"ui_type": ui_type, "data": self._fetch_character_data(nickname, tables), "nickname": nickname}
