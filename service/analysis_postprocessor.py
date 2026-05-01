from constants import DISPLAY_TRIGGERS, POSTPOSITIONS, DISPLAY_STRIP_WORDS
from llm.embedding_lookup_retriever import EMBEDDING_LOOKUP
from output_types import QuestionAnalysis

_CROSS_CATEGORY_TYPES = {"CLASS", "ARK_PASSIVE_CLASS"}

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


def post_process(
    question: str,
    analysis: QuestionAnalysis,
    lookup_entries: list[dict],
    excluded_nickname_terms: set,
) -> tuple[QuestionAnalysis, list[dict], str, set, set]:
    """분석 결과 후처리. (analysis, filtered_entries, abbr_hints, remaining_words, all_triggers) 반환"""

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
    remaining_words = set(q.split()) - DISPLAY_STRIP_WORDS - set(POSTPOSITIONS) - {""}
    all_triggers = {w for s in DISPLAY_TRIGGERS.values() for w in s}

    if analysis.response_format not in {"DISPLAY", "COMPARE"}:
        if remaining_words and remaining_words <= all_triggers and len(remaining_words) == 1:
            analysis.response_format = "DISPLAY"
            for cat, trigs in DISPLAY_TRIGGERS.items():
                if remaining_words & trigs:
                    analysis.category = cat
                    break

    if analysis.response_format == "DISPLAY":
        if remaining_words == {"정보"} and analysis.category != "TOTAL_INFO":
            analysis.category = "TOTAL_INFO"
        if "정보" in remaining_words and (remaining_words - {"정보"}) & all_triggers and analysis.category == "TOTAL_INFO":
            for cat, trigs in DISPLAY_TRIGGERS.items():
                if cat != "TOTAL_INFO" and (remaining_words - {"정보"}) & trigs:
                    analysis.category = cat
                    break

    return analysis, filtered_entries, abbr_hints, remaining_words, all_triggers
