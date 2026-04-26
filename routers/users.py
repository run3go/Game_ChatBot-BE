from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_db

router = APIRouter()


@router.post("/users")
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


@router.get("/users/call-count")
def get_call_count(
    user_id: str = Query(...),
    db: Session = Depends(get_db),
):
    row = db.execute(
        text("SELECT remaining_call_count FROM public.user_info_tb WHERE user_id = :user_id"),
        {"user_id": user_id},
    ).first()
    return {"call_count": row[0] if row else 0}


@router.get("/users/recent-nickname")
def get_recent_nickname(
    user_id: str = Query(...),
    db: Session = Depends(get_db),
):
    row = db.execute(
        text("""
            SELECT cm.nicknames[1] AS nickname
            FROM public.chat_messages_tb cm
            JOIN public.chat_sessions_tb cs ON cm.chat_id = cs.chat_id
            WHERE cs.user_id = :user_id
              AND cm.nicknames IS NOT NULL
              AND array_length(cm.nicknames, 1) > 0
            ORDER BY cm.created_at DESC
            LIMIT 1
        """),
        {"user_id": user_id},
    ).first()
    return {"nickname": row[0] if row else None}
