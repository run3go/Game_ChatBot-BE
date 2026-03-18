import re
from service.nickname_service import validate_nickname

POSTPOSITIONS = ["은", "는", "이", "가", "을", "를", "의", "와", "과", "랑", "이랑"]
STOPWORDS = ["스킬", "보석", "각인", "아바타", "장비", "내실", "능력치", "아크패시브", "아크그리드"]

def clean_word(word: str) -> str:
    for p in POSTPOSITIONS:
        if word.endswith(p):
            cleaned = word[:-len(p)]
            if len(cleaned) >= 2:
                return cleaned
    return word

def extract_nicknames(db, question: str) -> list[str]:

    words = re.findall(r"[가-힣A-Za-z]{2,12}", question)

    candidates = []
    for w in words:
        cleaned = clean_word(w)
        if cleaned not in STOPWORDS:
            candidates.append(cleaned)

    nicknames = []
    seen = set()
    
    for w in sorted(candidates, key=len, reverse=True):
        if w not in seen and validate_nickname(db, w):
            nicknames.append(w)
            seen.add(w)

    return nicknames
