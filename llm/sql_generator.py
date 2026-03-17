from langchain_core.prompts import ChatPromptTemplate
from utils.text_parser import extract_nicknames

class SQLGenerator:

    def __init__(self, llm):
        self.llm = llm
        self.UI_TABLE_MAP = {
            "SKILL": ["armory_skills_tb", "armory_gem_effects_tb", "armory_gem_tb"],
            "ARK_GRID": ["ark_grid_cores_tb", "ark_grid_effects_tb", "ark_grid_gems_tb"],
            "ARK_PASSIVE": ["ark_passive_effects_tb", "ark_passive_points_tb"],
            "ENGRAVING": ["armory_engravings_tb"],
            "AVATAR": ["armory_avatars_tb"],
            "COLLECTIBLE": ["armory_collectibles_tb", "armory_collectible_details_tb"],
            "PROFILE": ["armory_profile_tb", "armory_equipment_tb", "armory_card_tb", "armory_card_effects_tb", "armory_gem_effects_tb", "armory_gem_tb"],
            "TOTAL_INFO": ["armory_profile_tb", "armory_equipment_tb", "armory_card_tb", "armory_card_effects_tb", "ark_grid_cores_tb", "ark_grid_effects_tb", "ark_grid_gems_tb", "ark_passive_effects_tb", "ark_passive_points_tb",
                        "armory_engravings_tb", "armory_avatars_tb", "armory_collectibles_tb", "armory_collectible_details_tb", "armory_skills_tb", "armory_gem_effects_tb", "armory_gem_tb"],
            "MARKET_ITEMS": ["market_items_tb"],
            "AUCTION_ITEMS": ["auction_items_tb"]
        }

    def generate(self, question: str, analysis, schema):
        prompt = ChatPromptTemplate.from_template("""
            너는 로스트아크 DB 전문가야.

            --------------------------------------

            [출력 규칙]
            - 반드시 제공된 테이블만 사용해.
            - SQL만 출력해.
            - 테이블에 접근할 때는 접두사로 lostark.를 사용해.
            
            --------------------------------------

            [분석 규칙]
            - 메인 쿼리에 특정 테이블의 'FROM' 절을 사용하지 마. (PostgreSQL의 FROM 절 없는 SELECT 문 사용)
            - 각 캐릭터의 데이터를 개별 컬럼(AS 캐릭터명_data)으로 분리하고, 내부에서 'json_build_object'를 사용하여 캡슐화해.
            - 여러 테이블의 정보를 합쳐야 한다면 JOIN 대신 서브쿼리와 'json_agg'를 사용하여 단일 행으로 반환해. 
            - 여러 테이블의 통계(Count, Sum)와 리스트(json_agg)를 한 번에 가져올 때는 JOIN 대신 상호관련 서브쿼리(Correlated Subquery)를 사용하여 데이터 중복 계산과 집계 함수 중첩 에러를 방지해.

            --------------------------------------

            [비교 지침]                                             
            - '아크 그리드' 비교
                - 고대/유물/전설/영웅 코어 갯수 비교
                - 어떤 효과가 더 높은지 비교               
            - '각인' 비교
                - 설명을 제외한 나머지 속성을 비교

            --------------------------------------

            [질문]
            {question}

            [분석]
            {analysis}                             
                                                  
            [스키마]
            {schema}

        """)

        chain = prompt | self.llm

        result = chain.invoke({
            "question": question,
            "analysis": analysis,
            "schema": schema
        })
        
        return self._clean_sql(result.content)
    
    def generate_character(self, question: str, db):

        ui_type = self._detect_ui_type(question)
        nicknames = extract_nicknames(db, question)

        tables = self.UI_TABLE_MAP.get(ui_type)

        queries = []

        for nickname in nicknames:
            for table in tables:
                sql = f"""
                SELECT *
                FROM lostark.{table}
                WHERE character_name = '{nickname}'
                """
                queries.append({
                    "nickname": nickname,
                    "table": table,
                    "sql": sql.strip()
                })

        return queries, ui_type
    
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