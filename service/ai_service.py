import logging
from sqlalchemy.exc import ProgrammingError
from sqlalchemy import text
from sql.db_schema_store import DB_SCHEMA_STORE
from llm.sql_generator import SQLGenerator
from llm.analysis_generator import AnalysisGenerator
from llm.answer_generator import AnswerGenerator
from llm.few_shot_retriever import FEW_SHOT_STORE
from llm.embedding_lookup_retriever import EMBEDDING_LOOKUP
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
            lookup_entries = EMBEDDING_LOOKUP.retrieve(self.db, question)
            abbr_hints = EMBEDDING_LOOKUP.format_abbr_hints(question, lookup_entries)
            embedding_context = EMBEDDING_LOOKUP.format_context(lookup_entries)
            excluded_nickname_terms = EMBEDDING_LOOKUP.get_excluded_nickname_terms(lookup_entries)
            analysis = self.analysis_generator.analyze(question, history, candidates, embedding_context, excluded_nickname_terms)
        except Exception:
            logger.exception("분석 실패")
            yield "result", ["잠시 후 다시 시도해 주세요."]
            return

        nicknames, unverified = self._resolve_nicknames(candidates, analysis.nicknames)
        yield "nicknames", nicknames

        if analysis.category == "GENERAL":
            yield "status", "답변을 생성하는 중이에요..."
            yield "result", self.answer_generator.answer_general(question, history)
            return

        requires_nickname = analysis.category in CHARACTER_TYPES

        if requires_nickname and not nicknames:
            # LLM이 닉네임을 못 찾았을 때 히스토리에서 명시적으로 상속
            if not unverified:
                inherited = self._get_last_nickname_from_history(history)
                if inherited:
                    nicknames = inherited
            # 상속 후에도 없으면 사용자에게 요청
            if not nicknames:
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
            result, sql = self._handle_complex(question, nicknames, analysis, history, lookup_entries, abbr_hints)
        except ValueError as e:
            logger.warning("질문 처리 실패 (ValueError): %s", e)
            yield "result", ["질문을 좀 더 구체적으로 해주시면 더 잘 답변드릴 수 있어요."]
            return
        except Exception:
            logger.exception("데이터 조회 실패")
            yield "result", ["잠시 후 다시 시도해 주세요."]
            return

        if sql:
            yield "sql", sql

        if isinstance(result, dict):
            result['nicknames'] = analysis.nicknames
            yield "result", result
            if result.get("ui_type") != "TOTAL_INFO":
                yield "status", "답변을 생성하는 중이에요..."
                yield "result_text", self.answer_generator.answer_display(
                    question,
                    result.get("ui_type", ""),
                    result.get("data", {}),
                    history,
                )
        else:
            yield "result", result

    def _get_last_nickname_from_history(self, history: list[dict] | None) -> list[str]:
        """히스토리 메시지의 nicknames 컬럼에서 가장 최근 닉네임을 반환"""
        if not history:
            return []
        for msg in reversed(history):
            nicks = msg.get("nicknames")
            if nicks:
                return [nicks[0]] if isinstance(nicks, list) else [nicks]
        return []

    def _resolve_nicknames(self, candidates: list, llm_nicknames: list | None) -> tuple[list, list]:
        if not llm_nicknames:
            return [], []
        confirmed = [c for c in candidates if c in llm_nicknames]
        unvalidated = [n for n in llm_nicknames if n not in candidates]
        if unvalidated:
            verified, unverified = validate_nicknames_batch(self.db, unvalidated)
            return confirmed + verified, unverified
        return confirmed, []

    def _handle_complex(self, question: str, nicknames: list, analysis: QuestionAnalysis, history: list[dict], lookup_entries: list[dict] | None = None, abbr_hints: str = ""):
        if analysis.category == "TOTAL_INFO" and nicknames:
            data = self.populator.fetch_missing_tables(nicknames[0], UI_TABLE_MAP["TOTAL_INFO"])
            data = self.populator.populate("TOTAL_INFO", data)
            return {"ui_type": "TOTAL_INFO", "data": data}, None

        if analysis.category in CHARACTER_TYPES and analysis.response_format == "DISPLAY":
            tables = UI_TABLE_MAP.get(analysis.category, [])
            data = self.populator.fetch_missing_tables(nicknames[0], tables)
            data = self.populator.populate(analysis.category, data)
            return {"ui_type": analysis.category, "data": data}, None

        # analysis.category 기반 base_tables + embedding related_tables 합산
        seen_tables: set = set()
        priority_tables: list = []

        def _add_tables(tables):
            for t in tables:
                if t not in seen_tables:
                    seen_tables.add(t)
                    priority_tables.append(t)

        _add_tables(DB_SCHEMA_STORE.search(self.db, [analysis.category]))
        if lookup_entries:
            for entry in lookup_entries:
                _add_tables(entry.get("related_tables", []))

        schema = DB_SCHEMA_STORE.get_schema(self.db, priority_tables)
        few_shots = FEW_SHOT_STORE.retrieve(self.db, question, category=analysis.category)
        all_tables = DB_SCHEMA_STORE.get_all_tables(self.db)
        sql = self.sql_generator.generate_validated(question, analysis, schema, nicknames, few_shots=few_shots, all_tables=all_tables, abbr_hints=abbr_hints)

        result = self._execute_sql(sql, question, analysis, schema, nicknames, few_shots=few_shots)
        if result is None:
            return ["해당 정보를 찾지 못했어요. 질문을 좀 더 구체적으로 해주시면 더 잘 답변드릴 수 있어요."], sql
        if result == []:
            return ["조건에 맞는 데이터가 없어요."], sql
        return self.answer_generator.answer(question, result, history), sql

    def _execute_sql(self, sql: str, question: str, analysis: QuestionAnalysis, schema, nicknames: list, few_shots: str = ""):
        for attempt in range(2):
            try:
                return self.db.execute(text(sql)).mappings().all()
            except ProgrammingError as e:
                self.db.rollback()
                if attempt == 1:
                    return None
                sql, _ = self.sql_generator.generate(
                    question, analysis, schema, nicknames,
                    error=f"SQL 실행 오류: {str(e.orig)}",
                    few_shots=few_shots,
                )
