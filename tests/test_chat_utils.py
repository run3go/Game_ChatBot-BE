import pytest
from utils.chat_utils import clean_word, format_history


class TestCleanWord:
    def test_removes_postposition(self):
        assert clean_word("황로드유의") == "황로드유"

    def test_removes_을(self):
        assert clean_word("황로드유를") == "황로드유"

    def test_removes_은(self):
        assert clean_word("펜토르는") == "펜토르"

    def test_removes_이(self):
        assert clean_word("첫번째도구가") == "첫번째도구"

    def test_no_postposition_unchanged(self):
        assert clean_word("황로드유") == "황로드유"

    def test_too_short_after_removal_unchanged(self):
        # 조사 제거 후 1글자면 원래 단어 유지
        assert clean_word("가을") == "가을"  # "가을" → 제거 후 "가"(1글자) → 유지

    def test_longer_postposition_takes_priority(self):
        # 조사는 긴 것부터 매칭 ("이랑" > "이")
        assert clean_word("황로드유이랑") == "황로드유"


class TestFormatHistory:
    def test_empty_history_returns_empty(self):
        assert format_history([]) == ""

    def test_none_history_returns_empty(self):
        assert format_history(None) == ""

    def test_basic_user_message(self):
        history = [{"role": "user", "content": "스킬 보여줘"}]
        result = format_history(history)
        assert "사용자: 스킬 보여줘" in result

    def test_basic_ai_message(self):
        history = [{"role": "ai", "content": "스킬 목록입니다."}]
        result = format_history(history)
        assert "AI: 스킬 목록입니다." in result

    def test_user_message_with_nicknames(self):
        history = [{"role": "user", "content": "스킬 보여줘", "nicknames": ["황로드유"]}]
        result = format_history(history)
        assert "[닉네임: 황로드유]" in result

    def test_summary_message(self):
        history = [{"role": "summary", "content": "이전 대화 요약 내용"}]
        result = format_history(history)
        assert "[이전 대화 요약]" in result
        assert "이전 대화 요약 내용" in result

    def test_max_ai_length_truncates(self):
        long_ai = "A" * 300
        history = [{"role": "ai", "content": long_ai}]
        result = format_history(history, max_ai_length=100)
        assert "..." in result
        assert len(result) < 300

    def test_max_ai_length_no_truncate_when_short(self):
        short_ai = "짧은 답변"
        history = [{"role": "ai", "content": short_ai}]
        result = format_history(history, max_ai_length=100)
        assert "..." not in result
        assert short_ai in result

    def test_limit_returns_recent_messages_only(self):
        history = [
            {"role": "user", "content": f"질문{i}"}
            for i in range(10)
        ]
        result = format_history(history, limit=3)
        assert "질문9" in result
        assert "질문8" in result
        assert "질문7" in result
        assert "질문6" not in result

    def test_summary_always_included_regardless_of_limit(self):
        history = [
            {"role": "summary", "content": "요약"},
            *[{"role": "user", "content": f"질문{i}"} for i in range(10)],
        ]
        result = format_history(history, limit=3)
        assert "[이전 대화 요약]" in result
        assert "요약" in result
