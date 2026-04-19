# LLM 모니터링 시스템

## 1. 개요

챗봇이 LLM(OpenRouter / Llama 3.3 70B)을 호출할 때마다 **토큰 사용량 · 비용 · 레이턴시 · 에러 · 입출력 상세**를 기록하고, 웹 대시보드(`/monitor`)에서 실시간으로 확인할 수 있는 시스템입니다.

- **목적**: 어떤 Generator가 토큰·비용을 얼마나 쓰는지, 어느 단계에서 레이턴시·실패가 발생하는지 가시화
- **저장**: 인메모리 싱글톤 (최대 1,000건, 프로세스 재시작 시 초기화)
- **갱신**: FE가 10초마다 polling

## 2. 구성

### Backend (`Game_ChatBot-BE`)
| 파일 | 역할 |
|---|---|
| `llm/llm_monitor.py` | 로그 저장소 + 콜백 + 비용 계산 (핵심) |
| `routers/monitor.py` | `/monitor/summary`, `/logs`, `/stats` API |
| `llm/analysis_generator.py` | 질문 분석 LLM — 로그 남김 |
| `llm/sql_generator.py` | SQL 생성 LLM — 로그 남김 |
| `llm/answer_generator.py` | 답변 생성(스트리밍) LLM — 로그 남김 |
| `core/llm.py` | ChatOpenAI 공용 인스턴스 |

### Frontend (`Game_ChatBot-FE/src`)
| 파일 | 역할 |
|---|---|
| `app/monitor/page.tsx` | 모니터링 페이지 (10초 자동 새로고침 + 필터) |
| `components/monitor/SummaryCards.tsx` | 전체 호출/토큰/비용/에러율 요약 카드 |
| `components/monitor/GeneratorTable.tsx` | Generator별 통계 테이블 |
| `components/monitor/HourlyChart.tsx` | 시간대별 호출/비용 차트 |
| `components/monitor/LogTable.tsx` | 개별 호출 로그 (확장 시 상세 입출력 표시) |
| `lib/apis/monitor.ts`, `types/monitor.ts` | API 클라이언트 + 타입 |

## 3. 핵심 컴포넌트 — `llm_monitor.py`

### 3-1. `TokenCountCallback` (LangChain BaseCallbackHandler)
LLM 호출 완료 시 응답에서 토큰 수를 추출합니다. 세 가지 경로를 순서대로 시도:

1. **`message.usage_metadata`** — LangChain 표준 필드 (스트리밍 포함)
2. **`generation_info.token_usage`** — 비스트리밍 응답
3. **`response.llm_output.token_usage`** — 일부 provider fallback

### 3-2. `LLMLog` (dataclass)
한 번의 호출에 대한 스냅샷 — timestamp, generator_type, model, 토큰 3종, latency_ms, 성공 여부, 에러 메시지, 재시도 수, 비용 3종, 그리고 generator별 input/output 상세(`detail`).

### 3-3. `LLMMonitor` (싱글톤)
- `add_log()` — 스레드 안전하게 로그 추가 (최대 1000건 FIFO)
- `get_logs()` — 최신순 조회 + generator_type 필터 + pagination
- `get_summary()` — 전체 + Generator별 집계
- `get_recent_stats(hours)` — 시간대별 버킷 통계

### 3-4. `MODEL_PRICING` + `calc_cost()`
OpenRouter 가격표 기반 USD 비용 계산. 새 모델 추가 시 이 dict만 업데이트하면 됩니다.

### 3-5. `log_llm_call()` 헬퍼
각 Generator에서 호출하는 공용 진입점. `TokenCountCallback` → `LLMLog` 생성 → monitor에 저장.

## 4. 데이터 흐름

```
사용자 질문
  │
  ├─ AnalysisGenerator.analyze()      ← chain.invoke(callbacks=[cb])  → log_llm_call("analysis")
  │     → 카테고리·닉네임·response_format 추출
  │
  ├─ SQLGenerator.generate()          ← chain.invoke(callbacks=[cb])  → log_llm_call("sql")
  │     → SQL + UI 타입 생성
  │
  └─ AnswerGenerator.answer*()        ← chain.stream(callbacks=[cb])  → log_llm_call("answer")
        → 마크다운 답변 스트리밍

각 호출 → TokenCountCallback 이 토큰 캡처
       → log_llm_call 이 LLMLog 생성 + 비용 계산
       → LLMMonitor 싱글톤에 append

FE /monitor (10s polling)
  ↓
  GET /monitor/summary  → 대시보드 요약
  GET /monitor/logs     → 개별 호출 로그
  GET /monitor/stats    → 시간대별 차트
```

## 5. Generator별 호출 패턴

| Generator | 호출 방식 | 토큰 캡처 경로 |
|---|---|---|
| analysis | `chain.invoke()` (structured_output) | `generation_info.token_usage` |
| sql | `chain.invoke()` (structured_output) | `generation_info.token_usage` |
| answer | `chain.stream()` (스트리밍) | `message.usage_metadata` ← **이번 업데이트 포인트** |

## 6. 이번 업데이트 — Answer Generator 토큰 0 문제 해결

### 문제
모니터에서 **Answer Generator만 prompt/completion/total 토큰이 모두 0**으로 표시됨. (analysis, sql은 정상)

### 원인
Answer Generator는 스트리밍 방식(`chain.stream()`)을 사용하는데, **OpenAI 호환 API는 스트리밍 시 기본적으로 usage를 응답에 포함하지 않음**. 요청 시 `stream_options.include_usage=true`를 넘겨줘야 마지막 청크에 usage가 들어옵니다. 기존 콜백은 이 마지막 청크의 `usage_metadata`를 읽지 않고 `generation_info`만 확인하고 있어서 항상 0이었습니다.

### 수정

**`core/llm.py`** — 스트리밍 usage 활성화
```python
llm = ChatOpenAI(
    model="meta-llama/llama-3.3-70b-instruct",
    ...
    stream_usage=True,                                          # 추가
    model_kwargs={"stream_options": {"include_usage": True}},   # 추가
)
```

**`llm/llm_monitor.py`** — 콜백이 `message.usage_metadata`도 읽도록 보강
```python
def on_llm_end(self, response, **kwargs):
    for gen_list in response.generations:
        for gen in gen_list:
            # 1) LangChain 표준 usage_metadata (스트리밍 포함)
            msg = getattr(gen, "message", None)
            usage_meta = getattr(msg, "usage_metadata", None) if msg else None
            if usage_meta:
                self.prompt_tokens     += usage_meta.get("input_tokens", 0)
                self.completion_tokens += usage_meta.get("output_tokens", 0)
                self.total_tokens      += usage_meta.get("total_tokens", 0)
                continue
            # 2) 비스트리밍 generation_info fallback
            # 3) llm_output fallback
            ...
```

### 결과
백엔드 재시작 후 답변 생성 시 Answer Generator도 정상적으로 토큰·비용이 집계됩니다.

## 7. API 엔드포인트 요약

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/monitor/summary` | 전체 + Generator별 집계 + 모델명 |
| GET | `/monitor/logs?generator_type=&limit=&offset=` | 개별 호출 로그 (최신순) |
| GET | `/monitor/logs/{index}` | 특정 로그 상세 |
| GET | `/monitor/stats?hours=24` | 시간대별(시 단위) 통계 |

## 8. 확장 포인트

- **모델 추가 시**: `llm_monitor.py`의 `MODEL_PRICING`에 prompt/completion 단가 추가
- **장기 보관 필요 시**: 현재 인메모리(1000건) — DB(Postgres/SQLite) 영속화로 교체 가능
- **알림 필요 시**: `log_llm_call`에서 `success=False` 또는 비용 임계값 초과 시 Slack webhook 호출
- **사용자별 추적**: `LLMLog.detail`에 user_id 필드 추가 후 Generator 쪽에서 주입
