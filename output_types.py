from pydantic import BaseModel, Field
from typing import List

class CharacterQueryType(BaseModel):
  is_specific_question: bool = Field(description="특정 질문의 답변을 원하면 True, 데이터를 화면에 표시하길 원하면 False")

class QuestionAnalysis(BaseModel):
  nicknames: List[str] = Field(description="질문에서 추출된 순수 캐릭터 닉네임 리스트 (조사 제거)")
  relevant_tables: List[str] = Field(description="조회가 필요한 테이블 목록")
  is_comparison: bool = Field(description="두 명 이상의 캐릭터를 비교하는 질문인지 여부")
  is_specific_question: bool = Field(description="특정 질문의 답변을 원하면 True, 데이터를 화면에 표시하길 원하면 False")
  ui_type: str = Field(description="TOTAL_INFO, PROFILE, ARK_GRID, CARD, ETC 중 하나")
  intent: str = Field(description="CHARACTER, COMPLEX, TRADING, API, GENERAL 중 하나")
  keyword: str = Field(description="질문에서 닉네임을 제외한 핵심 키워드")
  item_name: str = Field(description="질문에서 추출된 아이템 명칭")