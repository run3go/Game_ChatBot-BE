from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from database import get_db
from service.ai_service import AIService

import os

load_dotenv()
app = FastAPI()

llm = ChatOpenAI(
  model="openai/gpt-4o", 
  temperature=0,
  openai_api_key= os.getenv("OPENROUTER_API_KEY"), 
  openai_api_base="https://openrouter.ai/api/v1",
  default_headers={
    "X-Title": "LostArk Chatbot"
  })

@app.get("/ask")
def ask_ai(question: str, db: Session = Depends(get_db)):

    service = AIService(llm)

    result = service.ask(question, db)

    return {"result": result}