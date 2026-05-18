import logging
from service.nickname_service import validate_nicknames_batch
from service.character_collector import collect_character
from service.populator import DataPopulator
from service.sql_pipeline import SQLPipeline
from constants import UI_TABLE_MAP, CHARACTER_TYPES, NICKNAME_BLACKLIST

logger = logging.getLogger(__name__)

_CHARACTER_DATA_TYPES = CHARACTER_TYPES - {"MARKET", "AUCTION"}
_GLOBALIZABLE = {"SKILL", "ENGRAVING", "ARK_PASSIVE", "ARK_GRID", "PROFILE"}


class LOSTARKService:

    def __init__(self, db, sql_generator, answer_generator):
        self.db = db
        self.answer_generator = answer_generator
        self.populator = DataPopulator(db)
        self.sql_pipeline = SQLPipeline(db, sql_generator, answer_generator, self.populator)

    def handle(self, question, analysis, history, candidates,
               filtered_entries, abbr_hints, remaining_words, all_triggers, **_):
        nicknames, unverified = self._resolve_nicknames(candidates, analysis.nicknames)
        yield "nicknames", nicknames

        if unverified and not nicknames:
            nickname = unverified[0]
            yield "status", f"'{nickname}' 캐릭터 데이터를 수집하는 중이에요..."
            success = collect_character(nickname, self.db)
            if not success:
                yield "result", [f"'{nickname}' 캐릭터 정보를 찾을 수 없어요."]
                return
            nicknames = [nickname]

        if not nicknames and analysis.category in _GLOBALIZABLE:
            analysis.category = "GLOBAL_" + analysis.category

        if analysis.category == "GENERAL":
            yield "status", "답변을 생성하는 중이에요..."
            yield "result", self.answer_generator.answer_general(question, history, game_type="LOSTARK")
            return

        requires_nickname = analysis.category in _CHARACTER_DATA_TYPES
        if requires_nickname and not nicknames:
            unknown_words = remaining_words - all_triggers
            inherited = self._last_nickname(history) if not unknown_words else []
            if inherited:
                nicknames = inherited
            else:
                yield "result", ["어떤 캐릭터에 대해 알고 싶으신가요? 닉네임을 알려주세요!"]
                return

        yield "status", "데이터를 조회하는 중이에요..."
        try:
            result, sql = self.sql_pipeline.run(
                question, nicknames, analysis, history,
                filtered_entries, abbr_hints, game_type="LOSTARK",
            )
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
            result["nicknames"] = analysis.nicknames
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

    def _resolve_nicknames(self, candidates, llm_nicknames):
        if not llm_nicknames:
            return [], []
        confirmed = [c for c in candidates if c in llm_nicknames]
        unvalidated = [
            n for n in llm_nicknames
            if n not in candidates and n not in NICKNAME_BLACKLIST and " " not in n
        ]
        if unvalidated:
            verified, unverified = validate_nicknames_batch(self.db, unvalidated)
            return confirmed + verified, unverified
        return confirmed, []

    def _last_nickname(self, history):
        if not history:
            return []
        for msg in reversed(history):
            nicks = msg.get("nicknames")
            if nicks:
                return [nicks[0]] if isinstance(nicks, list) else [nicks]
        return []
