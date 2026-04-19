import logging
from sqlalchemy import text
from sqlalchemy.orm import Session
from utils.lazy_embeddings import EmbeddingsMixin

logger = logging.getLogger(__name__)


class FewShotStore(EmbeddingsMixin):

    def retrieve(self, db: Session, question: str, category: str = "", k: int = 3) -> str:
        try:
            vector = self._get_embeddings().embed_query(question)
        except Exception:
            logger.exception("few-shot 임베딩 생성 실패")
            return ""

        all_rows = db.execute(text("""
            SELECT question, question_category, analysis_type, explanation, sql_query,
                   embedding <=> CAST(:embedding AS vector) AS distance
            FROM lostark.few_shot_examples_2
            ORDER BY
                CASE WHEN question_category = :category THEN 0 ELSE 1 END,
                embedding <=> CAST(:embedding AS vector)
            LIMIT 10
        """), {"embedding": str(vector), "category": category}).mappings().all()

        if not all_rows:
            return ""

        if logger.isEnabledFor(logging.DEBUG):
            header = f"{'순위':<4} {'거리(낮을수록 유사)':<22} {'카테고리':<20} 질문"
            rows_text = "\n".join(
                f"{i:<4} {row['distance']:<22.6f} {row['question_category']:<20} {row['question']}"
                for i, row in enumerate(all_rows, 1)
            )
            logger.debug("[few-shot 유사도 점수] 질문: %r\n%s\n%s", question, header, rows_text)

        rows = all_rows[:k]
        parts = ["[유사 예시 - 아래 패턴을 참고해서 SQL을 작성해]"]
        for i, row in enumerate(rows, 1):
            parts.append(
                f"예시 {i})\n"
                f"- 질문: {row['question']}\n"
                f"- 카테고리: {row['question_category']}\n"
                f"- 분석 유형: {row['analysis_type']}\n"
                f"- 힌트: {row['explanation']}\n"
                f"- SQL:\n{row['sql_query']}"
            )
        return "\n\n".join(parts)


FEW_SHOT_STORE = FewShotStore()
