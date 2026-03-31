from fastapi import FastAPI, Depends, Body, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from typing import Optional
import json
import os

from database import get_db, SessionLocal
from service.ai_service import AIService
from service.airflow_service import AirflowManager, CharacterRequest
from service.nickname_service import load_nicknames
from sql.schema_store import SCHEMA_STORE

load_dotenv()

airflow = AirflowManager()


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
    allow_origins=["http://localhost:3000", "https://gamechatbotfe.vercel.app"],
    allow_methods=["*"],
    allow_headers=["*"]
)

@app.post("/ask/stream")
def ask_ai_stream(
    question: str = Body(...),
    history: Optional[list[dict]] = Body(default=None),
    db: Session = Depends(get_db),
):
    service = AIService(llm, db)

    def generate():
        result = None
        try:
            for event_type, event_data in service.ask(question, history):
                if event_type == "status":
                    yield f"data: {json.dumps({'type': 'status', 'content': event_data})}\n\n"
                else:
                    result = event_data
        except Exception:
            yield f"data: {json.dumps({'type': 'error', 'content': '잠시 후 다시 시도해 주세요.'})}\n\n"
            yield "data: [DONE]\n\n"
            return

        try:
            if isinstance(result, dict) and result.get("ui_type") == "CONFIRM_COLLECT":
                yield f"data: {json.dumps({'type': 'text', 'content': result['message']})}\n\n"
                yield f"data: {json.dumps({'type': 'confirm_collect', 'nickname': result['nickname']})}\n\n"
            elif isinstance(result, dict):
                yield f"data: {json.dumps({'type': 'structured', 'payload': result})}\n\n"
            else:
                for chunk in result or []:
                    if chunk:
                        yield f"data: {json.dumps({'type': 'text', 'content': chunk})}\n\n"
        except Exception:
            yield f"data: {json.dumps({'type': 'error', 'content': '잠시 후 다시 시도해 주세요.'})}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

@app.post("/trigger-update")
def update_character_data(req: CharacterRequest):
    try:
        # 백엔드 로직 실행
        result = airflow.trigger_dag(
            dag_id="chatbot_response_processor",
            conf={"character_name": req.character_name, "request_source": "fastapi"},
        )

        if result.status_code in [200, 201, 202]:
            return {"status": "success", "run_id": result.json().get("dag_run_id")}
        else:
            raise HTTPException(status_code=result.status_code, detail=result.text)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))