import time
import threading
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from langchain_core.callbacks import BaseCallbackHandler

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))


class TokenCountCallback(BaseCallbackHandler):
    """LLM 호출 시 토큰 사용량을 캡처하는 콜백"""

    def __init__(self):
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0

    def on_llm_end(self, response, **kwargs):
        for gen_list in response.generations:
            for gen in gen_list:
                # 1) 메시지의 usage_metadata (LangChain 표준, 스트리밍 포함)
                msg = getattr(gen, "message", None)
                usage_meta = getattr(msg, "usage_metadata", None) if msg else None
                if usage_meta:
                    self.prompt_tokens += usage_meta.get("input_tokens", 0)
                    self.completion_tokens += usage_meta.get("output_tokens", 0)
                    self.total_tokens += usage_meta.get("total_tokens", 0)
                    continue

                # 2) generation_info (비스트리밍 응답)
                meta = getattr(gen, "generation_info", {}) or {}
                usage = meta.get("token_usage") or meta.get("usage") or {}
                if usage:
                    self.prompt_tokens += usage.get("prompt_tokens", 0)
                    self.completion_tokens += usage.get("completion_tokens", 0)
                    self.total_tokens += usage.get("total_tokens", 0)

        # 3) llm_output 레벨 (일부 provider는 여기에 넣음)
        if not self.total_tokens and response.llm_output:
            usage = response.llm_output.get("token_usage") or response.llm_output.get("usage") or {}
            self.prompt_tokens = usage.get("prompt_tokens", 0)
            self.completion_tokens = usage.get("completion_tokens", 0)
            self.total_tokens = usage.get("total_tokens", 0)


# OpenRouter 모델별 가격 ($ per token)
# https://openrouter.ai/api/v1/models 에서 조회
MODEL_PRICING: dict[str, dict[str, float]] = {
    "meta-llama/llama-3.3-70b-instruct": {
        "prompt": 0.0000001,      # $0.10 / 1M tokens
        "completion": 0.00000032,  # $0.32 / 1M tokens
    },
}

# 기본 가격 (등록되지 않은 모델용)
DEFAULT_PRICING = {"prompt": 0.0, "completion": 0.0}


def calc_cost(model_name: str, prompt_tokens: int, completion_tokens: int) -> dict:
    """토큰 수와 모델 가격으로 비용 계산 (USD)"""
    pricing = MODEL_PRICING.get(model_name, DEFAULT_PRICING)
    prompt_cost = prompt_tokens * pricing["prompt"]
    completion_cost = completion_tokens * pricing["completion"]
    total_cost = prompt_cost + completion_cost
    return {
        "prompt_cost": prompt_cost,
        "completion_cost": completion_cost,
        "total_cost": total_cost,
    }


@dataclass
class LLMLog:
    timestamp: str
    generator_type: str  # "analysis" | "sql" | "answer"
    model_name: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0
    success: bool = True
    error_message: str = ""
    retry_count: int = 0
    prompt_cost: float = 0.0
    completion_cost: float = 0.0
    total_cost: float = 0.0
    # generator별 상세 정보
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        # 소수점 10자리까지 유지 (미세 비용 표시)
        d["prompt_cost"] = round(self.prompt_cost, 10)
        d["completion_cost"] = round(self.completion_cost, 10)
        d["total_cost"] = round(self.total_cost, 10)
        return d


class LLMMonitor:
    """인메모리 LLM 호출 로그 저장소 (싱글톤)"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._logs: list[LLMLog] = []
                    cls._instance._log_lock = threading.Lock()
                    cls._instance._max_logs = 1000
        return cls._instance

    def add_log(self, log: LLMLog):
        with self._log_lock:
            self._logs.append(log)
            if len(self._logs) > self._max_logs:
                self._logs = self._logs[-self._max_logs:]

    def get_logs(
        self,
        generator_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        with self._log_lock:
            filtered = self._logs
            if generator_type:
                filtered = [l for l in filtered if l.generator_type == generator_type]
            # 최신순
            filtered = list(reversed(filtered))
            return [l.to_dict() for l in filtered[offset : offset + limit]]

    def get_summary(self) -> dict:
        with self._log_lock:
            if not self._logs:
                return {
                    "total_calls": 0,
                    "total_prompt_tokens": 0,
                    "total_completion_tokens": 0,
                    "total_tokens": 0,
                    "avg_latency_ms": 0,
                    "error_rate": 0,
                    "total_prompt_cost": 0.0,
                    "total_completion_cost": 0.0,
                    "total_cost": 0.0,
                    "by_generator": {},
                }

            total = len(self._logs)
            errors = sum(1 for l in self._logs if not l.success)
            total_prompt = sum(l.prompt_tokens for l in self._logs)
            total_completion = sum(l.completion_tokens for l in self._logs)
            total_tokens = sum(l.total_tokens for l in self._logs)
            avg_latency = sum(l.latency_ms for l in self._logs) / total
            total_prompt_cost = sum(l.prompt_cost for l in self._logs)
            total_completion_cost = sum(l.completion_cost for l in self._logs)
            total_cost = sum(l.total_cost for l in self._logs)

            by_gen: dict[str, dict] = {}
            for l in self._logs:
                g = l.generator_type
                if g not in by_gen:
                    by_gen[g] = {
                        "calls": 0,
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0,
                        "total_latency_ms": 0,
                        "errors": 0,
                        "prompt_cost": 0.0,
                        "completion_cost": 0.0,
                        "total_cost": 0.0,
                    }
                by_gen[g]["calls"] += 1
                by_gen[g]["prompt_tokens"] += l.prompt_tokens
                by_gen[g]["completion_tokens"] += l.completion_tokens
                by_gen[g]["total_tokens"] += l.total_tokens
                by_gen[g]["total_latency_ms"] += l.latency_ms
                by_gen[g]["prompt_cost"] += l.prompt_cost
                by_gen[g]["completion_cost"] += l.completion_cost
                by_gen[g]["total_cost"] += l.total_cost
                if not l.success:
                    by_gen[g]["errors"] += 1

            for g in by_gen:
                c = by_gen[g]["calls"]
                by_gen[g]["avg_latency_ms"] = round(by_gen[g]["total_latency_ms"] / c)
                by_gen[g]["error_rate"] = round(by_gen[g]["errors"] / c * 100, 1)
                by_gen[g]["prompt_cost"] = round(by_gen[g]["prompt_cost"], 10)
                by_gen[g]["completion_cost"] = round(by_gen[g]["completion_cost"], 10)
                by_gen[g]["total_cost"] = round(by_gen[g]["total_cost"], 10)

            return {
                "total_calls": total,
                "total_prompt_tokens": total_prompt,
                "total_completion_tokens": total_completion,
                "total_tokens": total_tokens,
                "avg_latency_ms": round(avg_latency),
                "error_rate": round(errors / total * 100, 1),
                "total_prompt_cost": round(total_prompt_cost, 10),
                "total_completion_cost": round(total_completion_cost, 10),
                "total_cost": round(total_cost, 10),
                "by_generator": by_gen,
            }

    def get_recent_stats(self, hours: int = 24) -> list[dict]:
        """시간대별 통계 반환"""
        now = datetime.now(KST)
        cutoff = now - timedelta(hours=hours)

        with self._log_lock:
            recent = [
                l for l in self._logs
                if datetime.fromisoformat(l.timestamp) >= cutoff
            ]

        # 시간대별 그룹핑
        buckets: dict[str, dict] = {}
        for l in recent:
            hour_key = datetime.fromisoformat(l.timestamp).strftime("%Y-%m-%d %H:00")
            if hour_key not in buckets:
                buckets[hour_key] = {
                    "hour": hour_key,
                    "calls": 0,
                    "tokens": 0,
                    "cost": 0.0,
                    "errors": 0,
                    "total_latency": 0,
                }
            buckets[hour_key]["calls"] += 1
            buckets[hour_key]["tokens"] += l.total_tokens
            buckets[hour_key]["cost"] += l.total_cost
            if not l.success:
                buckets[hour_key]["errors"] += 1
            buckets[hour_key]["total_latency"] += l.latency_ms

        result = []
        for b in sorted(buckets.values(), key=lambda x: x["hour"]):
            b["avg_latency_ms"] = round(b["total_latency"] / b["calls"]) if b["calls"] else 0
            b["cost"] = round(b["cost"], 10)
            del b["total_latency"]
            result.append(b)
        return result

    def clear(self):
        with self._log_lock:
            self._logs.clear()


# 싱글톤 인스턴스
monitor = LLMMonitor()


def log_llm_call(
    generator_type: str,
    model_name: str,
    start_time: float,
    callback: TokenCountCallback | None = None,
    success: bool = True,
    error_message: str = "",
    retry_count: int = 0,
    detail: dict | None = None,
):
    latency_ms = int((time.time() - start_time) * 1000)

    prompt_tokens = callback.prompt_tokens if callback else 0
    completion_tokens = callback.completion_tokens if callback else 0
    total_tokens = callback.total_tokens if callback else 0

    cost = calc_cost(model_name, prompt_tokens, completion_tokens)

    log = LLMLog(
        timestamp=datetime.now(KST).isoformat(),
        generator_type=generator_type,
        model_name=model_name,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        latency_ms=latency_ms,
        success=success,
        error_message=error_message,
        retry_count=retry_count,
        prompt_cost=cost["prompt_cost"],
        completion_cost=cost["completion_cost"],
        total_cost=cost["total_cost"],
        detail=detail or {},
    )
    monitor.add_log(log)
    logger.info(
        "LLM [%s] %s tokens=%d latency=%dms",
        generator_type,
        "OK" if success else "FAIL",
        log.total_tokens,
        latency_ms,
    )
    return log
