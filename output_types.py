from pydantic import BaseModel, Field
from typing import List, Literal

class QuestionAnalysis(BaseModel):
  nicknames: List[str] = Field(description="질문에서 추출된 순수 캐릭터 닉네임 리스트 (조사 제거)")
  response_format: Literal["DISPLAY", "COMPARE", "COUNT", "COUNT_LIST", "VALUE", "GENERAL"] = Field(description="응답 형식")
  category: Literal["GENERAL", "COMPLEX", "TRADING", "SKILL", "ENGRAVING", "AVATAR", "ARK_GRID", "ARK_PASSIVE", 
                    "COLLECTIBLE", "PROFILE", "TOTAL_INFO", "EXPEDITION", "MARKET_ITEMS", "AUCTION_ITEMS"] = Field(description="질문 카테고리")
  keywords: List[str] = Field(description="질문에서 닉네임을 제외한 핵심 개념 목록. 은어·약어는 정식 명칭으로 확장. 각 개념을 분리해서 나열. TRADING이면 아이템 정식 명칭 포함.")

class SQLWithUIType(BaseModel):
  sql: str = Field(description="생성된 SQL 쿼리 (SQL만, 설명 없이)")
  ui_type: Literal["TEXT", "SKILL", "ENGRAVING", "AVATAR", "ARK_GRID", "ARK_PASSIVE", "COLLECTIBLE", "PROFILE", "TOTAL_INFO"] = Field(description="카테고리 전체 조회면 해당 타입, 필터링·집계·수치 데이터면 TEXT")