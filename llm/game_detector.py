import re
import logging
from langchain_core.prompts import ChatPromptTemplate
from output_types import GameType

# 라이엇 계정 형식 "이름#태그" — TFT/LoL 전용 식별자
_RIOT_ID_RE = re.compile(r"[가-힣A-Za-z0-9][가-힣A-Za-z0-9 ]*#[A-Za-z0-9]+")

logger = logging.getLogger(__name__)

GAME_NAMES: dict[str, str] = {
    "LOSTARK": "로스트아크",
    "TFT": "롤토체스",
}

GAME_KEYWORDS: dict[str, list[str]] = {
    "LOSTARK": ["로스트아크", "로아", "어비스", "레이드", "각인", "아크패시브", "아크그리드", "보석", "원정대", "경매장", "거래소", "카드", "어빌리티스톤"],
    "TFT": ["롤토체스", "롤체", "tft", "증강체", "챔피언", "특성", "덱", "포지셔닝", "조합", "증강", "라운드", "시너지"],
}


def quick_detect(question: str) -> "GameType | None":
    """키워드 기반 빠른 감지. LLM 호출 없이 명확한 게임이 감지되면 반환, 불명확하면 None."""
    if _RIOT_ID_RE.search(question):
        return "TFT"
    q = question.lower()
    scores = {game: sum(kw in q for kw in keywords) for game, keywords in GAME_KEYWORDS.items()}
    best_game, best_score = max(scores.items(), key=lambda x: x[1])
    second_score = sorted(scores.values())[-2] if len(scores) > 1 else 0
    if best_score > 0 and best_score > second_score:
        return best_game
    return None


class GameDetector:

    def __init__(self, llm):
        self.llm = llm

    def detect(self, question: str) -> GameType:
        prompt = ChatPromptTemplate.from_template("""
        다음 질문이 어떤 게임에 관한 질문인지 판단해.

        - LOSTARK (로스트아크): 캐릭터, 장비, 스킬, 각인, 보석, 아크패시브, 아크그리드, 경매장, 거래소, 원정대 등
        - TFT (롤토체스): 증강체, 챔피언, 특성, 덱, 라운드, 골드, 포지셔닝, 조합 등
        - UNKNOWN: 어느 게임인지 판단 불가, 일반 대화, 인사

        반드시 LOSTARK / TFT / UNKNOWN 중 하나만 답해. 다른 말은 절대 하지 마.

        [질문]
        {question}
        """)
        try:
            result = (prompt | self.llm).invoke({"question": question})
            answer = result.content.strip().upper()
            if answer in ("LOSTARK", "TFT", "UNKNOWN"):
                return answer
            if "LOSTARK" in answer or "로스트아크" in answer:
                return "LOSTARK"
            if "TFT" in answer or "롤토체스" in answer:
                return "TFT"
            return "UNKNOWN"
        except Exception:
            logger.exception("게임 감지 실패, UNKNOWN 반환")
            return "UNKNOWN"


def is_game_switch_reask(history: list[dict]) -> bool:
    last_ai = _get_last_ai_message(history)
    if not last_ai:
        return False
    return "관련 질문인가요" in last_ai and any(name in last_ai for name in GAME_NAMES.values())


def extract_game_from_reask(history: list[dict]) -> GameType:
    last_ai = _get_last_ai_message(history) or ""
    for game_type, name in GAME_NAMES.items():
        if name in last_ai:
            return game_type
    return "UNKNOWN"


def is_affirmative(question: str) -> bool:
    q = question.strip()
    AFFIRMATIVES = {"응", "네", "맞아", "맞아요", "그래", "그렇습니다", "예", "ㅇ", "ㅇㅇ", "yes", "YES", "맞습니다", "맞음", "어"}
    if q in AFFIRMATIVES:
        return True
    if len(q) <= 5 and any(a in q for a in AFFIRMATIVES):
        return True
    return False


def _get_last_ai_message(history: list[dict]) -> str | None:
    for msg in reversed(history):
        if msg.get("role") in ("ai", "assistant"):
            return msg.get("content", "")
    return None
