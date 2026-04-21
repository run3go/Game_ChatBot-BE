import logging
from sqlalchemy import text
from sqlalchemy.orm import Session
from utils.lazy_embeddings import EmbeddingsMixin

logger = logging.getLogger(__name__)


class EmbeddingLookupRetriever(EmbeddingsMixin):

    def __init__(self):
        self._llm = None

    def _get_llm(self):
        if self._llm is None:
            from utils.llm import llm_sql
            self._llm = llm_sql
        return self._llm

    def _extract_keywords(self, question: str) -> list[str]:
        """LLM으로 질문에서 게임 용어 키워드만 추출."""
        try:
            result = self._get_llm().invoke(
                f'로스트아크 게임 용어 키워드만 쉼표로 추출해. 조사·부사·동사·일반어는 제외.\n"{question}"',
                max_tokens=64,
            )
            keywords = [k.strip() for k in result.content.split(",") if k.strip()][:10]
        except Exception:
            logger.exception("embedding_lookup 키워드 추출 실패, 질문 전체 사용")
            keywords = [question]
        logger.info("embedding_lookup 키워드 추출: %s", keywords)
        return keywords or [question]

    def _text_search(self, db: Session, keywords: list[str], k: int) -> list[dict]:
        """키워드별로 embedding_text 텍스트 매칭 (공백 정규화 포함)"""
        rows = db.execute(text("""
            SELECT formal_name, type, related_tables, embedding_text, COUNT(*) AS match_count
            FROM lostark.embedding_lookup,
                 UNNEST(string_to_array(embedding_text, ', ')) AS term
            WHERE EXISTS (
                SELECT 1 FROM UNNEST(CAST(:keywords AS text[])) AS kw
                WHERE kw ILIKE '%' || term || '%'
                   OR term ILIKE '%' || kw || '%'
                   OR REPLACE(kw, ' ', '') ILIKE '%' || REPLACE(term, ' ', '') || '%'
                   OR REPLACE(term, ' ', '') ILIKE '%' || REPLACE(kw, ' ', '') || '%'
            )
            GROUP BY formal_name, type, related_tables, embedding_text
            ORDER BY match_count DESC
            LIMIT :k
        """), {"keywords": keywords, "k": k}).mappings().all()

        return [
            {
                "formal_name": row["formal_name"],
                "type": row["type"],
                "related_tables": row["related_tables"] or [],
                "embedding_text": row["embedding_text"],
            }
            for row in rows
        ]

    def _vector_search(self, db: Session, keywords: list[str], k: int, threshold: float) -> list[dict]:
        """키워드별 개별 임베딩 후 최고 점수 기준으로 병합 (배치 API 1회 호출)"""
        try:
            vectors = self._get_embeddings().embed_documents(keywords)
        except Exception:
            logger.exception("embedding_lookup 임베딩 생성 실패")
            return []

        # 키워드별로 DB 검색, entry별 최고 점수 유지
        best: dict[str, dict] = {}  # formal_name → {entry, score}

        for vector in vectors:
            rows = db.execute(text("""
                SELECT formal_name, type, related_tables, embedding_text,
                       1 - (embedding <=> CAST(:vec AS vector)) AS score
                FROM lostark.embedding_lookup
                WHERE embedding IS NOT NULL
                ORDER BY embedding <=> CAST(:vec AS vector)
                LIMIT :k
            """), {"vec": str(vector), "k": k}).mappings().all()

            for row in rows:
                score = float(row["score"])
                name = row["formal_name"]
                if name not in best or score > best[name]["score"]:
                    best[name] = {
                        "formal_name": name,
                        "type": row["type"],
                        "related_tables": row["related_tables"] or [],
                        "embedding_text": row["embedding_text"] or "",
                        "score": score,
                    }

        logger.info("embedding_lookup 벡터 점수 (키워드별 최고): %s",
                    [(name, round(e["score"], 4)) for name, e in
                     sorted(best.items(), key=lambda x: -x[1]["score"])])

        return [
            {k: v for k, v in e.items() if k != "score"}
            for e in sorted(best.values(), key=lambda x: -x["score"])
            if e["score"] >= threshold
        ]

    def retrieve(self, db: Session, question: str, k: int = 5, fallback_threshold: float = 0.50) -> list[dict]:
        keywords = self._extract_keywords(question) or [question]

        try:
            text_results = self._text_search(db, keywords, k)
        except Exception:
            logger.exception("embedding_lookup 텍스트 검색 실패")
            db.rollback()
            text_results = []

        logger.info("embedding_lookup 텍스트 매칭: %s", [r["formal_name"] for r in text_results])

        try:
            vector_results = self._vector_search(db, keywords, k, fallback_threshold)
        except Exception:
            logger.exception("embedding_lookup 벡터 검색 실패")
            db.rollback()
            vector_results = []

        # 텍스트 결과 우선, 벡터 결과로 중복 없이 보충
        seen = {r["formal_name"] for r in text_results}
        merged = list(text_results)
        for r in vector_results:
            if r["formal_name"] not in seen:
                merged.append(r)
                seen.add(r["formal_name"])

        logger.info("embedding_lookup 최종: %s", [r["formal_name"] for r in merged])
        return merged

    # 테이블 type → 분석 카테고리 매핑
    # 닉네임 있으면 앞 카테고리, 없으면 뒤 카테고리 사용
    _TYPE_TO_CATEGORY = {
        "SKILL":              "SKILL / GLOBAL_SKILL",
        "RUNE":               "SKILL / GLOBAL_SKILL",
        "GEM":                "SKILL / GLOBAL_SKILL",
        "ENGRAVING":          "ENGRAVING / GLOBAL_ENGRAVING",
        "ARK_PASSIVE_EFFECT": "ARK_PASSIVE / GLOBAL_ARK_PASSIVE",
        "ARK_PASSIVE_CLASS":  "ARK_PASSIVE / GLOBAL_ARK_PASSIVE · 닉네임 제외 대상 (아크패시브 클래스 유형)",
        "PROFILE":            "PROFILE",
        "COLLECTIBLE":        "COLLECTIBLE",
        "CARD":               "PROFILE",
        "CLASS":              "PROFILE / GLOBAL_PROFILE · 닉네임 제외 대상 (직업명·클래스)",
    }

    # embedding_text에 포함된 도메인 태그 (약어가 아닌 검색용 분류어)
    _DOMAIN_TAGS = {"스킬", "룬", "보석", "각인", "아크패시브", "수집품", "카드", "스탯", "장비", "장신구", "악세", "직업", "클래스"}

    _NICKNAME_EXCLUDE_TYPES = {"CLASS", "ARK_PASSIVE_CLASS"}

    def _get_abbrs(self, entry: dict) -> list[str]:
        formal_name = entry.get("formal_name", "")
        raw_terms = [t.strip() for t in entry.get("embedding_text", "").split(",")]
        return [t for t in raw_terms if t and t != formal_name and t not in self._DOMAIN_TAGS]

    def get_excluded_nickname_terms(self, entries: list[dict]) -> list[str]:
        """CLASS·ARK_PASSIVE_CLASS 타입 entry의 모든 약어와 정식 명칭을 반환. 닉네임 제외 목록으로 사용."""
        terms = []
        for entry in entries:
            if entry.get("type") not in self._NICKNAME_EXCLUDE_TYPES:
                continue
            terms.extend(self._get_abbrs(entry))
        return terms

    def _find_match_in_question(self, question: str, entry: dict) -> str | None:
        """질문에서 이 entry와 매칭되는 텍스트 반환 (formal_name 포함)."""
        formal_name = entry.get("formal_name", "")
        for abbr in self._get_abbrs(entry):
            if abbr in question:
                return abbr
        normalized = formal_name.replace(" ", "")
        if normalized != formal_name and normalized in question:
            return normalized
        if formal_name in question:
            return formal_name
        return None

    def filter_subsumed(self, question: str, entries: list[dict]) -> list[dict]:
        """질문에서 매칭된 텍스트가 다른 entry의 더 긴 매칭 텍스트의 부분 문자열인 entry를 제거.
        예: '버스트'(ARK_PASSIVE_CLASS)가 '버스트 캐넌'(SKILL) 안에 포함되면 제거."""
        matched = {e["formal_name"]: self._find_match_in_question(question, e) for e in entries}
        matched_texts = {t for t in matched.values() if t}
        result = []
        for entry in entries:
            m = matched[entry["formal_name"]]
            if m and any(m != longer and m in longer for longer in matched_texts):
                continue
            result.append(entry)
        return result

    def format_term_hints(self, question: str, entries: list[dict]) -> str:
        """embedding 검색으로 찾은 모든 정식 명칭을 힌트로 반환. 질문에서 매칭된 표현이 있으면 '매칭어→정식명', 없으면 정식명만 출력."""
        hints = []
        for entry in entries:
            formal_name = entry["formal_name"]
            matched = None

            # 1. embedding_text의 약어가 질문에 포함되는지 확인
            for abbr in self._get_abbrs(entry):
                if abbr in question:
                    matched = abbr
                    break

            # 2. 공백 제거한 정식명이 질문에 포함되는지 확인 (예: 라이징클로→라이징 클로)
            if not matched:
                normalized = formal_name.replace(" ", "")
                if normalized != formal_name and normalized in question:
                    matched = normalized

            type_label = self._TYPE_LABEL.get(entry.get("type", ""), "")
            type_str = f" [{type_label}]" if type_label else ""
            hints.append(f"{matched}→{formal_name}{type_str}" if matched else f"{formal_name}{type_str}")
        return ", ".join(hints) if hints else "없음"

    _TYPE_LABEL = {
        "RUNE": "룬",
        "SKILL": "스킬",
        "ENGRAVING": "각인",
        "ARK_PASSIVE_EFFECT": "아크패시브 효과",
        "ARK_PASSIVE_CLASS": "아크패시브 클래스",
        "CARD": "카드",
        "CLASS": "직업",
        "COLLECTIBLE": "수집품",
        "PROFILE": "프로필",
    }

    def format_context(self, entries: list[dict]) -> str:
        if not entries:
            return ""
        lines = ["[질문 관련 게임 용어 힌트 - 아래 약어는 게임 용어이며 닉네임이 아님]"]
        for e in entries:
            category = self._TYPE_TO_CATEGORY.get(e["type"], e["type"])
            type_label = self._TYPE_LABEL.get(e["type"], "")
            abbrs = self._get_abbrs(e)
            abbr_str = f" (약어: {', '.join(abbrs)})" if abbrs else ""
            type_str = f" [{type_label}]" if type_label else ""
            lines.append(f"- {e['formal_name']}{type_str}{abbr_str} → {category}")
        return "\n".join(lines)


EMBEDDING_LOOKUP = EmbeddingLookupRetriever()
