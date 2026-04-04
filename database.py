from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker 
from dotenv import load_dotenv

import os

load_dotenv()

db_url = os.getenv("DB_URL")
if not db_url:
    raise RuntimeError("환경변수 DB_URL이 설정되지 않았습니다.")

engine = create_engine(db_url)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()