import pytest
from utils.auction_option_resolver import resolve


class TestResolveNoMatch:
    def test_no_item_type_returns_none(self):
        assert resolve("딜러 상중 시세 알려줘") is None

    def test_no_grade_returns_none(self):
        assert resolve("딜러 귀걸이 시세") is None

    def test_empty_string_returns_none(self):
        assert resolve("") is None

    def test_bracelet_not_supported_returns_none(self):
        # 팔찌는 ITEM_KEYWORDS에 없음
        assert resolve("딜러 상중 팔찌") is None


class TestResolveSameGrade:
    def test_dealer_상상_earring(self):
        result = resolve("딜러 상상 귀걸이 최저가")
        assert result is not None
        assert "AND" in result
        assert "OR" not in result
        # 무기 공격력 % 상옵 기준 3.00, 공격력 % 상옵 기준 1.55
        assert "3.0" in result
        assert "1.55" in result

    def test_dealer_중중_ring(self):
        result = resolve("딜러 중중 반지 시세")
        assert result is not None
        assert "AND" in result
        # 치명타 적중률 중옵 0.95, 치명타 피해 중옵 2.40
        assert "0.95" in result
        assert "2.4" in result

    def test_support_중중_necklace(self):
        result = resolve("서폿 중중 목걸이")
        assert result is not None
        assert "AND" in result
        # 낙인력 중옵 4.80
        assert "4.8" in result


class TestResolveDifferentGrade:
    def test_dealer_상중_earring_returns_both_cases(self):
        result = resolve("딜러 상중 귀걸이")
        assert result is not None
        # 등급이 다르면 양방향 OR 반환
        assert "OR" in result

    def test_dealer_중하_ring(self):
        result = resolve("딜러 중하 반지")
        assert result is not None
        assert "OR" in result


class TestResolveSingleGrade:
    def test_dealer_상단일_earring(self):
        result = resolve("딜러 상단일 귀걸이 매물")
        assert result is not None
        # 단일 패턴은 opt1 OR opt2
        assert "OR" in result
        # 무기 공격력 % 상옵 3.00
        assert "3.0" in result

    def test_dealer_중단일_necklace(self):
        result = resolve("딜러 중단일 목걸이")
        assert result is not None
        assert "OR" in result
        # 추가 피해 % 중옵 1.60
        assert "1.6" in result


class TestResolveRoleDetection:
    def test_서포터_keyword_maps_to_서폿(self):
        result_서포터 = resolve("서포터 중중 목걸이")
        result_서폿 = resolve("서폿 중중 목걸이")
        assert result_서포터 == result_서폿

    def test_default_role_is_딜러(self):
        # 역할 키워드 없으면 딜러로 처리
        result_no_role = resolve("상중 귀걸이")
        result_dealer = resolve("딜러 상중 귀걸이")
        assert result_no_role == result_dealer
