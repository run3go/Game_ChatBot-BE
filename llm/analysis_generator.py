import time
from langchain_core.prompts import ChatPromptTemplate
from output_types import LOSTARKAnalysis, TFTAnalysis, QuestionAnalysis
from prompts.game_knowledge import get_game_knowledge
from utils.chat_utils import format_history
from constants import DISPLAY_TRIGGERS
from llm.llm_monitor import log_llm_call, TokenCountCallback
from service.prompt_manager import PromptManager

_ANALYSIS_MODEL: dict = {
    "LOSTARK": LOSTARKAnalysis,
    "TFT": TFTAnalysis,
}


def _format_display_triggers() -> str:
    lines = []
    for category, words in DISPLAY_TRIGGERS.items():
        lines.append(f"        - {category}: {', '.join(sorted(words))}")
    return "\n".join(lines)


class AnalysisGenerator:
    def __init__(self, llm, prompt_manager: PromptManager):
        self.llm = llm
        self.prompt_manager = prompt_manager
        self.model_name = getattr(llm, "model_name", getattr(llm, "model", "unknown"))

    def analyze(self, question: str, history: list[dict] | None = None, candidates: list[str] | None = None, embedding_context: str = "", game_type: str = "LOSTARK") -> QuestionAnalysis:

        model = _ANALYSIS_MODEL.get(game_type, LOSTARKAnalysis)

        if "000" in question and (history is None or len(history) == 0):
            return model(
                nicknames=[],
                response_format="TEXT",
                category="GENERAL",
                reason="최초 질문에 '000' 플레이스홀더가 포함되어 재질문을 유도",
                reask_message="000을 닉네임으로 채워 다시 질문해주세요."
            )

        template = self.prompt_manager.build_analysis_template(game_type)
        prompt = ChatPromptTemplate.from_template(template)
        structured_llm = self.llm.with_structured_output(model)
        chain = (prompt | structured_llm).with_retry(stop_after_attempt=2)

        history_text = format_history(history, max_ai_length=200) if history else ""

        inputs = {
            "question": question,
            "history": history_text or "없음",
            "candidates": candidates or [],
            "game_knowledge": get_game_knowledge(game_type),
            "embedding_context": embedding_context or "없음",
            "display_triggers": _format_display_triggers(),
        }

        start_time = time.time()
        cb = TokenCountCallback()
        detail = {
            "input": {
                "embedding_context": embedding_context or "없음",
                "candidates": candidates or [],
            },
            "output": {},
        }

        try:
            result = chain.invoke(inputs, config={"callbacks": [cb]})

            if result is None:
                raise ValueError("질문 분석 결과가 없습니다.")

            detail["output"] = {
                "nicknames": result.nicknames,
                "response_format": result.response_format,
                "category": result.category,
                "reason": result.reason,
            }

            log_llm_call(
                generator_type="analysis",
                model_name=self.model_name,
                start_time=start_time,
                callback=cb,
                detail=detail,
            )
            return result

        except Exception as e:
            log_llm_call(
                generator_type="analysis",
                model_name=self.model_name,
                start_time=start_time,
                callback=cb,
                success=False,
                error_message=str(e),
                detail=detail,
            )
            raise
