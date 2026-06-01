import logging
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import text
from sqlalchemy.orm import Session
from utils.lazy_embeddings import EmbeddingsMixin
from utils.reranker import CROSS_ENCODER

logger = logging.getLogger(__name__)


class EmbeddingLookupRetriever(EmbeddingsMixin):
    _schema: str = ""
    _TYPE_TO_CATEGORY: dict[str, str] = {}
    _DOMAIN_TAGS: set[str] = set()
    _NICKNAME_EXCLUDE_TYPES: set[str] = set()
    _TYPE_LABEL: dict[str, str] = {}

    def _text_search(self, db: Session, keywords: list[str], k: int) -> list[dict]:
        table = f"{self._schema}.embedding_lookup"
        sql = (
            f"SELECT formal_name, type, related_tables, embedding_text, COUNT(*) AS match_count"
            f" FROM {table},"
            f" UNNEST(string_to_array(embedding_text, ', ')) AS term"
            f" WHERE EXISTS ("
            f"   SELECT 1 FROM UNNEST(CAST(:keywords AS text[])) AS kw"
            f"   WHERE kw ILIKE '%' || term || '%'"
            f"      OR term ILIKE '%' || kw || '%'"
            f"      OR REPLACE(kw, ' ', '') ILIKE '%' || REPLACE(term, ' ', '') || '%'"
            f"      OR REPLACE(term, ' ', '') ILIKE '%' || REPLACE(kw, ' ', '') || '%'"
            f" )"
            f" GROUP BY formal_name, type, related_tables, embedding_text"
            f" ORDER BY match_count DESC"
            f" LIMIT :k"
        )
        rows = db.execute(text(sql), {"keywords": keywords, "k": k}).mappings().all()
        return [
            {
                "formal_name": row["formal_name"],
                "type": row["type"],
                "related_tables": row["related_tables"] or [],
                "embedding_text": row["embedding_text"],
            }
            for row in rows
        ]

    def _fetch_vectors(self, keywords: list[str]) -> list[list[float]] | None:
        try:
            return self._get_embeddings().embed_documents(keywords)
        except Exception:
            logger.exception("embedding_lookup 임베딩 생성 실패")
            return None

    def _vector_search_with_vectors(self, db: Session, vectors: list[list[float]], k: int, threshold: float) -> list[dict]:
        table = f"{self._schema}.embedding_lookup"
        sql = (
            f"SELECT formal_name, type, related_tables, embedding_text,"
            f"       1 - (embedding <=> CAST(:vec AS vector)) AS score"
            f" FROM {table}"
            f" WHERE embedding IS NOT NULL"
            f" ORDER BY embedding <=> CAST(:vec AS vector)"
            f" LIMIT :k"
        )
        best: dict[str, dict] = {}
        for vector in vectors:
            rows = db.execute(text(sql), {"vec": str(vector), "k": k}).mappings().all()
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

        top = sorted(best.items(), key=lambda x: -x[1]["score"])[:5]
        logger.debug("embedding_lookup 벡터 점수 (상위 5): %s",
                     [(name, round(e["score"], 4)) for name, e in top])

        return [
            {key: val for key, val in e.items() if key != "score"}
            for e in sorted(best.values(), key=lambda x: -x["score"])
            if e["score"] >= threshold
        ]

    def retrieve(
        self,
        db: Session,
        question: str,
        k: int = 5,
        fallback_threshold: float = 0.50,
        candidate_k: int = 10,
    ) -> list[dict]:
        keywords = [question]

        with ThreadPoolExecutor(max_workers=1) as executor:
            embed_future = executor.submit(self._fetch_vectors, keywords)

            try:
                text_results = self._text_search(db, keywords, candidate_k)
            except Exception:
                logger.exception("embedding_lookup 텍스트 검색 실패")
                db.rollback()
                text_results = []

            logger.info("embedding_lookup 텍스트 매칭: %s", [r["formal_name"] for r in text_results])

            try:
                vectors = embed_future.result(timeout=10)
                if vectors:
                    vector_results = self._vector_search_with_vectors(db, vectors, candidate_k, fallback_threshold)
                else:
                    vector_results = []
            except Exception:
                logger.exception("embedding_lookup 벡터 검색 실패")
                db.rollback()
                vector_results = []

        seen = {r["formal_name"] for r in text_results}
        merged = list(text_results)
        for r in vector_results:
            if r["formal_name"] not in seen:
                merged.append(r)
                seen.add(r["formal_name"])

        if merged:
            try:
                merged = CROSS_ENCODER.rerank(question, merged, text_key="embedding_text")
                merged = merged[:k]
            except Exception:
                logger.exception("CrossEncoder 재정렬 실패, 1차 결과 그대로 사용")
                merged = merged[:k]

        logger.info("embedding_lookup 최종: %s", [r["formal_name"] for r in merged])
        return merged

    def _get_abbrs(self, entry: dict) -> list[str]:
        formal_name = entry.get("formal_name", "")
        raw_terms = [t.strip() for t in entry.get("embedding_text", "").split(",")]
        return [t for t in raw_terms if t and t != formal_name and t not in self._DOMAIN_TAGS]

    def get_excluded_nickname_terms(self, entries: list[dict]) -> list[str]:
        terms = []
        for entry in entries:
            if entry.get("type") not in self._NICKNAME_EXCLUDE_TYPES:
                continue
            terms.extend(self._get_abbrs(entry))
        return terms

    def _find_match_in_question(self, question: str, entry: dict) -> str | None:
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
        hints = []
        for entry in entries:
            formal_name = entry["formal_name"]
            matched = None
            for abbr in self._get_abbrs(entry):
                if abbr in question:
                    matched = abbr
                    break
            if not matched:
                normalized = formal_name.replace(" ", "")
                if normalized != formal_name and normalized in question:
                    matched = normalized
            type_label = self._TYPE_LABEL.get(entry.get("type", ""), "")
            type_str = f" [{type_label}]" if type_label else ""
            hints.append(f"{matched}→{formal_name}{type_str}" if matched else f"{formal_name}{type_str}")
        return ", ".join(hints) if hints else "없음"

    def top_matches_with_scores(self, db: Session, question: str, k: int = 3) -> list[dict]:
        """게임 감지용 — 벡터 유사도 상위 k개를 score 포함해서 반환."""
        vectors = self._fetch_vectors([question])
        if not vectors:
            return []
        table = f"{self._schema}.embedding_lookup"
        sql = (
            f"SELECT formal_name, 1 - (embedding <=> CAST(:vec AS vector)) AS score"
            f" FROM {table}"
            f" WHERE embedding IS NOT NULL"
            f" ORDER BY embedding <=> CAST(:vec AS vector)"
            f" LIMIT :k"
        )
        try:
            rows = db.execute(text(sql), {"vec": str(vectors[0]), "k": k}).mappings().all()
            return [{"formal_name": row["formal_name"], "score": float(row["score"])} for row in rows]
        except Exception:
            logger.exception("top_matches_with_scores 실패 (%s)", self._schema)
            db.rollback()
            return []

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


class LOSTARKEmbeddingLookup(EmbeddingLookupRetriever):
    _schema = "lostark"

    _TYPE_TO_CATEGORY: dict[str, str] = {
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

    _DOMAIN_TAGS: set[str] = {
        "스킬", "룬", "보석", "각인", "아크패시브", "수집품", "카드", "스탯", "장비", "장신구", "악세", "직업", "클래스",
    }

    _NICKNAME_EXCLUDE_TYPES: set[str] = {"CLASS", "ARK_PASSIVE_CLASS"}

    _TYPE_LABEL: dict[str, str] = {
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


class TFTEmbeddingLookup(EmbeddingLookupRetriever):
    _schema = "tft"

    _TYPE_TO_CATEGORY: dict[str, str] = {}  # TFT는 엔티티 타입으로 카테고리 추론 불가

    _DOMAIN_TAGS: set[str] = {"챔피언", "기물", "증강체", "아이템", "특성", "덱", "조합"}

    _NICKNAME_EXCLUDE_TYPES: set[str] = set()  # 이름#태그 형식으로 구분되어 불필요

    _TYPE_LABEL: dict[str, str] = {
        "UNIT":    "챔피언",
        "ITEM":    "아이템",
        "AUGMENT": "증강체",
        "TRAIT":   "특성",
    }


EMBEDDING_LOOKUP: dict[str, EmbeddingLookupRetriever] = {
    "LOSTARK": LOSTARKEmbeddingLookup(),
    "TFT":     TFTEmbeddingLookup(),
}
