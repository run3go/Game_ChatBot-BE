from langchain_core.prompts import ChatPromptTemplate

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

    def generate(self, question: str, analysis, schema):
        prompt = ChatPromptTemplate.from_template("""
            너는 로스트아크 DB 전문가야.

            [출력 규칙]
            - 반드시 [스키마]에 명시된 테이블만 사용해. 그 외 테이블(예: characters, users 등)은 절대 사용 금지.
            - SQL만 출력해. 설명 금지.
            - 테이블에 접근할 때는 접두사로 lostark.를 사용해.
        

            [aggregation_type별 SQL 규칙]
            - COUNT: 반드시 COUNT(*) 단일 값만 반환해. json_agg 사용 금지. AS 별칭은 무엇을 세는지 알 수 있도록 지정해. (예: 황로드유_겁화_count)
            - COUNT_LIST: GROUP BY + COUNT(*) 로 항목별 개수 목록을 반환해. json_agg 사용 금지. 각 COUNT 컬럼 AS 별칭도 동일하게 의미 있게 지정해.
            - VALUE: 단일 수치 컬럼 하나만 반환해.
            - LIST: json_agg로 해당 항목 목록을 반환해.
            - COMPARE: 각 캐릭터별 서브쿼리로 비교 가능한 구조로 반환해.
            - DISPLAY: 화면 표시용 전체 데이터를 json_agg로 반환해.

            [분석 규칙]
            - 메인 쿼리에 특정 테이블의 'FROM' 절을 사용하지 마. (PostgreSQL의 FROM 절 없는 SELECT 문 사용)
            - 각 캐릭터의 데이터를 개별 컬럼(AS 캐릭터명_data)으로 분리하고, 내부에서 'json_build_object'를 사용하여 캡슐화해.
            - 여러 테이블의 정보를 합쳐야 한다면 JOIN 대신 서브쿼리와 'json_agg'를 사용하여 단일 행으로 반환해.
            - 여러 테이블의 통계(Count, Sum)와 리스트(json_agg)를 한 번에 가져올 때는 JOIN 대신 상호관련 서브쿼리(Correlated Subquery)를 사용하여 데이터 중복 계산과 집계 함수 중첩 에러를 방지해.
    
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

        chain = prompt | self.llm

        result = chain.invoke({
            "question": question,
            "analysis": analysis,
            "nicknames": analysis.nicknames if analysis.nicknames else "",
            "schema": schema
        })
        
        return self._clean_sql(result.content)
    
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

    def _detect_ui_type(self, question: str):

        if "스킬" in question:
            return "SKILL"

        if "그리드" in question or "코어" in question:
            return "ARK_GRID"
        
        if "패시브" in question:
            return "ARK_PASSIVE"
        
        if "각인" in question:
            return "ENGRAVING"

        if "아바타" in question:
            return "AVATAR"

        if "내실" in question or "수집" in question:
            return "COLLECTIBLE"

        return "PROFILE"
    
    def _clean_sql(self, sql: str):
        return (
            sql
            .replace("```sql", "")
            .replace("```", "")
            .strip()
        )