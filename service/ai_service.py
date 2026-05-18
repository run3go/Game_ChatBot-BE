import logging
from llm.sql_generator import SQLGenerator
from llm.analysis_generator import AnalysisGenerator
from llm.answer_generator import AnswerGenerator
from llm.embedding_lookup_retriever import EMBEDDING_LOOKUP
from utils.chat_utils import extract_nicknames
from service.analysis_postprocessor import post_process
from service.lostark_service import LOSTARKService
from service.tft_service import TFTService

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
        self.handlers = {
            "LOSTARK": LOSTARKService(db, sql_generator, answer_generator),
            "TFT": TFTService(db, sql_generator, answer_generator),
        }

    def ask(self, question: str, history: list[dict] | None = None, game_type: str = "LOSTARK"):
        # LOSTARK만 DB 후보 검색 — TFT 소환사명은 DB에 없음
        candidates = extract_nicknames(self.db, question) if game_type == "LOSTARK" else []

        yield "status", "질문을 분석하는 중이에요..."
        try:
            lookup = EMBEDDING_LOOKUP.get(game_type, EMBEDDING_LOOKUP["LOSTARK"])
            lookup_entries = lookup.retrieve(self.db, question)
            excluded_nickname_terms = lookup.get_excluded_nickname_terms(lookup_entries)
            analysis = self.analysis_generator.analyze(
                question, history, candidates,
                lookup.format_context(lookup_entries), game_type=game_type,
            )
        except Exception:
            logger.exception("분석 실패")
            yield "result", ["잠시 후 다시 시도해 주세요."]
            return

        if analysis.reask_message:
            yield "result", [analysis.reask_message]
            return

        analysis, filtered_entries, abbr_hints, remaining_words, all_triggers = post_process(
            question, analysis, lookup_entries, excluded_nickname_terms, lookup=lookup
        )

        handler = self.handlers.get(game_type, self.handlers["LOSTARK"])
        yield from handler.handle(
            question, analysis, history,
            candidates=candidates,
            filtered_entries=filtered_entries,
            abbr_hints=abbr_hints,
            remaining_words=remaining_words,
            all_triggers=all_triggers,
        )
