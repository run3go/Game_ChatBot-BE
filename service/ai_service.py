from sqlalchemy import text

from router.intent_router import IntentRouter
from llm.sql_generator import SQLGenerator
from sql.schema_builder import SchemaBuilder
from llm.analysis_generator import AnalysisGenerator
from llm.answer_generator import AnswerGenerator

class AIService:

    def __init__(self, llm, db):
        self.db = db
        self.router = IntentRouter()
        self.sql_generator = SQLGenerator(llm)
        self.analysis_generator = AnalysisGenerator(llm)
        self.answer_generator = AnswerGenerator(llm)
        self.schema_builder = SchemaBuilder(db)

    def ask(self, question):

        # 사용자 의도 파악 및 라우팅
        intent = self.router.route(question)

        # 캐릭터 관련 질문
        if intent == "CHARACTER":
            queries, ui_type = self.sql_generator.generate_character(question, self.db)

            data = {}

            for q in queries:
                result = self.db.execute(text(q["sql"])).mappings().all()
                data[q["table"]] = result

            return {
                "ui_type": ui_type,
                "data": data
            }
        
        # if intent == "TRADING":
        
        # if intent == "COMPLEX":
        table_info = self.schema_builder.build_summary()
        analysis = self.analysis_generator.analyze(question, table_info)

        schema = self.schema_builder.build(analysis.relevant_tables)
        sql = self.sql_generator.generate(question, analysis, schema)

        result = self.db.execute(text(sql)).mappings().all()

        answer = self.answer_generator.generate(question, result)

        return answer
                    