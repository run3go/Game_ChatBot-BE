from fastapi import FastAPI, Depends, Body, HTTPException, BackgroundTasks, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from typing import Optional
import json
import logging
import os

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

from database import get_db, SessionLocal
from service.ai_service import AIService
from service.airflow_service import AirflowManager, CharacterRequest
from service.nickname_service import load_nicknames
from service.chat_service import ChatService, run_background_save, generate_title
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

@app.post("/users")
def register_user(
    user_id: str = Body(..., embed=True),
    db: Session = Depends(get_db),
):
    db.execute(
        text("""
            INSERT INTO public.user_info_tb (user_id)
            VALUES (:user_id)
            ON CONFLICT (user_id) DO UPDATE SET last_accessed_at = CURRENT_TIMESTAMP
        """),
        {"user_id": user_id},
    )
    db.commit()
    return {"user_id": user_id}


@app.post("/chat/sessions")
def create_chat_session(
    user_id: str = Body(..., embed=True),
    db: Session = Depends(get_db),
):
    chat_id = ChatService(db).create_session(user_id)
    return {"chat_id": chat_id}


@app.get("/chat/sessions")
def get_chat_sessions(
    user_id: str = Query(...),
    db: Session = Depends(get_db),
):
    return ChatService(db).get_sessions(user_id)


@app.delete("/chat/sessions/{chat_id}")
def delete_chat_session(
    chat_id: str,
    user_id: str = Query(...),
    db: Session = Depends(get_db),
):
    svc = ChatService(db)
    if not svc.verify_ownership(chat_id, user_id):
        raise HTTPException(status_code=403, detail="접근 권한이 없습니다.")
    svc.delete_session(chat_id)
    return {"ok": True}


@app.get("/chat/sessions/{chat_id}/messages")
def get_chat_messages(
    chat_id: str,
    user_id: str = Query(...),
    db: Session = Depends(get_db),
):
    svc = ChatService(db)
    if not svc.verify_ownership(chat_id, user_id):
        raise HTTPException(status_code=403, detail="접근 권한이 없습니다.")
    return svc.get_recent_messages(chat_id)


@app.post("/ask/stream")
def ask_ai_stream(
    background_tasks: BackgroundTasks,
    question: str = Body(...),
    chat_id: Optional[str] = Body(default=None),
    user_id: Optional[str] = Body(default=None),
    db: Session = Depends(get_db),
):
    history = None
    is_first_message = False

    if chat_id and user_id:
        svc = ChatService(db)
        if not svc.verify_ownership(chat_id, user_id):
            raise HTTPException(status_code=403, detail="접근 권한이 없습니다.")
        recent = svc.get_recent_messages(chat_id)
        is_first_message = len(recent) == 0
        summary = svc.get_summary(chat_id)
        history = ([{"role": "summary", "content": summary}] if summary else []) + recent

    ai_service = AIService(llm, db)
    answer_parts: list[str] = []
    structured_result: list = []
    generated_title: list[str] = []

    def generate():
        result = None
        result_text = None
        try:
            for event_type, event_data in ai_service.ask(question, history):
                if event_type == "status":
                    yield f"data: {json.dumps({'type': 'status', 'content': event_data})}\n\n"
                elif event_type == "result":
                    result = event_data
                elif event_type == "result_text":
                    result_text = event_data
        except Exception:
            yield f"data: {json.dumps({'type': 'error', 'content': '잠시 후 다시 시도해 주세요.'})}\n\n"
            yield "data: [DONE]\n\n"
            return

        try:
            if isinstance(result, dict) and result.get("ui_type") == "CONFIRM_COLLECT":
                msg = result['message']
                answer_parts.append(msg)
                yield f"data: {json.dumps({'type': 'text', 'content': msg})}\n\n"
                yield f"data: {json.dumps({'type': 'confirm_collect', 'nickname': result['nickname']})}\n\n"
            elif isinstance(result, dict):
                structured_result.append(result)
                yield f"data: {json.dumps({'type': 'structured', 'payload': result})}\n\n"
                for chunk in result_text or []:
                    if chunk:
                        answer_parts.append(chunk)
                        yield f"data: {json.dumps({'type': 'text', 'content': chunk})}\n\n"
            else:
                for chunk in result or []:
                    if chunk:
                        answer_parts.append(chunk)
                        yield f"data: {json.dumps({'type': 'text', 'content': chunk})}\n\n"
        except Exception:
            yield f"data: {json.dumps({'type': 'error', 'content': '잠시 후 다시 시도해 주세요.'})}\n\n"
        finally:
            if is_first_message and chat_id and user_id:
                try:
                    title = generate_title(question, llm)
                    generated_title.append(title)
                    yield f"data: {json.dumps({'type': 'title', 'content': title})}\n\n"
                except Exception:
                    pass
            yield "data: [DONE]\n\n"

    if chat_id and user_id:
        background_tasks.add_task(
            run_background_save,
            chat_id,
            question,
            answer_parts,
            structured_result,
            llm,
            is_first_message,
            generated_title,
        )

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        background=background_tasks,
    )

@app.post("/trigger-update")
def update_character_data(req: CharacterRequest):
    try:
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

@app.get("/dag-status/{run_id}")
def get_dag_status(run_id: str):
    try:
        status = airflow.get_dag_run_status("chatbot_response_processor", run_id)
        return {"status": status}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))