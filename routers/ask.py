import json
import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_db
from service.ai_service import AIService
from service.chat_service import ChatService, run_background_save
from llm.game_detector import (
    GameDetector,
    GAME_NAMES,
    is_game_switch_reask,
    extract_game_from_reask,
    is_affirmative,
    quick_detect,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def get_ai_service(request: Request, db: Session = Depends(get_db)):
    return AIService(
        db=db,
        sql_generator=request.app.state.sql_gen,
        analysis_generator=request.app.state.analysis_gen,
        answer_generator=request.app.state.answer_gen,
    )


@router.post("/ask/stream")
async def ask_ai_stream(
    request: Request,
    background_tasks: BackgroundTasks,
    question: str = Body(...),
    chat_id: Optional[str] = Body(default=None),
    user_id: Optional[str] = Body(default=None),
    db: Session = Depends(get_db),
    ai_service: AIService = Depends(get_ai_service),
):
    history = None
    is_first_message = False
    reask_message: str | None = None

    if chat_id and user_id:
        svc = ChatService(db)
        if not svc.verify_ownership(chat_id, user_id):
            raise HTTPException(status_code=403, detail="접근 권한이 없습니다.")
        recent = svc.get_recent_messages(chat_id)
        is_first_message = len(recent) == 0
        summary = svc.get_summary(chat_id)
        history = ([{"role": "summary", "content": summary}] if summary else []) + recent

        game_detector: GameDetector = request.app.state.game_detector
        game_type = svc.get_game_type(chat_id)

        if history and is_game_switch_reask(history):
            # 직전 AI 메시지가 게임 전환 재질문이었던 경우
            if is_affirmative(question):
                new_game = extract_game_from_reask(history)
                if new_game != "UNKNOWN":
                    svc.update_game_type(chat_id, new_game)
                    game_type = new_game
        else:
            if game_type is None:
                # 첫 질문 — 키워드/패턴으로 먼저 시도, 불명확하면 LLM으로 확정
                detected = quick_detect(question) or game_detector.detect(question)
                if detected != "UNKNOWN":
                    svc.update_game_type(chat_id, detected)
                    game_type = detected
            else:
                # 게임 이미 확정 — 키워드 체크 후 다른 게임일 때만 LLM 호출
                quick = quick_detect(question)
                if quick is not None and quick != game_type:
                    detected = game_detector.detect(question)
                    if detected != "UNKNOWN" and detected != game_type:
                        reask_message = f"혹시 {GAME_NAMES[detected]} 관련 질문인가요?"

    if user_id:
        row = db.execute(
            text("""
                UPDATE public.user_info_tb
                SET remaining_call_count = remaining_call_count + 1
                WHERE user_id = :user_id AND remaining_call_count < 50
                RETURNING remaining_call_count
            """),
            {"user_id": user_id},
        ).first()
        db.commit()

        if row is None:
            raise HTTPException(status_code=429, detail="오늘의 질문 횟수를 모두 사용했어요.")

    answer_parts: list[str] = []
    structured_result: list = []
    generated_title: list[str] = []
    resolved_nicknames: list[str] = []
    generated_sql: list[str] = []

    async def generate():
        result = None
        result_text = None

        # 게임 전환 재질문
        if reask_message:
            answer_parts.append(reask_message)
            yield f"data: {json.dumps({'type': 'text', 'content': reask_message})}\n\n"
            yield "data: [DONE]\n\n"
            return

        try:
            for event_type, event_data in ai_service.ask(question, history, game_type=game_type or "UNKNOWN"):
                if await request.is_disconnected():
                    logger.info("클라이언트 연결 끊김 (chat_id=%s)", chat_id)
                    return
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
                elif event_type == "data_updated_at":
                    yield f"data: {json.dumps({'type': 'data_updated_at', 'value': event_data})}\n\n"
        except Exception:
            logger.exception("SSE 스트리밍 오류 (chat_id=%s)", chat_id)
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
                yield f"data: {json.dumps({'type': 'structured', 'payload': jsonable_encoder(result)})}\n\n"
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
            logger.exception("결과 직렬화 오류 (chat_id=%s)", chat_id)
            yield f"data: {json.dumps({'type': 'error', 'content': '잠시 후 다시 시도해 주세요.'})}\n\n"
        finally:
            yield "data: [DONE]\n\n"
            if is_first_message and chat_id and user_id:
                try:
                    title = ChatService.generate_title(question, request.app.state.llms["answer"])
                    generated_title.append(title)
                    yield f"data: {json.dumps({'type': 'title', 'content': title})}\n\n"
                except Exception:
                    pass

    if chat_id and user_id:
        background_tasks.add_task(
            run_background_save,
            chat_id,
            question,
            answer_parts,
            structured_result,
            request.app.state.llms["answer"],
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
