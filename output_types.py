from pydantic import BaseModel, Field
from typing import List

class QuestionAnalysis(BaseModel):
  nicknames: List[str] = Field(description="질문에서 추출된 순수 캐릭터 닉네임 리스트 (조사 제거)")
  relevant_tables: List[str] = Field(description="조회가 필요한 테이블 목록")
  is_comparison: bool = Field(description="두 명 이상의 캐릭터를 비교하는 질문인지 여부")
  ui_type: str = Field(description="TOTAL_INFO, PROFILE, ARK_GRID, CARD, ETC 중 하나")
  intent: str = Field(description="단순조회(API) 또는 복잡질문(LLM) 중 하나")
  keyword: str = Field(description="질문에서 닉네임을 제외한 핵심 키워드")
  item_name: str = Field(description="질문에서 추출된 아이템 명칭")