from pydantic import BaseModel, Field
from typing import List, Literal

GameType = Literal["LOSTARK", "TFT", "UNKNOWN"]


class _BaseAnalysis(BaseModel):
    nicknames: List[str] = Field(description="질문에서 추출된 순수 캐릭터 닉네임 리스트 (조사 제거)")
    reason: str = Field(description="response_format의 선정 이유")
    reask_message: str | None = Field(description="재질문 유도 메시지 (필요 시)")


class LOSTARKAnalysis(_BaseAnalysis):
    response_format: Literal["DISPLAY", "LIST", "COMPARE", "COUNT", "COUNT_LIST", "VALUE", "TEXT"] = Field(description="응답 형식")
    category: Literal[
        "GENERAL", "GLOBAL_SKILL", "GLOBAL_ARK_PASSIVE", "GLOBAL_ARK_GRID", "GLOBAL_ENGRAVING", "GLOBAL_PROFILE",
        "TRADING", "SKILL", "ENGRAVING", "AVATAR", "ARK_GRID", "ARK_PASSIVE",
        "COLLECTIBLE", "PROFILE", "TOTAL_INFO", "EXPEDITION", "MARKET", "AUCTION",
    ] = Field(description="질문 카테고리")


class TFTAnalysis(_BaseAnalysis):
    response_format: Literal[
        "LIST", "FILTER", "JOIN_ARRAY", "REGEX_EXTRACT", "FILTER_TAGS",
        "FILTER_BY_ITEM", "FILTER_BY_AUGMENT_UNIQUE", "MULTI_UNIT_MATCHING",
        "COMBINE_ITEM_AND_SEARCH", "TEXT",
    ] = Field(description="응답 형식")
    category: Literal[
        "GENERAL", "USER_MATCH_HISTORY", "META_COMPS", "UNIT_INFO",
        "UNIT_ITEM_RECOMMENDATION", "COMPARE_PERFORMANCE", "AUGMENT_COMPS",
        "BENCH_RECOMMENDATION", "ITEM_BUILDUP_COMPS", "PATCH_COMPS",
        "META_SYNERGY", "UNIT_ITEM_PERFORMANCE", "UNIT_PERFORMANCE", "ITEM_PERFORMANCE",
    ] = Field(description="질문 카테고리")


QuestionAnalysis = LOSTARKAnalysis | TFTAnalysis

class SQLWithUIType(BaseModel):
  sql: str = Field(description="생성된 SQL 쿼리 (SQL만, 설명 없이)")