import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI

from fastapi.middleware.cors import CORSMiddleware

from routers import airflow, ask, monitor, sessions, users

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    from utils.reranker import CROSS_ENCODER
    CROSS_ENCODER._get_model()
    yield
    logger.info("서버를 종료합니다.")


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001", "https://gamechatbotfe.vercel.app", "https://game.mumulbot.com"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(users.router)
app.include_router(sessions.router)
app.include_router(ask.router)
app.include_router(airflow.router)
app.include_router(monitor.router)
