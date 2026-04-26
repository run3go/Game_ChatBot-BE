import re

# option JSONB key → (하_min, 중_min, 상_min)
OPTION_THRESHOLDS: dict[str, tuple] = {
    "공격력  %":                               (0.40,  0.95,   1.55),
    "공격력  +":                               (80,    195,    390),
    "무기 공격력  %":                          (0.80,  1.80,   3.00),
    "무기 공격력  +":                          (195,   480,    960),
    "추가 피해 %":                             (0.70,  1.60,   2.60),
    "적에게 주는 피해 증가 %":                  (0.55,  1.20,   2.00),
    "낙인력 %":                                (2.15,  4.80,   8.00),
    "세레나데, 신앙, 조화 게이지 획득량 증가 %": (1.60,  3.60,   6.00),
    "치명타 적중률 %":                         (0.40,  0.95,   1.55),
    "치명타 피해 %":                           (1.10,  2.40,   4.00),
    "최대 생명력 +":                           (1300,  3250,   6500),
    "아군 공격력 강화 효과 %":                 (1.35,  3.00,   5.00),
    "아군 피해량 강화 효과 %":                 (2.00,  4.50,   7.50),
}

# % 키 → + 키: _cond에서 두 조건을 AND로 함께 생성
PAIRED_OPTIONS: dict[str, str] = {
    "공격력  %":      "공격력  +",
    "무기 공격력  %": "무기 공격력  +",
}

# 역할 × 장신구 종류 → [기본옵션1 key, 기본옵션2 key]
ITEM_OPTIONS: dict[str, dict[str, list[str]]] = {
    "딜러": {
        "목걸이": ["추가 피해 %",              "적에게 주는 피해 증가 %"],
        "귀걸이": ["무기 공격력  %",           "공격력  %"],
        "반지":   ["치명타 적중률 %",          "치명타 피해 %"],
    },
    "서폿": {
        "목걸이": ["낙인력 %",                 "세레나데, 신앙, 조화 게이지 획득량 증가 %"],
        "귀걸이": ["무기 공격력  %",           "무기 공격력  %"],
        "반지":   ["아군 공격력 강화 효과 %",  "아군 피해량 강화 효과 %"],
    },
}

_GRADE_INDEX = {"하": 0, "중": 1, "상": 2}

_ROLE_KEYWORDS = [
    ("서포터", "서폿"), ("서폿", "서폿"),
    ("딜러", "딜러")
]
_ITEM_KEYWORDS = [
    ("귀걸이", "귀걸이"), ("귀걸", "귀걸이"),
    ("목걸이", "목걸이"), ("목걸", "목걸이"),
    ("반지", "반지"),
]


def resolve(question: str) -> str | None:
    """
    질문에서 장신구 옵션 등급 표현(예: '딜러 상중 귀걸이', '딜러 상단일 귀걸이')을 파싱해
    SQL WHERE 조건 문자열을 반환. 파싱 불가 시 None.
    """
    item_type = next((c for kw, c in _ITEM_KEYWORDS if kw in question), None)
    if not item_type:
        return None

    role = next((c for kw, c in _ROLE_KEYWORDS if kw in question), "딜러")

    options = ITEM_OPTIONS.get(role, {}).get(item_type)
    if not options:
        return None

    opt1, opt2 = options

    def _cond(key: str, grade: str) -> str:
        val = OPTION_THRESHOLDS[key][_GRADE_INDEX[grade]]
        cond = f"(options->>'{key}')::numeric >= {val}"
        if key in PAIRED_OPTIONS:
            paired_key = PAIRED_OPTIONS[key]
            paired_val = OPTION_THRESHOLDS[paired_key][_GRADE_INDEX[grade]]
            cond += f" AND (options->>'{paired_key}')::numeric >= {paired_val}"
        return cond

    # 단일 패턴: 상단일 / 중단일 
    # 두 옵션 중 하나만 해당 등급 이상이면 됨
    단일_match = re.search(r'([상중])단일', question)
    if 단일_match:
        grade = 단일_match.group(1)
        return f"({_cond(opt1, grade)} OR {_cond(opt2, grade)})"

    # 일반 2등급 패턴: 상중 / 중중 / 상상 등
    grade_match = re.search(r'[상중하]{2}', question)
    if not grade_match:
        return None

    g1, g2 = list(grade_match.group())

    if g1 == g2:
        return f"{_cond(opt1, g1)} AND {_cond(opt2, g2)}"

    # 다른 등급: 어느 옵션이 어느 등급인지 특정할 수 없으므로 양방향 OR
    high, low = sorted([g1, g2], key=lambda g: _GRADE_INDEX[g], reverse=True)
    case_a = f"{_cond(opt1, high)} AND {_cond(opt2, low)}"
    case_b = f"{_cond(opt1, low)} AND {_cond(opt2, high)}"
    return f"(({case_a})\n    OR ({case_b}))"
