import re
from service.nickname_service import validate_nickname

POSTPOSITIONS = ["은", "는", "이", "가", "을", "를", "의", "와", "과", "랑", "이랑"]

def clean_word(word: str):
    for p in POSTPOSITIONS:
        if word.endswith(p):
            return word[:-len(p)]
    return word

def extract_nicknames(db, question):

    words = re.findall(r"[가-힣A-Za-z0-9]{2,12}", question)

    candidates = [clean_word(w) for w in words]

    STOPWORDS = ["스킬", "보석", "각인", "아바타", "장비", "내실", "능력치", "아크패시브", "아크그리드"]
    candidates = [w for w in candidates if w not in STOPWORDS]

    candidates.sort(key=len, reverse=True)

    nicknames = []
    
    for w in candidates:
        if validate_nickname(db, w):
            nicknames.append(w)

    return nicknames
