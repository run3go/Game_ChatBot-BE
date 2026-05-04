# 파이썬 3.11 환경 사용
FROM python:3.11-slim

# 작업 폴더 지정
WORKDIR /app

# 필요한 파일 복사 및 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 코드 복사
COPY . .

# 빌드 시점에 reranker 모델을 미리 다운로드해 이미지에 포함
RUN python -c "from sentence_transformers import CrossEncoder; CrossEncoder('BAAI/bge-reranker-v2-m3')"

# FastAPI 서버 실행 (Cloud Run은 PORT 환경변수로 포트를 전달)
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]