DISPLAY_TRIGGERS: dict[str, set[str]] = {
    "SKILL":       {"스킬", "보석"},
    "ENGRAVING":   {"각인"},
    "AVATAR":      {"아바타"},
    "ARK_GRID":    {"아크그리드", "코어"},
    "ARK_PASSIVE": {"아크패시브", "진화", "깨달음", "도약"},
    "COLLECTIBLE": {"내실", "수집품"},
    "PROFILE":     {"장비", "프로필", "능력치"},
    "EXPEDITION":  {"원정대"},
    "TOTAL_INFO":  {"정보"},
}

UI_TABLE_MAP = {
    "SKILL": ["armory_skills_tb", "armory_gem_tb"],
    "ARK_GRID": ["ark_grid_cores_tb", "ark_grid_gems_tb"],
    "ARK_PASSIVE": ["ark_passive_effects_tb", "ark_passive_points_tb"],
    "ENGRAVING": ["armory_engravings_tb"],
    "AVATAR": ["armory_avatars_tb", "armory_profile_tb"],
    "COLLECTIBLE": ["armory_collectibles_tb", "armory_collectible_details_tb"],
    "PROFILE": ["armory_profile_tb", "armory_equipment_tb", "armory_card_tb", "armory_card_effects_tb", "armory_gem_tb"],
    "TOTAL_INFO": ["armory_profile_tb", "armory_equipment_tb", "armory_card_tb", "armory_card_effects_tb", "ark_grid_cores_tb", "ark_grid_gems_tb", "ark_passive_effects_tb", "ark_passive_points_tb",
                "armory_engravings_tb", "armory_avatars_tb", "armory_collectibles_tb", "armory_collectible_details_tb", "armory_skills_tb", "armory_gem_tb"],
    "MARKET": ["market_items_tb"],
    "AUCTION": ["auction_items_tb"]
}

CHARACTER_TYPES = set(UI_TABLE_MAP.keys())

POSTPOSITIONS = ["은", "는", "이", "가", "을", "를", "의", "와", "과", "랑", "이랑"]
STOPWORDS = ["스킬", "보석", "각인", "아바타", "장비", "내실", "능력치", "아크패시브", "아크그리드"]

# 실제 닉네임과 일치하더라도 닉네임으로 취급하지 않을 역할·설명 표현
NICKNAME_BLACKLIST = {"딜러", "딜", "서폿", "서포터", "서포트"}
