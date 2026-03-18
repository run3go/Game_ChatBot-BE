from sqlalchemy import text

from router.intent_router import IntentRouter
from sql.schema_builder import SchemaBuilder
from llm.sql_generator import SQLGenerator
from llm.analysis_generator import AnalysisGenerator
from llm.answer_generator import AnswerGenerator

from utils.text_parser import extract_nicknames
from api.lostark_api import get_expedition
from service.nickname_service import validate_nickname

class AIService:

    def __init__(self, llm, db):
        self.db = db
        self.router = IntentRouter()
        self.sql_generator = SQLGenerator(llm)
        self.analysis_generator = AnalysisGenerator(llm)
        self.answer_generator = AnswerGenerator(llm)
        self.schema_builder = SchemaBuilder(db)

    def ask(self, question: str):
        # 닉네임 파싱
        nicknames = extract_nicknames(self.db, question)

        # 사용자 의도 파악 및 라우팅
        intent = self.router.route(question)

        # 캐릭터 관련 질문
        if intent == "CHARACTER":
            queries, ui_type = self.sql_generator.generate_character(question, self.db, nicknames)

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

        if analysis.ui_type == "EXPEDITION" and analysis.intent == "API":
            target_name = nicknames[0] if nicknames else analysis.nicknames[0]
            print(target_name)
            data = get_expedition(target_name)
            
            return {
                "ui_type": analysis.ui_type,
                "data": data
            }

        schema = self.schema_builder.build(analysis.relevant_tables)
        sql = self.sql_generator.generate(question, analysis, schema)

        result = self.db.execute(text(sql)).mappings().all()

        answer = self.answer_generator.generate(question, result)

        return answer
                    