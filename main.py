from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from contextlib import asynccontextmanager

from database import get_db, SessionLocal
from service.ai_service import AIService
from service.nickname_service import load_nicknames, NICKNAME_SET

import os

load_dotenv()

llm = ChatOpenAI(
  model="openai/gpt-4o", 
  temperature=0,
  openai_api_key= os.getenv("OPENROUTER_API_KEY"), 
  openai_api_base="https://openrouter.ai/api/v1",
  default_headers={
    "X-Title": "LostArk Chatbot"
  })

@asynccontextmanager
async def lifespan(_: FastAPI):
    # STARTUP
    db = SessionLocal()

    try:
        load_nicknames(db)
        print(f"성공적으로 {len(NICKNAME_SET)}개의 닉네임을 로드했습니다.")
    except Exception as e:
        print(f"닉네임 로드 중 오류 발생: {e}")
    finally:
        db.close()

    yield

    # SHUTDOWN
    print("서버를 종료합니다.")

app = FastAPI(lifespan=lifespan)

@app.get("/ask")
def ask_ai(question: str, db: Session = Depends(get_db)):

    service = AIService(llm, db)
    result = service.ask(question)

    return {"result": result}