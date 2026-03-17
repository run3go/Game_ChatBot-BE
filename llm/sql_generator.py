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
    
    def generate_character(self, question: str, db):

        ui_type = self._detect_ui_type(question)
        nicknames = extract_nicknames(db, question)

        tables = self.UI_TABLE_MAP.get(ui_type, ["armory_profile_tb"])

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