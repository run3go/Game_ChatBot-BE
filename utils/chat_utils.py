import re
from service.nickname_service import validate_nicknames_batch
from constants import POSTPOSITIONS, STOPWORDS

def clean_word(word: str) -> str:
    for p in sorted(POSTPOSITIONS, key=len, reverse=True):
        if word.endswith(p):
            cleaned = word[:-len(p)]
            if len(cleaned) >= 2:
                return cleaned
            break
    return word

def format_history(history: list[dict], limit: int = 6, max_ai_length: int | None = None) -> str:
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
        else:
            content = m['content']
            if max_ai_length and len(content) > max_ai_length:
                content = content[:max_ai_length] + "..."
            line = f"AI: {content}"
        lines.append(line)
    return "\n".join(lines)

def extract_nicknames(db, question: str) -> list[str]:
    words = re.findall(r"[가-힣A-Za-z]{2,12}", question)

    seen = set()
    ordered = [] 
    word_to_cleaned = {}

    for w in sorted(words, key=len, reverse=True):
        if w in seen:
            continue
        seen.add(w)
        ordered.append(w)
        cleaned = clean_word(w)
        if cleaned != w and cleaned not in seen and cleaned not in STOPWORDS:
            word_to_cleaned[w] = cleaned

    to_check = list(ordered) + list(word_to_cleaned.values())
    verified, _ = validate_nicknames_batch(db, to_check)
    verified_set = set(verified)

    nicknames = []
    for w in ordered:
        if w in verified_set:
            nicknames.append(w)
        elif word_to_cleaned.get(w) in verified_set:
            nicknames.append(word_to_cleaned[w])

    return nicknames