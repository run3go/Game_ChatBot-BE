import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import SessionLocal
from routers import airflow, ask, sessions, users
from service.nickname_service import load_nicknames
from sql.schema_store import SCHEMA_STORE

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(_: FastAPI):
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

    print("서버를 종료합니다.")


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://gamechatbotfe.vercel.app"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(users.router)
app.include_router(sessions.router)
app.include_router(ask.router)
app.include_router(airflow.router)
