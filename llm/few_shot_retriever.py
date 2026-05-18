import logging
from sqlalchemy import text
from sqlalchemy.orm import Session
from utils.lazy_embeddings import EmbeddingsMixin

logger = logging.getLogger(__name__)

_FEW_SHOT_TABLE: dict[str, str] = {
    "LOSTARK": "lostark.few_shot_examples_2",
    "TFT":     "tft.few_shot_examples",
}


class FewShotStore(EmbeddingsMixin):

    def retrieve(
        self,
        db: Session,
        question: str,
        category: str = "",
        game_type: str = "LOSTARK",
        k: int = 3,
        similarity_threshold: float = 0.20,
    ) -> str:
        table = _FEW_SHOT_TABLE.get(game_type, _FEW_SHOT_TABLE["LOSTARK"])

        try:
            vector = self._get_embeddings().embed_query(question)
        except Exception:
            logger.exception("few-shot 임베딩 생성 실패")
            return ""

        # 카테고리 일치 예시는 무조건 포함,
        # 타 카테고리는 유사도 임계값(distance < threshold) 이상인 것만 보충
        sql = (
            "WITH scored AS ("
            "  SELECT question, question_category, analysis_type, explanation, sql_query,"
            "         embedding <=> CAST(:embedding AS vector) AS distance"
            f" FROM {table}"
            ") "
            "SELECT * FROM scored"
            " WHERE question_category = :category"
            "    OR distance < :threshold"
            " ORDER BY"
            "    CASE WHEN question_category = :category THEN 0 ELSE 1 END,"
            "    distance"
            " LIMIT :limit"
        )
        all_rows = db.execute(
            text(sql),
            {
                "embedding": str(vector),
                "category": category,
                "threshold": similarity_threshold,
                "limit": k * 3,
            },
        ).mappings().all()

        if not all_rows:
            return ""

        if logger.isEnabledFor(logging.DEBUG):
            header = f"{'순위':<4} {'거리':<10} {'카테고리':<30} 질문"
            rows_text = "\n".join(
                f"{i:<4} {row['distance']:<10.4f} {row['question_category']:<30} {row['question']}"
                for i, row in enumerate(all_rows, 1)
            )
            logger.debug("[few-shot] 질문: %r\n%s\n%s", question, header, rows_text)

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
