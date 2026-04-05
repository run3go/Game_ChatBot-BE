from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from service.chat_service import ChatService

router = APIRouter(prefix="/chat")


@router.post("/sessions")
def create_chat_session(
    user_id: str = Body(..., embed=True),
    db: Session = Depends(get_db),
):
    chat_id = ChatService(db).create_session(user_id)
    return {"chat_id": chat_id}


@router.get("/sessions")
def get_chat_sessions(
    user_id: str = Query(...),
    db: Session = Depends(get_db),
):
    return ChatService(db).get_sessions(user_id)


@router.delete("/sessions/{chat_id}")
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


@router.get("/sessions/{chat_id}/messages")
def get_chat_messages(
    chat_id: str,
    user_id: str = Query(...),
    db: Session = Depends(get_db),
):
    svc = ChatService(db)
    if not svc.verify_ownership(chat_id, user_id):
        raise HTTPException(status_code=403, detail="접근 권한이 없습니다.")
    return svc.get_recent_messages(chat_id)
