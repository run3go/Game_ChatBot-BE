import json
import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from utils.llm import llm, llm_answer, llm_sql
from database import get_db
from service.ai_service import AIService
from service.chat_service import ChatService, run_background_save

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/ask/stream")
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

    ai_service = AIService(llm, db, llm_sql=llm_sql, llm_answer=llm_answer)
    answer_parts: list[str] = []
    structured_result: list = []
    generated_title: list[str] = []
    resolved_nicknames: list[str] = []
    generated_sql: list[str] = []

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
                elif event_type == "nicknames":
                    resolved_nicknames[:] = event_data
                elif event_type == "sql":
                    generated_sql[:] = [event_data]
        except Exception:
            yield f"data: {json.dumps({'type': 'error', 'content': '잠시 후 다시 시도해 주세요.'})}\n\n"
            yield "data: [DONE]\n\n"
            return

        try:
            if isinstance(result, dict) and result.get("ui_type") == "CONFIRM_COLLECT":
                msg = result["message"]
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
                    title = ChatService.generate_title(question, llm)
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
            resolved_nicknames,
            generated_sql,
        )

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        background=background_tasks,
    )
