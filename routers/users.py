from fastapi import APIRouter, Body, Depends
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
