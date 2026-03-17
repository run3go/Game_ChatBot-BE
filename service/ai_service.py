from sqlalchemy import text

from router.intent_router import IntentRouter
from llm.sql_generator import SQLGenerator

class AIService:

    def __init__(self, llm):
        self.router = IntentRouter()
        self.sql_generator = SQLGenerator(llm)

    def ask(self, question, db):

        # 사용자 의도 파악 및 라우팅
        intent = self.router.route(question)

        # 캐릭터 관련 질문
        if intent == "CHARACTER":
            queries, ui_type = self.sql_generator.generate_character(question, db)

            data = {}

            for q in queries:
                result = db.execute(text(q["sql"])).mappings().all()
                data[q["table"]] = result

            return {
                "ui_type": ui_type,
                "data": data
            }
        
        # if intent == "TRADING":
        
        # if intent == "COMPLEX":
                    