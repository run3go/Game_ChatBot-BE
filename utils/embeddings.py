import os
from langchain_openai import OpenAIEmbeddings


def get_openrouter_embeddings() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        model="openai/text-embedding-3-small",
        openai_api_key=os.getenv("OPENROUTER_API_KEY"),
        openai_api_base="https://openrouter.ai/api/v1",
    )
