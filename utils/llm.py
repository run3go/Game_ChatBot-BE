import os

from langchain_openai import ChatOpenAI

_base = dict(
    temperature=0,
    max_tokens=8192,
    timeout=60,
    openai_api_key=os.getenv("OPENROUTER_API_KEY"),
    openai_api_base="https://openrouter.ai/api/v1",
    default_headers={"X-Title": "LostArk Chatbot"},
)

# 분석용
llm = ChatOpenAI(model="openai/gpt-4o-mini", **_base)

# 답변 생성용 (스트리밍 속도 우선)
llm_answer = ChatOpenAI(model="openai/gpt-4o-mini", **{**_base, "max_tokens": 16384})

# SQL 생성용
llm_sql = ChatOpenAI(model="openai/gpt-4o-mini", **_base)
