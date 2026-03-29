# 파이썬 3.9 환경 사용
FROM python:3.9-slim

# 작업 폴더 지정
WORKDIR /app

# 필요한 파일 복사 및 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 코드 복사
COPY . .

# FastAPI 서버 실행 (8000번 포트)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]