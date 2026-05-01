import logging
from llm.sql_generator import SQLGenerator
from llm.analysis_generator import AnalysisGenerator
from llm.answer_generator import AnswerGenerator
from llm.embedding_lookup_retriever import EMBEDDING_LOOKUP
from utils.chat_utils import extract_nicknames
from service.nickname_service import validate_nicknames_batch
from service.populator import DataPopulator
from service.analysis_postprocessor import post_process
from service.sql_pipeline import SQLPipeline
from constants import UI_TABLE_MAP, CHARACTER_TYPES, NICKNAME_BLACKLIST

_CHARACTER_DATA_TYPES = CHARACTER_TYPES - {"MARKET", "AUCTION"}
_GLOBALIZABLE = {"SKILL", "ENGRAVING", "ARK_PASSIVE", "ARK_GRID", "PROFILE"}

logger = logging.getLogger(__name__)


class AIService:

    def __init__(
        self,
        db,
        sql_generator: SQLGenerator,
        analysis_generator: AnalysisGenerator,
        answer_generator: AnswerGenerator,
    ):
        self.db = db
        self.analysis_generator = analysis_generator
        self.answer_generator = answer_generator
        self.populator = DataPopulator(db)
        self.sql_pipeline = SQLPipeline(db, sql_generator, answer_generator, self.populator)

    def ask(self, question: str, history: list[dict] | None = None):
        candidates = extract_nicknames(self.db, question)

        yield "status", "질문을 분석하는 중이에요..."
        try:
            lookup_entries = EMBEDDING_LOOKUP.retrieve(self.db, question)
            excluded_nickname_terms = EMBEDDING_LOOKUP.get_excluded_nickname_terms(lookup_entries)
            analysis = self.analysis_generator.analyze(question, history, candidates, EMBEDDING_LOOKUP.format_context(lookup_entries))
        except Exception:
            logger.exception("분석 실패")
            yield "result", ["잠시 후 다시 시도해 주세요."]
            return

        if analysis.reask_message:
            yield "result", [analysis.reask_message]
            return

        analysis, filtered_entries, abbr_hints, remaining_words, all_triggers = post_process(
            question, analysis, lookup_entries, excluded_nickname_terms
        )

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

        requires_nickname = analysis.category in _CHARACTER_DATA_TYPES
        if requires_nickname and not nicknames:
            unknown_words = remaining_words - all_triggers
            inherited = self._get_last_nickname_from_history(history) if not unknown_words else []
            if inherited:
                nicknames = inherited
            else:
                yield "result", ["어떤 캐릭터에 대해 알고 싶으신가요? 닉네임을 알려주세요!"]
                return

        yield "status", "데이터를 조회하는 중이에요..."
        try:
            result, sql = self.sql_pipeline.run(question, nicknames, analysis, history, filtered_entries, abbr_hints)
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

        tables = UI_TABLE_MAP.get(analysis.category, [])
        if nicknames and analysis.category in _CHARACTER_DATA_TYPES:
            collected_at = self.populator.get_max_collected_at(nicknames[0], tables)
        elif analysis.category in {"MARKET", "AUCTION"}:
            collected_at = self.populator.get_max_collected_at_global(tables)
        else:
            collected_at = None

        if collected_at:
            yield "data_updated_at", collected_at

    def _resolve_nicknames(self, candidates: list, llm_nicknames: list | None) -> tuple[list, list]:
        if not llm_nicknames:
            return [], []
        confirmed = [c for c in candidates if c in llm_nicknames]
        unvalidated = [n for n in llm_nicknames if n not in candidates and n not in NICKNAME_BLACKLIST and ' ' not in n]
        if unvalidated:
            verified, unverified = validate_nicknames_batch(self.db, unvalidated)
            return confirmed + verified, unverified
        return confirmed, []

    def _get_last_nickname_from_history(self, history: list[dict] | None) -> list[str]:
        if not history:
            return []
        for msg in reversed(history):
            nicks = msg.get("nicknames")
            if nicks:
                return [nicks[0]] if isinstance(nicks, list) else [nicks]
        return []
