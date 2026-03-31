import logging
import traceback
from sqlalchemy.exc import ProgrammingError
from sqlalchemy import text
from sql.schema_store import SCHEMA_STORE
from llm.sql_generator import SQLGenerator
from llm.analysis_generator import AnalysisGenerator
from llm.answer_generator import AnswerGenerator
from utils.chat_utils import extract_nicknames
from service.nickname_service import validate_nicknames_batch
from service.populator import DataPopulator
from constants import UI_TABLE_MAP, CHARACTER_TYPES
from output_types import QuestionAnalysis

logger = logging.getLogger(__name__)

class AIService:

    def __init__(self, llm, db):
        self.db = db
        self.sql_generator = SQLGenerator(llm)
        self.analysis_generator = AnalysisGenerator(llm)
        self.answer_generator = AnswerGenerator(llm)
        self.populator = DataPopulator(db)

    def ask(self, question: str, history: list[dict] | None = None):
        candidates = extract_nicknames(self.db, question)

        yield "status", "질문을 분석하는 중이에요..."
        try:
            analysis = self.analysis_generator.analyze(question, history, candidates)
        except Exception as e:
            logger.error("분석 실패: %s\n%s", e, traceback.format_exc())
            yield "result", ["잠시 후 다시 시도해 주세요."]
            return

        nicknames, unverified = self._resolve_nicknames(candidates, analysis.nicknames)

        if analysis.category == "GENERAL":
            yield "status", "답변을 생성하는 중이에요..."
            yield "result", self.answer_generator.answer_general(question, history)
            return

        if analysis.category in CHARACTER_TYPES and not nicknames:
            if unverified:
                nickname = unverified[0]
                yield "result", {
                    "ui_type": "CONFIRM_COLLECT",
                    "nickname": nickname,
                    "message": f"'{nickname}' 캐릭터 정보가 존재하지 않습니다. 데이터를 수집할까요? (예/아니오)",
                }
            else:
                yield "result", ["어떤 캐릭터에 대해 알고 싶으신가요? 닉네임을 알려주세요!"]
            return

        yield "status", "데이터를 조회하는 중이에요..."
        try:
            result = self._handle_complex(question, nicknames, analysis, history)
        except ValueError as e:
            logger.warning("질문 처리 실패 (ValueError): %s", e)
            yield "result", ["질문을 좀 더 구체적으로 해주시면 더 잘 답변드릴 수 있어요."]
            return
        except Exception as e:
            logger.error("데이터 조회 실패: %s\n%s", e, traceback.format_exc())
            yield "result", ["잠시 후 다시 시도해 주세요."]
            return

        if isinstance(result, dict):
            result['nicknames'] = analysis.nicknames
            result['keywords'] = analysis.keywords
        yield "result", result

    def _resolve_nicknames(self, candidates: list, llm_nicknames: list | None) -> tuple[list, list]:
        if candidates:
            return candidates, []
        if llm_nicknames:
            return validate_nicknames_batch(self.db, llm_nicknames)
        return [], []

    def _handle_complex(self, question: str, nicknames: list, analysis: QuestionAnalysis, history: list[dict]):
        tables = SCHEMA_STORE.search(analysis.keywords)
        schema = SCHEMA_STORE.get_schema(tables)

        if analysis.category in CHARACTER_TYPES and analysis.response_format == "DISPLAY":
            required = UI_TABLE_MAP.get(analysis.category, [])
            extra = SCHEMA_STORE.get_schema([t for t in required if t not in schema])
            schema.update(extra)

        sql, ui_type, used = self.sql_generator.generate_validated(question, analysis, schema, nicknames)

        if ui_type != "TEXT" and ui_type in UI_TABLE_MAP:
            if not nicknames:
                result = self._execute_sql(sql, False, question, analysis, schema, nicknames)
                return self.answer_generator.answer(question, result or [], history)

            row = self._execute_sql(sql, True, question, analysis, schema, nicknames)
            data = dict(row) if row else {}

            # LLM이 잘못된 별칭을 쓸 시 보정
            unknown_keys = [k for k in data if k not in schema]
            unmatched_tables = [t for t in used if t not in data]
            if len(unknown_keys) == len(unmatched_tables) == 1:
                data[unmatched_tables[0]] = data.pop(unknown_keys[0])

            if data and all(isinstance(v, list) and len(v) == 0 for v in data.values()):
                return self.answer_generator.answer(question, [], history)

            missing = [t for t in UI_TABLE_MAP[ui_type] if t not in data]
            if missing:
                data.update(self.populator.fetch_missing_tables(nicknames[0], missing))

            data = self.populator.populate(ui_type, data)
            return {"ui_type": ui_type, "data": data}

        result = self._execute_sql(sql, False, question, analysis, schema, nicknames)
        if result is None:
            return ["질문을 좀 더 구체적으로 해주시면 더 잘 답변드릴 수 있어요."]
        return self.answer_generator.answer(question, result, history)

    def _execute_sql(self, sql: str, fetch_one: bool, question: str, analysis: QuestionAnalysis, schema, nicknames: list):
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
                continue
        return None
