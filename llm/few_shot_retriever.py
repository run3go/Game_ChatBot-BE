import os
import logging
from langchain_openai import OpenAIEmbeddings
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class FewShotStore:

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

    def retrieve(self, db: Session, question: str, k: int = 3) -> str:
        try:
            vector = self._get_embeddings().embed_query(question)
        except Exception:
            logger.exception("few-shot 임베딩 생성 실패")
            return ""

        rows = db.execute(text("""
            SELECT question, analysis_type, explanation, sql_query
            FROM lostark.few_shot_examples
            ORDER BY embedding <=> CAST(:embedding AS vector)
            LIMIT :k
        """), {"embedding": str(vector), "k": k}).mappings().all()

        if not rows:
            return ""

        parts = ["[유사 예시 - 아래 패턴을 참고해서 SQL을 작성해]"]
        for i, row in enumerate(rows, 1):
            parts.append(
                f"예시 {i})\n"
                f"- 질문: {row['question']}\n"
                f"- 분석 유형: {row['analysis_type']}\n"
                f"- 힌트: {row['explanation']}\n"
                f"- SQL:\n{row['sql_query']}"
            )
        return "\n\n".join(parts)


FEW_SHOT_STORE = FewShotStore()
