from pydantic import BaseModel, Field
from typing import List

class QuestionAnalysis(BaseModel):
  nicknames: List[str] = Field(description="질문에서 추출된 순수 캐릭터 닉네임 리스트 (조사 제거)")
  response_format: str = Field(description="DISPLAY, COMPARE, COUNT, COUNT_LIST, VALUE 중 하나")
  category: str = Field(description="GENERAL | COMPLEX | TRADING | SKILL | ENGRAVING | AVATAR | ARK_GRID | ARK_PASSIVE | COLLECTIBLE | PROFILE | TOTAL_INFO | EXPEDITION | MARKET_ITEMS | AUCTION_ITEMS 중 하나")
  keywords: List[str] = Field(description="질문에서 닉네임을 제외한 핵심 개념 목록. 은어·약어는 정식 명칭으로 확장. 각 개념을 분리해서 나열. TRADING이면 아이템 정식 명칭 포함.")

class SQLWithUIType(BaseModel):
  sql: str = Field(description="생성된 SQL 쿼리 (SQL만, 설명 없이)")
  ui_type: str = Field(description=(
    "TEXT 또는 캐릭터 카테고리 타입. "
    "닉네임 외 조건 없이 카테고리 전체를 조회하면 해당 타입 반환 "
    "(SKILL | ENGRAVING | AVATAR | ARK_GRID | ARK_PASSIVE | COLLECTIBLE | PROFILE | TOTAL_INFO). "
    "속성·조건으로 필터링된 부분 데이터이거나 수치·통계 데이터이면 TEXT 반환."
  ))