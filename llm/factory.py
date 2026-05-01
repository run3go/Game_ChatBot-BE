from langchain_openai import ChatOpenAI
from core.config import settings

def create_llm_instances():
    base_config = dict(
        temperature=0,
        max_tokens=8192,
        timeout=60,
        openai_api_key=settings.OPENROUTER_API_KEY,
        openai_api_base=settings.OPENROUTER_BASE_URL,
        default_headers={"X-Title": "LostArk Chatbot"},
    )

    return {
        "analyze": ChatOpenAI(model=settings.MODEL_ANALYZE, **base_config),
        "answer": ChatOpenAI(model=settings.MODEL_ANSWER, **{**base_config, "max_tokens": 16384}),
        "sql": ChatOpenAI(model=settings.MODEL_SQL, **base_config),
    }