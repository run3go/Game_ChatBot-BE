from langchain_core.prompts import ChatPromptTemplate
from output_types import SQLWithUIType

UI_TABLE_MAP = {
    "SKILL": ["armory_skills_tb", "armory_gem_effects_tb", "armory_gem_tb"],
    "ARK_GRID": ["ark_grid_cores_tb", "ark_grid_effects_tb", "ark_grid_gems_tb"],
    "ARK_PASSIVE": ["ark_passive_effects_tb", "ark_passive_points_tb"],
    "ENGRAVING": ["armory_engravings_tb"],
    "AVATAR": ["armory_avatars_tb", "armory_profile_tb"],
    "COLLECTIBLE": ["armory_collectibles_tb", "armory_collectible_details_tb"],
    "PROFILE": ["armory_profile_tb", "armory_equipment_tb", "armory_card_tb", "armory_card_effects_tb", "armory_gem_effects_tb", "armory_gem_tb"],
    "TOTAL_INFO": ["armory_profile_tb", "armory_equipment_tb", "armory_card_tb", "armory_card_effects_tb", "ark_grid_cores_tb", "ark_grid_effects_tb", "ark_grid_gems_tb", "ark_passive_effects_tb", "ark_passive_points_tb",
                "armory_engravings_tb", "armory_avatars_tb", "armory_collectibles_tb", "armory_collectible_details_tb", "armory_skills_tb", "armory_gem_effects_tb", "armory_gem_tb"],
    "MARKET_ITEMS": ["market_items_tb"],
    "AUCTION_ITEMS": ["auction_items_tb"]
}

class SQLGenerator:

    def __init__(self, llm):
        self.llm = llm

    def generate(self, question: str, analysis, schema, nicknames: list[str] | None = None):
        prompt = ChatPromptTemplate.from_template("""
            너는 로스트아크 DB 전문가야.

            [SQL 출력 규칙]
            - 반드시 [스키마]에 명시된 테이블만 사용해. 그 외 테이블(예: characters, users, skills 등)은 절대 사용 금지.
            - 테이블에 접근할 때는 접두사로 lostark.를 사용해.

            [response_format별 SQL 규칙]
            - COUNT: COUNT(*) 단일 값만 반환. json_agg 사용 금지. AS 별칭은 의미 있게 지정. (예: 황로드유_겁화_count)
            - COUNT_LIST: GROUP BY + COUNT(*) 로 항목별 개수 목록 반환. json_agg 사용 금지.
            - VALUE: 단일 수치 컬럼 하나만 반환.
            - COMPARE: 메인 쿼리에 FROM 절 없이, 캐릭터별 서브쿼리를 개별 컬럼(AS 캐릭터명_data)으로 분리하고 json_build_object로 캡슐화해.
            - DISPLAY: 메인 쿼리에 FROM 절 없이, 테이블마다 서브쿼리로 json_agg(t.*)를 반환해.
              필터 조건이 있어도 반드시 서브쿼리 포맷을 유지하고, AS 별칭은 테이블 원본 이름을 그대로 사용해. (예: AS armory_skills_tb)
              SELECT
                (SELECT COALESCE(json_agg(t.*), '[]'::json) FROM lostark.{{테이블A}} t WHERE t.character_name = '닉네임' [AND 추가필터]) AS {{테이블A}},
                (SELECT COALESCE(json_agg(t.*), '[]'::json) FROM lostark.{{테이블B}} t WHERE t.character_name = '닉네임') AS {{테이블B}},
                (SELECT COALESCE(json_agg(t.*), '[]'::json) FROM lostark.{{테이블C}} t WHERE t.character_name = '닉네임' AND t.weak_point >= 1) AS {{테이블C}}                                  

            [분석 규칙]
            - 여러 테이블의 통계(Count, Sum)와 리스트를 한 번에 가져올 때는 JOIN 대신 상호관련 서브쿼리를 사용해.

            [ui_type 결정 규칙]
            - SQL이 캐릭터 테이블 전체 컬럼(t.* 또는 *)을 반환하면 → [분석]의 category 그대로 반환 (SKILL, ENGRAVING, ARK_GRID 등)
            - SQL이 특정 컬럼만 반환하거나 COUNT·SUM 등 집계값이면 → TEXT

            [질문]
            {question}

            [분석]
            {analysis}

            [대상 닉네임]
            {nicknames}
            - 반드시 위 닉네임을 WHERE character_name = '...' 조건으로 사용해.
            - 닉네임이 있으면 절대 생략하지 마.

            [스키마]
            {schema}

        """)

        structured_llm = self.llm.with_structured_output(SQLWithUIType)
        chain = prompt | structured_llm

        result = chain.invoke({
            "question": question,
            "analysis": analysis,
            "nicknames": nicknames if nicknames else "",
            "schema": schema
        })

        return self._clean_sql(result.sql), result.ui_type
    
    def generate_character_json(self, nicknames: list[str], tables: list[str]):
        queries = []

        for nickname in nicknames:
            subqueries = ",\n".join(
                f"  (SELECT COALESCE(json_agg(t.*), '[]'::json) FROM lostark.{table} t WHERE t.character_name = '{nickname}') AS {table}"
                for table in tables
            )
            sql = f"SELECT\n{subqueries}"

            queries.append({
                "nickname": nickname,
                "sql": sql.strip()
            })

        return queries
    
    def _clean_sql(self, sql: str):
        return (
            sql
            .replace("```sql", "")
            .replace("```", "")
            .strip()
        )