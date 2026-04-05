import uuid
import json
import logging
from sqlalchemy.orm import Session
from sqlalchemy import text
from langchain_core.prompts import ChatPromptTemplate
from database import SessionLocal

logger = logging.getLogger(__name__)

HISTORY_LIMIT = 10


class ChatService:

    def __init__(self, db: Session):
        self.db = db

    def create_session(self, user_id: str) -> str:
        chat_id = str(uuid.uuid4())
        self.db.execute(
            text("INSERT INTO public.chat_sessions_tb (chat_id, user_id) VALUES (:chat_id, :user_id)"),
            {"chat_id": chat_id, "user_id": user_id},
        )
        self.db.commit()
        return chat_id

    def get_sessions(self, user_id: str) -> list:
        rows = self.db.execute(
            text("""
                SELECT cs.chat_id, cs.title, cs.created_at
                FROM public.chat_sessions_tb cs
                LEFT JOIN (
                    SELECT chat_id, MAX(created_at) AS last_msg_at
                    FROM public.chat_messages_tb
                    GROUP BY chat_id
                ) lm ON cs.chat_id = lm.chat_id
                WHERE cs.user_id = :user_id
                ORDER BY COALESCE(lm.last_msg_at, cs.created_at) DESC
            """),
            {"user_id": user_id},
        ).mappings().all()
        return [
            {
                "chat_id": r["chat_id"],
                "title": r["title"] or "새 대화",
                "created_at": r["created_at"].isoformat(),
            }
            for r in rows
        ]

    def verify_ownership(self, chat_id: str, user_id: str) -> bool:
        row = self.db.execute(
            text("SELECT 1 FROM public.chat_sessions_tb WHERE chat_id = :chat_id AND user_id = :user_id"),
            {"chat_id": chat_id, "user_id": user_id},
        ).first()
        return row is not None

    def get_recent_messages(self, chat_id: str) -> list[dict]:
        rows = self.db.execute(
            text("""
                SELECT role, content, result_json FROM (
                    SELECT role, content, result_json, created_at
                    FROM public.chat_messages_tb
                    WHERE chat_id = :chat_id
                    ORDER BY created_at DESC
                    LIMIT :limit
                ) sub ORDER BY created_at ASC
            """),
            {"chat_id": chat_id, "limit": HISTORY_LIMIT},
        ).mappings().all()
        return [{"role": r["role"], "content": r["content"], "result_json": r["result_json"]} for r in rows]

    def get_summary(self, chat_id: str) -> str | None:
        row = self.db.execute(
            text("SELECT summary FROM public.chat_sessions_tb WHERE chat_id = :chat_id"),
            {"chat_id": chat_id},
        ).first()
        return row[0] if row else None

    def save_message(self, chat_id: str, role: str, content: str, result_json: dict | None = None):
        self.db.execute(
            text("INSERT INTO public.chat_messages_tb (msg_id, chat_id, role, content, result_json) VALUES (:msg_id, :chat_id, :role, :content, CAST(:result_json AS jsonb))"),
            {
                "msg_id": str(uuid.uuid4()),
                "chat_id": chat_id,
                "role": role,
                "content": content,
                "result_json": json.dumps(result_json) if result_json is not None else None,
            },
        )
        self.db.commit()

    def delete_session(self, chat_id: str):
        self.db.execute(
            text("DELETE FROM public.chat_messages_tb WHERE chat_id = :chat_id"),
            {"chat_id": chat_id},
        )
        self.db.execute(
            text("DELETE FROM public.chat_sessions_tb WHERE chat_id = :chat_id"),
            {"chat_id": chat_id},
        )
        self.db.commit()

    def set_title_if_empty(self, chat_id: str, title: str):
        self.db.execute(
            text("UPDATE public.chat_sessions_tb SET title = :title WHERE chat_id = :chat_id AND title IS NULL"),
            {"title": title, "chat_id": chat_id},
        )
        self.db.commit()

    def get_message_count(self, chat_id: str) -> int:
        row = self.db.execute(
            text("SELECT COUNT(*) FROM public.chat_messages_tb WHERE chat_id = :chat_id"),
            {"chat_id": chat_id},
        ).first()
        return row[0]

    def update_summary(self, chat_id: str, llm):
        total = self.get_message_count(chat_id)
        if total <= HISTORY_LIMIT:
            return

        rows = self.db.execute(
            text("""
                SELECT role, content FROM public.chat_messages_tb
                WHERE chat_id = :chat_id
                ORDER BY created_at ASC
                LIMIT :limit
            """),
            {"chat_id": chat_id, "limit": total - HISTORY_LIMIT},
        ).mappings().all()

        history_text = "\n".join(
            f"{'사용자' if r['role'] == 'user' else 'AI'}: {r['content']}"
            for r in rows
        )

        prompt = ChatPromptTemplate.from_template("""
            다음은 로스트아크 게임 챗봇의 대화 내용이야.
            핵심만 3~5문장으로 한국어 요약을 작성해.
            어떤 캐릭터에 대해 어떤 정보를 물었는지를 중심으로 정리해.

            [대화]
            {history}
        """)

        try:
            result = (prompt | llm).invoke({"history": history_text})
            self.db.execute(
                text("UPDATE public.chat_sessions_tb SET summary = :summary WHERE chat_id = :chat_id"),
                {"summary": result.content, "chat_id": chat_id},
            )
            self.db.commit()
        except Exception:
            logger.exception("요약 생성 실패 (chat_id=%s)", chat_id)


def generate_title(question: str, llm=None) -> str:
    if not llm or len(question) <= 10:
        return question[:10]

    prompt = ChatPromptTemplate.from_template("""
        다음은 로스트아크 게임 챗봇에 대한 사용자의 첫 질문이야.
        5~10글자로 간단한 제목을 만들어줘. 마침표나 특수문자는 빼줘.

        [질문]
        {question}
    """)

    try:
        result = (prompt | llm).invoke({"question": question})
        return result.content.strip()[:50]
    except Exception:
        logger.exception("제목 생성 실패, 원본 질문으로 설정")
        return question[:50]


def run_background_save(
    chat_id: str,
    question: str,
    answer_parts: list[str],
    structured_result: list,
    llm,
    is_first_message: bool,
    generated_title: list[str],
):
    db = SessionLocal()
    try:
        svc = ChatService(db)
        svc.save_message(chat_id, "user", question)
        answer_text = "".join(answer_parts)
        result_json = structured_result[0] if structured_result else None
        if answer_text or result_json:
            svc.save_message(chat_id, "assistant", answer_text, result_json)
        if is_first_message and generated_title:
            svc.set_title_if_empty(chat_id, generated_title[0])
        svc.update_summary(chat_id, llm)
    except Exception:
        logger.exception("백그라운드 메시지 저장 실패 (chat_id=%s)", chat_id)
    finally:
        db.close()
