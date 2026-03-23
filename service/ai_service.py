from sqlalchemy import text

from router.intent_router import IntentRouter
from sql.schema_builder import SchemaBuilder
from llm.sql_generator import SQLGenerator, UI_TABLE_MAP
from llm.analysis_generator import AnalysisGenerator
from llm.answer_generator import AnswerGenerator

from utils.text_parser import extract_nicknames
from api.lostark_api import get_expedition


class AIService:

    def __init__(self, llm, db):
        self.db = db
        self.router = IntentRouter()
        self.sql_generator = SQLGenerator(llm)
        self.analysis_generator = AnalysisGenerator(llm)
        self.answer_generator = AnswerGenerator(llm)
        self.schema_builder = SchemaBuilder(db)

    # 메인 함수
    def ask(self, question: str):
        nicknames = extract_nicknames(self.db, question)
        intent = self.router.route(question)

        if intent == "CHARACTER":
            return self._handle_character(question, nicknames)

        table_info = self.schema_builder.build_summary()
        analysis = self.analysis_generator.analyze(question, table_info)

        if analysis.ui_type == "TOTAL_INFO":
            target = nicknames[0] if nicknames else analysis.nicknames[0]
            return self._fetch_character_data(target, UI_TABLE_MAP["TOTAL_INFO"], "TOTAL_INFO")

        return self._handle_complex(question, analysis)

    # 캐릭터 관련 질문
    def _handle_character(self, question: str, nicknames: list):
        if not nicknames:
            return self.answer_generator.answer_general(question)

        ui_type = self.sql_generator._detect_ui_type(question)
        tables = UI_TABLE_MAP.get(ui_type, UI_TABLE_MAP["PROFILE"])
        return self._fetch_character_data(nicknames[0], tables, ui_type)

    # DB 접근 후 데이터 반환
    def _fetch_character_data(self, nickname: str, tables: list, ui_type: str) -> dict:
        queries = self.sql_generator.generate_character_json([nickname], tables)
        row = self.db.execute(text(queries[0]["sql"])).mappings().fetchone()
        return {"ui_type": ui_type, "data": dict(row) if row else {}}

    # 복잡한 질문 판단 및 
    def _handle_complex(self, question: str, analysis):
        schema = self.schema_builder.build(analysis.relevant_tables)
        sql = self.sql_generator.generate(question, analysis, schema)
        self._validate_tables(sql, schema)
        result = self.db.execute(text(sql)).mappings().all()
        return self.answer_generator.answer(question, result)

    # 할루시네이션 예외 처리
    def _validate_tables(self, sql: str, schema: dict):
        allowed = set(schema.keys())
        used = {word.split(".")[-1] for word in sql.split() if "lostark." in word}
        hallucinated = used - allowed
        if hallucinated:
            raise ValueError(f"LLM이 허용되지 않은 테이블을 사용했습니다: {hallucinated}")
                    