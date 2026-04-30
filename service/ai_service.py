import logging
import re
from sqlalchemy.exc import ProgrammingError
from sqlalchemy import text
from utils.db_schema_store import DB_SCHEMA_STORE
from llm.sql_generator import SQLGenerator
from llm.analysis_generator import AnalysisGenerator
from llm.answer_generator import AnswerGenerator
from llm.few_shot_retriever import FEW_SHOT_STORE
from llm.embedding_lookup_retriever import EMBEDDING_LOOKUP
from utils.chat_utils import extract_nicknames
from service.nickname_service import validate_nicknames_batch
from service.populator import DataPopulator
from utils.auction_option_resolver import resolve as resolve_auction_options
from constants import UI_TABLE_MAP, CHARACTER_TYPES, DISPLAY_TRIGGERS, POSTPOSITIONS, NICKNAME_BLACKLIST, DISPLAY_STRIP_WORDS

_CHARACTER_DATA_TYPES = CHARACTER_TYPES - {"MARKET", "AUCTION"}
from output_types import QuestionAnalysis

logger = logging.getLogger(__name__)



_GLOBALIZABLE = {"SKILL", "ENGRAVING", "ARK_PASSIVE", "ARK_GRID", "PROFILE"}

# 카테고리 무관하게 항상 스키마에 포함 (JOIN 조건 제공용)
_CROSS_CATEGORY_TYPES = {"CLASS", "ARK_PASSIVE_CLASS"}

# 카테고리 일치 시에만 스키마에 포함 (질문의 주제 타입)
_CATEGORY_SUBJECT_TYPES: dict[str, set[str]] = {
    "SKILL":              {"SKILL", "RUNE", "GEM"},
    "GLOBAL_SKILL":       {"SKILL", "RUNE", "GEM"},
    "ENGRAVING":          {"ENGRAVING"},
    "GLOBAL_ENGRAVING":   {"ENGRAVING"},
    "ARK_PASSIVE":        {"ARK_PASSIVE_EFFECT", "ARK_PASSIVE_CLASS"},
    "GLOBAL_ARK_PASSIVE": {"ARK_PASSIVE_EFFECT", "ARK_PASSIVE_CLASS"},
    "ARK_GRID":           {"ARK_GRID"},
    "GLOBAL_ARK_GRID":    {"ARK_GRID"},
    "PROFILE":            {"PROFILE", "CARD"},
    "GLOBAL_PROFILE":     {"PROFILE", "CARD"},
    "COLLECTIBLE":        {"COLLECTIBLE"},
    "MARKET":             {"ENGRAVING"},
}

class AIService:

    def __init__(self, llm, db, llm_sql=None, llm_answer=None):
        self.db = db
        self.sql_generator = SQLGenerator(llm_sql or llm)
        self.analysis_generator = AnalysisGenerator(llm)
        self.answer_generator = AnswerGenerator(llm_answer or llm)
        self.populator = DataPopulator(db)

    def ask(self, question: str, history: list[dict] | None = None):
        candidates = extract_nicknames(self.db, question)

        yield "status", "질문을 분석하는 중이에요..."
        try:
            lookup_entries = EMBEDDING_LOOKUP.retrieve(self.db, question)
            abbr_hints = EMBEDDING_LOOKUP.format_term_hints(question, lookup_entries)
            embedding_context = EMBEDDING_LOOKUP.format_context(lookup_entries)
            excluded_nickname_terms = EMBEDDING_LOOKUP.get_excluded_nickname_terms(lookup_entries)
            analysis = self.analysis_generator.analyze(question, history, candidates, embedding_context)
        except Exception:
            logger.exception("분석 실패")
            yield "result", ["잠시 후 다시 시도해 주세요."]
            return

        if analysis.reask_message:
            yield "result", [analysis.reask_message]
            return

        if analysis.nicknames and excluded_nickname_terms:
            analysis.nicknames = [n for n in analysis.nicknames if n not in excluded_nickname_terms]

        if analysis.nicknames and analysis.category.startswith("GLOBAL_"):
            analysis.category = analysis.category[len("GLOBAL_"):]

        allowed_types = _CROSS_CATEGORY_TYPES | _CATEGORY_SUBJECT_TYPES.get(analysis.category, set())
        filtered_entries = [e for e in lookup_entries if e.get("type") in allowed_types]
        filtered_entries = EMBEDDING_LOOKUP.filter_subsumed(question, filtered_entries)
        abbr_hints = EMBEDDING_LOOKUP.format_term_hints(question, filtered_entries)

        q = question
        for nick in (analysis.nicknames or []):
            q = q.replace(nick, "")
        words = set(q.split()) - DISPLAY_STRIP_WORDS - set(POSTPOSITIONS) - {""}
        all_triggers = {w for s in DISPLAY_TRIGGERS.values() for w in s}

        if analysis.response_format not in {"DISPLAY", "COMPARE"}:
            if words and words <= all_triggers and len(words) == 1:
                analysis.response_format = "DISPLAY"
                for cat, trigs in DISPLAY_TRIGGERS.items():
                    if words & trigs:
                        analysis.category = cat
                        break

        if analysis.response_format == "DISPLAY":
            # "정보"만 남은 경우 → LLM이 PROFILE 등으로 잘못 분류했을 때 TOTAL_INFO로 보정
            if words == {"정보"} and analysis.category != "TOTAL_INFO":
                analysis.category = "TOTAL_INFO"

            # "정보" + 다른 트리거 조합 → "정보"는 요청어 취급, LLM이 TOTAL_INFO로 잘못 분류했으면 보정
            if "정보" in words and (words - {"정보"}) & all_triggers and analysis.category == "TOTAL_INFO":
                for cat, trigs in DISPLAY_TRIGGERS.items():
                    if cat != "TOTAL_INFO" and (words - {"정보"}) & trigs:
                        analysis.category = cat
                        break

        nicknames, unverified = self._resolve_nicknames(candidates, analysis.nicknames)
        yield "nicknames", nicknames

        if unverified and not nicknames:
            nickname = unverified[0]
            yield "result", {
                "ui_type": "CONFIRM_COLLECT",
                "nickname": nickname,
                "message": f"'{nickname}' 캐릭터 정보가 존재하지 않습니다. 데이터를 수집할까요? (예/아니오)",
            }
            return

        if not nicknames and analysis.category in _GLOBALIZABLE:
            analysis.category = "GLOBAL_" + analysis.category

        if analysis.category == "GENERAL":
            yield "status", "답변을 생성하는 중이에요..."
            yield "result", self.answer_generator.answer_general(question, history)
            return

        requires_nickname = analysis.category in (CHARACTER_TYPES - {"MARKET", "AUCTION"})

        if requires_nickname and not nicknames:
            # 순수 후속 질문(트리거·조사·요청어만 남는 짧은 질문)일 때만 히스토리 닉네임 상속.
            # 트리거 외 미인식 단어가 있으면 엉뚱한 질문으로 판단해 상속 금지.
            unknown_words = words - all_triggers
            inherited = self._get_last_nickname_from_history(history) if not unknown_words else []
            if inherited:
                nicknames = inherited
            else:
                yield "result", ["어떤 캐릭터에 대해 알고 싶으신가요? 닉네임을 알려주세요!"]
                return

        yield "status", "데이터를 조회하는 중이에요..."
        try:
            result, sql = self._handle_complex(question, nicknames, analysis, history, filtered_entries, abbr_hints)
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
        else:
            yield "result", result

        if nicknames and analysis.category in _CHARACTER_DATA_TYPES:
            tables = UI_TABLE_MAP.get(analysis.category, [])
            collected_at = self.populator.get_max_collected_at(nicknames[0], tables)
            if collected_at:
                yield "data_updated_at", collected_at
        elif analysis.category in {"MARKET", "AUCTION"}:
            tables = UI_TABLE_MAP.get(analysis.category, [])
            collected_at = self.populator.get_max_collected_at_global(tables)
            if collected_at:
                yield "data_updated_at", collected_at

    def _normalize_for_retrieval(self, question: str, nicknames: list[str]) -> str:
        normalized = question
        for i, name in enumerate(nicknames, 1):
            placeholder = "CHARACTER_NAME" if len(nicknames) == 1 else f"CHARACTER_NAME{i}"
            normalized = normalized.replace(name, placeholder)
        return normalized

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
        unvalidated = [n for n in llm_nicknames if n not in candidates and n not in NICKNAME_BLACKLIST and ' ' not in n]
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

        if analysis.category in {"MARKET", "AUCTION"}:
            _add_tables(UI_TABLE_MAP.get(analysis.category, []))
        else:
            _add_tables(DB_SCHEMA_STORE.search(self.db, [analysis.category]))
        if lookup_entries:
            for entry in lookup_entries:
                _add_tables(entry.get("related_tables", []))

        schema = DB_SCHEMA_STORE.get_schema(self.db, priority_tables)
        retrieval_query = self._normalize_for_retrieval(question, nicknames)
        retrieval_query += f" {analysis.category} {analysis.response_format}"
        few_shots = FEW_SHOT_STORE.retrieve(self.db, retrieval_query, category=analysis.category)
        all_tables = DB_SCHEMA_STORE.get_all_tables(self.db)
        auction_conditions = resolve_auction_options(question) if analysis.category == "AUCTION" else ""
        logger.info("[auction_conditions] category=%s resolved=%r", analysis.category, auction_conditions)
        sql = self.sql_generator.generate_validated(question, analysis, schema, nicknames, few_shots=few_shots, all_tables=all_tables, abbr_hints=abbr_hints, auction_conditions=auction_conditions, history=history)

        result = self._execute_sql(sql, question, analysis, schema, nicknames, few_shots=few_shots, auction_conditions=auction_conditions)
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
        if analysis.category in {"MARKET", "AUCTION"} and analysis.response_format == "LIST":
            return {"ui_type": analysis.category, "data": [dict(r) for r in result]}, sql
        return self.answer_generator.answer(question, result, history, category=analysis.category), sql

    def _execute_sql(self, sql: str, question: str, analysis: QuestionAnalysis, schema, nicknames: list, few_shots: str = "", auction_conditions: str = ""):
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
                )
