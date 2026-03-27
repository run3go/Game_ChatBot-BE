from fastapi import FastAPI, Depends
from fastapi.responses import StreamingResponse
from fastapi import Body
from sqlalchemy.orm import Session
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from typing import Optional
import json

from database import get_db, SessionLocal
from service.ai_service import AIService
from service.nickname_service import load_nicknames, NICKNAME_SET
from sql.schema_store import SCHEMA_STORE

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
        length = load_nicknames(db)
        print(f"성공적으로 {length}개의 닉네임을 로드했습니다.")
    except Exception as e:
        print(f"닉네임 로드 중 오류 발생: {e}")

    try:
        count = SCHEMA_STORE.load(db)
        print(f"성공적으로 {count}개의 테이블 스키마를 벡터스토어에 로드했습니다.")
    except Exception as e:
        print(f"스키마 벡터스토어 로드 중 오류 발생: {e}")
        
    finally:
        db.close()

    yield

    # SHUTDOWN
    print("서버를 종료합니다.")

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"]
)

@app.post("/ask/stream")
def ask_ai_stream(
    question: str = Body(...),
    history: Optional[list[dict]] = Body(default=None),
    pending: Optional[dict] = Body(default=None),
    db: Session = Depends(get_db),
):
    service = AIService(llm, db)
    result = service.ask(question, pending, history)

    def generate():
        if isinstance(result, dict):
            yield f"data: {json.dumps({'type': 'structured', 'payload': result})}\n\n"
        else:
            for chunk in result:
                if chunk:
                    yield f"data: {json.dumps({'type': 'text', 'content': chunk})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )