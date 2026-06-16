# 무물봇 Backend

게임 유저의 질문에 AI가 실시간으로 답변하는 챗봇 서비스의 백엔드 서버입니다.  
**로스트아크**와 **TFT(롤토체스)** 두 게임을 지원하며, 사용자의 질문을 분석해 SQL을 생성하고 DB에서 데이터를 조회한 뒤 LLM이 자연어로 답변을 생성합니다.

---

## 기술 스택

| 분류 | 기술 |
|------|------|
| **프레임워크** | FastAPI, Uvicorn |
| **LLM** | OpenRouter (GPT-4o-mini), LangChain |
| **데이터베이스** | PostgreSQL, SQLAlchemy |
| **임베딩 / 리랭킹** | Sentence-Transformers (CrossEncoder) |
| **모니터링** | LangSmith |
| **외부 API** | 로스트아크 공식 API, Riot API |
| **데이터 파이프라인** | Apache Airflow |

---

## 아키텍처

```
사용자 질문
    │
    ▼
[게임 감지]
키워드로 즉시 판별 (quick_detect)
실패 시 LLM으로 감지
    │
    ▼
[질문 분석] AnalysisGenerator
카테고리 / 응답 형식 / 닉네임 추출 결정
    │
    ▼
[데이터 검색] 임베딩 유사도 검색 + CrossEncoder 리랭킹
관련 DB 스키마 및 Few-shot 예제 검색
    │
    ▼
[SQL 생성] SQLGenerator
LLM이 질문에 맞는 SQL 쿼리 작성
    │
    ▼
[SQL 실행]
PostgreSQL에서 실제 게임 데이터 조회
    │
    ▼
[답변 생성] AnswerGenerator
조회 결과를 바탕으로 LLM이 자연어 답변 생성
    │
    ▼
[SSE 스트리밍]
청크 단위로 클라이언트에 실시간 전송
    │
    ▼
[백그라운드 저장]
대화 내용 DB 저장 (응답 완료 후 비동기 처리)
```

---

## 프로젝트 구조

```
dev/
├── main.py                  # FastAPI 앱 진입점, LLM 인스턴스 초기화
├── database.py              # SQLAlchemy 세션 설정
├── constants.py             # UI 타입 매핑, 트리거 상수
├── output_types.py          # 분석 결과 Pydantic 모델
│
├── routers/                 # API 엔드포인트
│   ├── ask.py               # /ask/stream — SSE 스트리밍 질문 처리
│   ├── users.py             # 사용자 등록, 호출 횟수 관리
│   ├── sessions.py          # 채팅 세션 생성/조회/삭제
│   ├── monitor.py           # 모니터링 대시보드 API
│   ├── airflow.py           # 데이터 수집 DAG 트리거
│   └── tft.py               # TFT 메타데이터 조회
│
├── service/                 # 비즈니스 로직
│   ├── ai_service.py        # 질문 처리 통합 서비스
│   ├── chat_service.py      # 세션/메시지 DB 관리
│   ├── prompt_manager.py    # YAML 기반 프롬프트 관리
│   ├── sql_pipeline.py      # SQL 생성 및 실행 파이프라인
│   ├── lostark_service.py   # 로스트아크 데이터 처리
│   └── tft_service.py       # TFT 데이터 처리
│
├── llm/                     # LLM 모듈
│   ├── factory.py           # LLM 인스턴스 생성
│   ├── game_detector.py     # 게임 타입 감지
│   ├── analysis_generator.py # 질문 분석
│   ├── sql_generator.py     # SQL 생성
│   ├── answer_generator.py  # 답변 생성
│   ├── embedding_lookup_retriever.py  # 임베딩 검색
│   ├── few_shot_retriever.py          # Few-shot 예제 검색
│   └── llm_monitor.py       # LLM 호출 모니터링
│
├── prompts/                 # 게임별 프롬프트 템플릿 (YAML)
│   ├── lostark/
│   └── tft/
│
├── api/                     # 외부 API 클라이언트
│   ├── lostark_api.py       # 로스트아크 공식 API
│   └── riot_api.py          # Riot API (TFT)
│
├── utils/                   # 유틸리티
│   ├── reranker.py          # CrossEncoder 리랭킹
│   ├── db_schema_store.py   # DB 스키마 캐싱
│   └── embeddings.py        # 임베딩 로드
│
└── tests/
```

---

## 주요 API

### `POST /ask/stream`
사용자 질문을 받아 SSE(Server-Sent Events)로 실시간 답변을 스트리밍합니다.

**SSE 이벤트 타입**

| type | 설명 |
|------|------|
| `status` | 처리 진행 상태 메시지 |
| `text` | 답변 텍스트 청크 |
| `structured` | UI 렌더링용 구조화 데이터 |
| `confirm_collect` | 데이터 수집 확인 요청 |
| `title` | 첫 질문 시 생성된 채팅 제목 |
| `data_updated_at` | 데이터 최신화 일시 |

### `GET /users/call-count`
사용자의 남은 질문 횟수를 반환합니다. (일일 50회 제한)

### `POST /chat/sessions`
새 채팅 세션을 생성합니다.

### `POST /trigger-update`
Airflow DAG를 트리거해 특정 닉네임의 게임 데이터를 수집합니다.

---

## 실행 방법

### 1. 의존성 설치

```bash
pip install -r requirements.txt
```

### 2. 환경변수 설정

`.env` 파일을 생성하고 아래 변수를 설정합니다.

```env
OPENROUTER_API_KEY=

DB_URL=

LOSTARK_API_KEY=
RIOT_API_KEY=

AIRFLOW_BASE_URL=
AIRFLOW_USERNAME=
AIRFLOW_PASSWORD=

# LangSmith 모니터링 (선택)
LANGCHAIN_TRACING_V2=true
LANGCHAIN_ENDPOINT=
LANGCHAIN_API_KEY=
LANGCHAIN_PROJECT=
```

### 3. 서버 실행

```bash
python -m uvicorn main:app --reload
```

---

## 테스트

```bash
pytest tests/
```
