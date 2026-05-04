import logging
from sentence_transformers.cross_encoder import CrossEncoder

logger = logging.getLogger(__name__)

# 다국어(한국어 포함) 크로스 인코더 - 1차 검색 결과를 재검증·재정렬
_MODEL_NAME = "BAAI/bge-reranker-v2-m3"


class CrossEncoderReranker:
    _model: CrossEncoder | None = None

    def _get_model(self) -> CrossEncoder:
        if self._model is None:
            logger.info("CrossEncoder 모델 로딩: %s", _MODEL_NAME)
            self._model = CrossEncoder(_MODEL_NAME, automodel_args={"torch_dtype": "float16"})
        return self._model

    def rerank(
        self,
        query: str,
        entries: list[dict],
        text_key: str = "embedding_text",
        threshold: float | None = None,
    ) -> list[dict]:
        """
        1차 검색 후보를 CrossEncoder로 재정렬.

        - query: 원본 질문
        - entries: 1차 검색 결과 (dict 리스트)
        - text_key: 비교 대상 텍스트가 담긴 필드명
        - threshold: 이 점수 미만 항목은 제거 (None이면 필터링 없이 재정렬만)
        """
        if not entries:
            return entries

        model = self._get_model()
        pairs = [(query, entry.get(text_key, "")) for entry in entries]
        scores = model.predict(pairs).tolist()

        scored = sorted(zip(scores, entries), key=lambda x: -x[0])

        logger.info(
            "CrossEncoder 재정렬 점수: %s",
            [(e.get("formal_name", e.get(text_key, ""))[:20], round(float(s), 4)) for s, e in scored],
        )

        if threshold is not None:
            scored = [(s, e) for s, e in scored if s >= threshold]

        return [e for _, e in scored]


CROSS_ENCODER = CrossEncoderReranker()
