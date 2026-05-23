import logging
from sqlalchemy.exc import ProgrammingError
from sqlalchemy import text
from utils.db_schema_store import DB_SCHEMA_STORE
from llm.sql_generator import SQLGenerator
from llm.answer_generator import AnswerGenerator
from llm.few_shot_retriever import FEW_SHOT_STORE
from service.populator import DataPopulator
from utils.auction_option_resolver import resolve as resolve_auction_options
from constants import UI_TABLE_MAP, CHARACTER_TYPES
from output_types import QuestionAnalysis

logger = logging.getLogger(__name__)


class SQLPipeline:

    def __init__(self, db, sql_generator: SQLGenerator, answer_generator: AnswerGenerator, populator: DataPopulator | None = None):
        self.db = db
        self.sql_generator = sql_generator
        self.answer_generator = answer_generator
        self.populator = populator

    def run(
        self,
        question: str,
        nicknames: list,
        analysis: QuestionAnalysis,
        history: list[dict],
        lookup_entries: list[dict] | None = None,
        abbr_hints: str = "",
        game_type: str = "LOSTARK",
    ) -> tuple:
        """SQL 파이프라인 실행. (result, sql) 반환"""

        if analysis.category == "TOTAL_INFO" and nicknames:
            data = self.populator.fetch_missing_tables(nicknames[0], UI_TABLE_MAP["TOTAL_INFO"])
            data = self.populator.populate("TOTAL_INFO", data)
            return {"ui_type": "TOTAL_INFO", "data": data}, None

        if analysis.category in CHARACTER_TYPES and analysis.response_format == "DISPLAY" and nicknames:
            tables = UI_TABLE_MAP.get(analysis.category, [])
            data = self.populator.fetch_missing_tables(nicknames[0], tables)
            data = self.populator.populate(analysis.category, data)
            return {"ui_type": analysis.category, "data": data}, None

        priority_tables = self._build_priority_tables(analysis, lookup_entries, game_type)
        schema = DB_SCHEMA_STORE.get_schema(self.db, priority_tables, game_type=game_type)

        retrieval_query = self._normalize_for_retrieval(question, nicknames)
        if history:
            last_user = next((m["content"] for m in reversed(history) if m.get("role") == "user"), None)
            if last_user:
                retrieval_query = last_user + " " + retrieval_query
        retrieval_query += f" {analysis.category} {analysis.response_format}"
        few_shots = FEW_SHOT_STORE.retrieve(self.db, retrieval_query, category=analysis.category, game_type=game_type)

        all_tables = DB_SCHEMA_STORE.get_all_tables(self.db, game_type=game_type)
        auction_conditions = resolve_auction_options(question) if analysis.category == "AUCTION" else ""
        logger.info("[auction_conditions] category=%s resolved=%r", analysis.category, auction_conditions)

        sql = self.sql_generator.generate_validated(
            question, analysis, schema, nicknames,
            few_shots=few_shots, all_tables=all_tables,
            abbr_hints=abbr_hints, auction_conditions=auction_conditions,
            history=history, game_type=game_type,
        )

        result = self._execute_sql(sql, question, analysis, schema, nicknames, few_shots=few_shots, auction_conditions=auction_conditions, game_type=game_type)

        if result is None:
            return ["해당 정보를 찾지 못했어요. 질문을 좀 더 구체적으로 해주시면 더 잘 답변드릴 수 있어요."], sql
        if result == []:
            if analysis.response_format == "COMPARE":
                return ["변경된 기록이 없습니다."], sql
            if analysis.category in {"MARKET", "AUCTION"}:
                return ["해당 아이템을 찾을 수 없어요. 아이템명을 정확히 입력해주세요."], sql
            if analysis.category.startswith("GLOBAL_"):
                return ["해당 정보가 데이터베이스에 없어요."], sql
            return ["조건에 맞는 데이터가 없어요."], sql

        if analysis.category == "META_COMPS" and game_type == "TFT":
            required = {"tier", "comp_name", "avg_place", "pick_rate", "win_rate", "top4_rate", "traits", "champs_items", "tags"}
            data = [{**{k: None for k in required}, **dict(r)} for r in result]
            return {"ui_type": "TFT_META_COMP", "data": data}, sql

        if analysis.category in {"MARKET", "AUCTION"} and analysis.response_format == "LIST":
            return {"ui_type": analysis.category, "data": [dict(r) for r in result]}, sql

        if game_type == "TFT":
            return self.answer_generator.answer_tft(question, result, history), sql
        return self.answer_generator.answer_lostark(question, result, history, category=analysis.category), sql

    def _build_priority_tables(self, analysis: QuestionAnalysis, lookup_entries: list[dict] | None, game_type: str = "LOSTARK") -> list:
        seen: set = set()
        tables: list = []

        def _add(t_list):
            for t in t_list:
                if t not in seen:
                    seen.add(t)
                    tables.append(t)

        if analysis.category in {"MARKET", "AUCTION"}:
            _add(UI_TABLE_MAP.get(analysis.category, []))
        else:
            _add(DB_SCHEMA_STORE.search(self.db, [analysis.category], game_type=game_type))

        if lookup_entries:
            for entry in lookup_entries:
                _add(entry.get("related_tables", []))

        return tables

    def _normalize_for_retrieval(self, question: str, nicknames: list[str]) -> str:
        normalized = question
        for i, name in enumerate(nicknames, 1):
            placeholder = "CHARACTER_NAME" if len(nicknames) == 1 else f"CHARACTER_NAME{i}"
            normalized = normalized.replace(name, placeholder)
        return normalized

    def _execute_sql(self, sql: str, question: str, analysis: QuestionAnalysis, schema, nicknames: list, few_shots: str = "", auction_conditions: str = "", game_type: str = "LOSTARK"):
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
                    auction_conditions=auction_conditions,
                    game_type=game_type,
                )
