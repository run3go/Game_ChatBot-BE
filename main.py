from dotenv import load_dotenv

load_dotenv()

import logging
from contextlib import asynccontextmanager
from llm.factory import create_llm_instances

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import airflow, ask, monitor, sessions, users
from service.prompt_manager import PromptManager
from llm.sql_generator import SQLGenerator
from llm.analysis_generator import AnalysisGenerator
from llm.answer_generator import AnswerGenerator
from llm.game_detector import GameDetector

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from utils.reranker import CROSS_ENCODER

    CROSS_ENCODER._get_model()

    llms = create_llm_instances()

    pm = PromptManager()

    sql_gen = SQLGenerator(llm=llms["sql"], prompt_manager=pm)
    analysis_gen = AnalysisGenerator(llm=llms["analyze"], prompt_manager=pm)
    answer_gen = AnswerGenerator(llm=llms["answer"])
    game_detector = GameDetector(llm=llms["analyze"])

    app.state.llms = llms
    app.state.pm = pm
    app.state.sql_gen = sql_gen
    app.state.analysis_gen = analysis_gen
    app.state.answer_gen = answer_gen
    app.state.game_detector = game_detector

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
