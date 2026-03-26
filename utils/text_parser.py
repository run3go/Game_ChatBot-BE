import re
from service.nickname_service import validate_nickname

POSTPOSITIONS = ["은", "는", "이", "가", "을", "를", "의", "와", "과", "랑", "이랑"]
STOPWORDS = ["스킬", "보석", "각인", "아바타", "장비", "내실", "능력치", "아크패시브", "아크그리드"]

def clean_word(word: str) -> str:
    for _ in range(3):
        changed = False
        for p in sorted(POSTPOSITIONS, key=len, reverse=True):
            if word.endswith(p):
                cleaned = word[:-len(p)]
                if len(cleaned) >= 2:
                    word = cleaned
                    changed = True
                    break
        if not changed:
            break
    return word

def extract_nicknames(db, question: str) -> list[str]:

    words = re.findall(r"[가-힣A-Za-z0-9]{2,12}", question)

    nicknames = []
    seen = set()

    for w in sorted(words, key=len, reverse=True):
        if w in seen:
            continue
        if validate_nickname(db, w):
            nicknames.append(w)
            seen.add(w)
        else:
            cleaned = clean_word(w)
            if cleaned != w and cleaned not in seen and cleaned not in STOPWORDS and validate_nickname(db, cleaned):
                nicknames.append(cleaned)
                seen.add(cleaned)

    return nicknames
