import re
from service.nickname_service import validate_nickname
from constants import POSTPOSITIONS, STOPWORDS

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

def format_history(history: list[dict], limit: int = 6) -> str:
    lines = []
    regular = []
    for m in history:
        if m['role'] == 'summary':
            lines.append(f"[이전 대화 요약]\n{m['content']}")
        else:
            regular.append(m)
    for m in regular[-limit:]:
        if m['role'] == 'user':
            line = f"사용자: {m['content']}"
            if m.get('nicknames'):
                line += f" [닉네임: {', '.join(m['nicknames'])}]"
            if m.get('keywords'):
                line += f" [키워드: {', '.join(m['keywords'])}]"
        else:
            line = f"AI: {m['content']}"
        lines.append(line)
    return "\n".join(lines)

def extract_nicknames(db, question: str) -> list[str]:

    words = re.findall(r"[가-힣A-Za-z]{2,12}", question)

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
