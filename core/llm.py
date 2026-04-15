import os

from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    model="meta-llama/llama-3.3-70b-instruct",
    temperature=0,
    max_tokens=8192,
    openai_api_key=os.getenv("OPENROUTER_API_KEY"),
    openai_api_base="https://openrouter.ai/api/v1",
    default_headers={"X-Title": "LostArk Chatbot"},
)

