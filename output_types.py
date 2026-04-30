from pydantic import BaseModel, Field
from typing import List, Literal

class QuestionAnalysis(BaseModel):
  nicknames: List[str] = Field(description="질문에서 추출된 순수 캐릭터 닉네임 리스트 (조사 제거)")
  response_format: Literal["DISPLAY", "LIST", "COMPARE", "COUNT", "COUNT_LIST", "VALUE", "TEXT"] = Field(description="응답 형식")
  category: Literal["GENERAL", "GLOBAL_SKILL", "GLOBAL_ARK_PASSIVE", "GLOBAL_ARK_GRID", "GLOBAL_ENGRAVING", "GLOBAL_PROFILE",
                    "TRADING", "SKILL", "ENGRAVING", "AVATAR", "ARK_GRID", "ARK_PASSIVE",
                    "COLLECTIBLE", "PROFILE", "TOTAL_INFO", "EXPEDITION", "MARKET", "AUCTION"] = Field(description="질문 카테고리")
  reason: str = Field(description="response_format의 선정 이유")
  reask_message: str | None = Field(description="재질문 유도 메시지 (필요 시)")

class SQLWithUIType(BaseModel):
  sql: str = Field(description="생성된 SQL 쿼리 (SQL만, 설명 없이)")
  ui_type: Literal["TEXT", "SKILL", "ENGRAVING", "AVATAR", "ARK_GRID", "ARK_PASSIVE", "COLLECTIBLE", "PROFILE", "TOTAL_INFO", "MARKET", "AUCTION"] = Field(description="카테고리 전체 조회면 해당 타입, 필터링·집계·수치 데이터면 TEXT")