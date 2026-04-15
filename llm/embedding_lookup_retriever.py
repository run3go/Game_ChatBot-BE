import os
import logging
from langchain_openai import OpenAIEmbeddings
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class EmbeddingLookupRetriever:

    def __init__(self):
        self._embeddings: OpenAIEmbeddings | None = None

    def _get_embeddings(self) -> OpenAIEmbeddings:
        if self._embeddings is None:
            self._embeddings = OpenAIEmbeddings(
                model="openai/text-embedding-3-small",
                openai_api_key=os.getenv("OPENROUTER_API_KEY"),
                openai_api_base="https://openrouter.ai/api/v1",
            )
        return self._embeddings

    def _text_search(self, db: Session, question: str, k: int) -> list[dict]:
        """embedding_text의 각 키워드가 질문에 포함되는지 텍스트 매칭"""
        rows = db.execute(text("""
            SELECT formal_name, type, related_tables, embedding_text, COUNT(*) AS match_count
            FROM lostark.embedding_lookup,
                 UNNEST(string_to_array(embedding_text, ', ')) AS term
            WHERE :question ILIKE '%' || term || '%'
            GROUP BY formal_name, type, related_tables, embedding_text
            ORDER BY match_count DESC
            LIMIT :k
        """), {"question": question, "k": k}).mappings().all()

        return [
            {
                "formal_name": row["formal_name"],
                "type": row["type"],
                "related_tables": row["related_tables"] or [],
                "embedding_text": row["embedding_text"],
            }
            for row in rows
        ]

    def _vector_search(self, db: Session, question: str, k: int, threshold: float) -> list[dict]:
        """오타 등 텍스트 매칭 실패 시 임베딩 유사도로 폴백"""
        try:
            vector = self._get_embeddings().embed_query(question)
        except Exception:
            logger.exception("embedding_lookup 임베딩 생성 실패")
            return []

        rows = db.execute(text("""
            SELECT formal_name, type, related_tables,
                   1 - (embedding <=> CAST(:vec AS vector)) AS score
            FROM lostark.embedding_lookup
            WHERE embedding IS NOT NULL
            ORDER BY embedding <=> CAST(:vec AS vector)
            LIMIT :k
        """), {"vec": str(vector), "k": k}).mappings().all()

        return [
            {
                "formal_name": row["formal_name"],
                "type": row["type"],
                "related_tables": row["related_tables"] or [],
            }
            for row in rows
            if float(row["score"]) >= threshold
        ]

    def retrieve(self, db: Session, question: str, k: int = 5, fallback_threshold: float = 0.55) -> list[dict]:
        try:
            results = self._text_search(db, question, k)
        except Exception:
            logger.exception("embedding_lookup 텍스트 검색 실패")
            db.rollback()
            results = []

        if results:
            logger.info("embedding_lookup 텍스트 매칭: %s", [r["formal_name"] for r in results])
            return results

        # 텍스트 매칭 실패 시 (오타 등) 임베딩 폴백
        logger.info("embedding_lookup 텍스트 매칭 없음 → 임베딩 폴백")
        try:
            results = self._vector_search(db, question, k, fallback_threshold)
        except Exception:
            logger.exception("embedding_lookup 벡터 검색 실패")
            db.rollback()
            return []

        logger.info("embedding_lookup 벡터 폴백 결과: %s", [r["formal_name"] for r in results])
        return results

    # 테이블 type → 분석 카테고리 매핑
    # 닉네임 있으면 앞 카테고리, 없으면 뒤 카테고리 사용
    _TYPE_TO_CATEGORY = {
        "SKILL":              "SKILL / GLOBAL_SKILL",
        "RUNE":               "SKILL / GLOBAL_SKILL",
        "ENGRAVING":          "ENGRAVING / GLOBAL_ENGRAVING",
        "ARK_PASSIVE_EFFECT": "ARK_PASSIVE / GLOBAL_ARK_PASSIVE",
        "ARK_PASSIVE_CLASS":  "ARK_PASSIVE / GLOBAL_ARK_PASSIVE · 닉네임 제외 대상 (아크패시브 클래스 유형)",
        "PROFILE":            "PROFILE",
        "COLLECTIBLE":        "COLLECTIBLE",
        "CARD":               "PROFILE",
        "CLASS":              "PROFILE / GLOBAL_PROFILE · 닉네임 제외 대상 (직업명·클래스)",
    }

    # embedding_text에 포함된 도메인 태그 (약어가 아닌 검색용 분류어)
    _DOMAIN_TAGS = {"스킬", "룬", "각인", "아크패시브", "수집품", "카드", "스탯", "장비", "장신구", "악세", "직업", "클래스"}

    _NICKNAME_EXCLUDE_TYPES = {"CLASS", "ARK_PASSIVE_CLASS"}

    def get_excluded_nickname_terms(self, entries: list[dict]) -> list[str]:
        """CLASS·ARK_PASSIVE_CLASS 타입 entry의 모든 약어와 정식 명칭을 반환. 닉네임 제외 목록으로 사용."""
        terms = []
        for entry in entries:
            if entry.get("type") not in self._NICKNAME_EXCLUDE_TYPES:
                continue
            raw_terms = [t.strip() for t in entry.get("embedding_text", "").split(",")]
            terms.extend(t for t in raw_terms if t and t not in self._DOMAIN_TAGS)
        return terms

    def format_abbr_hints(self, question: str, entries: list[dict]) -> str:
        """질문에 포함된 약어와 정식 명칭 매핑을 힌트 문자열로 반환. 예: '기술→아르데타인의 기술, 스카→스카우터'"""
        hints = []
        for entry in entries:
            raw_terms = [t.strip() for t in entry.get("embedding_text", "").split(",")]
            abbrs = [t for t in raw_terms if t and t != entry["formal_name"] and t not in self._DOMAIN_TAGS]
            for abbr in abbrs:
                if abbr in question:
                    hints.append(f"{abbr}→{entry['formal_name']}")
        return ", ".join(hints) if hints else "없음"

    def format_context(self, entries: list[dict]) -> str:
        if not entries:
            return ""
        lines = ["[질문 관련 게임 용어 힌트 - 아래 약어는 게임 용어이며 닉네임이 아님]"]
        for e in entries:
            category = self._TYPE_TO_CATEGORY.get(e["type"], e["type"])
            raw_terms = [t.strip() for t in e.get("embedding_text", "").split(",")]
            abbrs = [t for t in raw_terms if t and t != e["formal_name"] and t not in self._DOMAIN_TAGS]
            abbr_str = f" (약어: {', '.join(abbrs)})" if abbrs else ""
            lines.append(f"- {e['formal_name']}{abbr_str} → {category}")
        return "\n".join(lines)


EMBEDDING_LOOKUP = EmbeddingLookupRetriever()
