from sqlalchemy.exc import SQLAlchemyError, ProgrammingError
from sqlalchemy import text
from sql.schema_store import SCHEMA_STORE
from llm.sql_generator import SQLGenerator
from llm.analysis_generator import AnalysisGenerator
from llm.answer_generator import AnswerGenerator
from utils.chat_utils import extract_nicknames
from service.populator import DataPopulator
from constants import UI_TABLE_MAP, CHARACTER_TYPES
from output_types import QuestionAnalysis

class AIService:

    def __init__(self, llm, db):
        self.db = db
        self.sql_generator = SQLGenerator(llm)
        self.analysis_generator = AnalysisGenerator(llm)
        self.answer_generator = AnswerGenerator(llm)
        self.populator = DataPopulator(db)

    def ask(self, question: str, history: list[dict] | None = None):
        candidates = extract_nicknames(self.db, question)
        try:
            analysis = self.analysis_generator.analyze(question, history, candidates)
        except Exception:
            return ["잠시 후 다시 시도해 주세요."]

        nicknames = analysis.nicknames or candidates
        # DB 검증 없이 llm이 추측해서 뽑은 닉네임이 여러 개인 경우
        if not candidates and len(nicknames) > 1:
            # 신뢰도가 낮으므로 마지막 1개만 사용
            nicknames = nicknames[-1:]

        if analysis.category == "GENERAL":
            return self.answer_generator.answer_general(question, history)

        if analysis.category in CHARACTER_TYPES and not nicknames:
            return ["어떤 캐릭터에 대해 알고 싶으신가요? 닉네임을 알려주세요!"]

        try:
            result = self._handle_complex(question, nicknames, analysis, history)
        except ValueError:
            return ["질문을 좀 더 구체적으로 해주시면 더 잘 답변드릴 수 있어요."]
        except Exception:
            return ["잠시 후 다시 시도해 주세요."]

        if isinstance(result, dict):
            result['nicknames'] = analysis.nicknames
            result['keywords'] = analysis.keywords
        return result

    def _handle_complex(self, question: str, nicknames: list, analysis : QuestionAnalysis, history: list[dict]):
        tables = SCHEMA_STORE.search(analysis.keywords)
        schema = SCHEMA_STORE.get_schema(tables)

        # CHARACTER 카테고리(DISPLAY)는 카테고리 테이블 전체를 schema에 보강
        if analysis.category in CHARACTER_TYPES and analysis.response_format == "DISPLAY":
            required = UI_TABLE_MAP.get(analysis.category, [])
            extra = SCHEMA_STORE.get_schema([t for t in required if t not in schema])
            schema.update(extra)

        sql, ui_type = self.sql_generator.generate(question, analysis, schema, nicknames)

        # 할루시네이션 방지: 허용되지 않은 테이블 사용 시 에러 피드백과 함께 1회 재시도
        for attempt in range(2):
            used = {w.split(".")[-1] for w in sql.split() if "lostark." in w}
            invalid = used - set(schema.keys())
            if not invalid:
                break
            if attempt == 1:
                raise ValueError(f"LLM이 허용되지 않은 테이블을 사용했습니다: {invalid}")
            
            sql, ui_type = self.sql_generator.generate(question, analysis, schema, nicknames, error=f"허용되지 않은 테이블 사용: {invalid}. 반드시 [스키마]에 있는 테이블만 사용해.")

        if ui_type != "TEXT" and ui_type in UI_TABLE_MAP:
            if not nicknames:
                result = self._execute_sql(sql, False, question, analysis, schema, nicknames)
                return self.answer_generator.answer(question, result or [], history)
            
            row = self._execute_sql(sql, True, question, analysis, nicknames, history)
            data = dict(row) if row else {}

            # LLM이 잘못된 별칭을 쓸 시 보정
            unknown_keys = [k for k in data if k not in schema]
            unmatched_tables = [t for t in used if t not in data]
            if len(unknown_keys) == len(unmatched_tables) == 1:
                data[unmatched_tables[0]] = data.pop(unknown_keys[0])

            # SQL 필터 조건에 맞는 결과가 없으면 텍스트 답변으로 처리
            if data and all(isinstance(v, list) and len(v) == 0 for v in data.values()):
                return self.answer_generator.answer(question, [], history)

            missing = [t for t in UI_TABLE_MAP[ui_type] if t not in data]
            if missing:
                data.update(self._fetch_missing_tables(nicknames[0], missing))

            data = self.populator.populate(ui_type, data)

            return {"ui_type": ui_type, "data": data, "nickname": nicknames[0]}
        
        result = self._execute_sql(sql, False, question, analysis, schema, nicknames)
        if result is None:
            return ["질문을 좀 더 구체적으로 해주시면 더 잘 답변드릴 수 있어요."]
        return self.answer_generator.answer(question, result, history)
 
    # 누락 테이블 fetch
    def _fetch_missing_tables(self, nickname: str, tables: list) -> dict:
        subqueries = ",\n".join(
            f"  (SELECT COALESCE(json_agg(t.*), '[]'::json) FROM lostark.{table} t "
            f"WHERE t.character_name = :nickname AND t.collected_at = "
            f"(SELECT MAX(t2.collected_at) FROM lostark.{table} t2 WHERE t2.character_name = :nickname)) AS {table}"
            for table in tables
        )
        try:
            row = self.db.execute(text(f"SELECT\n{subqueries}"), {"nickname": nickname}).mappings().fetchone()
            return dict(row) if row else {}
        except SQLAlchemyError:
            return {}
        
    def _execute_sql(self, sql: str, fetch_one: bool, question: str, analysis : QuestionAnalysis, schema, nicknames: list):
        for attempt in range(2):
            try:
                result = self.db.execute(text(sql))
                return result.mappings().fetchone() if fetch_one else result.mappings().all()
            except ProgrammingError as e:
                if attempt == 1:
                    return None
                sql, _ = self.sql_generator.generate(
                    question, analysis, schema, nicknames,
                    error=f"SQL 실행 오류: {str(e.orig)}"
                )

