from langchain_openai import OpenAIEmbeddings
from utils.embeddings import get_openrouter_embeddings


class EmbeddingsMixin:
    _embeddings: OpenAIEmbeddings | None = None

    def _get_embeddings(self) -> OpenAIEmbeddings:
        if self._embeddings is None:
            self._embeddings = get_openrouter_embeddings()
        return self._embeddings
