import yaml
from pathlib import Path

GAME_NAMES = {
    "LOSTARK": "로스트아크",
    "TFT": "롤토체스",
}


class PromptManager:
    def __init__(self):
        self.root = Path("prompts")
        self._analysis_cache: dict[str, dict] = {}
        self._base_cache: dict[str, dict] = {}
        self._formats_cache: dict[str, dict] = {}
        self._global_cache: dict[str, dict] = {}

    def _load_yaml(self, file_name: str) -> dict:
        path = self.root / file_name
        try:
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    return data if data else {}
            return {}
        except Exception as e:
            print(f"YAML 로드 실패 ({file_name}): {e}")
            return {}

    def _get(self, cache: dict, game_type: str, file_name: str) -> dict:
        if game_type not in cache:
            cache[game_type] = self._load_yaml(f"{game_type.lower()}/{file_name}")
        return cache[game_type]

    def build_analysis_template(self, game_type: str = "LOSTARK") -> str:
        a = self._get(self._analysis_cache, game_type, "analysis.yaml")
        game_name = GAME_NAMES.get(game_type, game_type)

        def escape(text: str) -> str:
            return text.replace("{", "{{").replace("}", "}}")

        return (
            f"너는 {game_name} 질문 분석기야.\n\n"
            f"{escape(a.get('category_rules', ''))}\n"
            "[카테고리 힌트 - embedding 검색 결과]\n"
            "{embedding_context}\n\n"
            "[게임 지식]\n"
            "{game_knowledge}\n\n"
            f"{escape(a.get('response_format_rules', ''))}\n"
            f"{escape(a.get('nickname_rules', ''))}\n"
            f"{escape(a.get('followup_rules', ''))}\n"
            "[이전 대화]\n"
            "{history}\n\n"
            "[사용자 질문]\n"
            "{question}"
        )

    def build_sql_rules(self, game_type: str = "LOSTARK", category: str = "", response_format: str = "") -> dict:
        base = self._get(self._base_cache, game_type, "base.yaml")
        formats = self._get(self._formats_cache, game_type, "formats.yaml")
        global_rules = self._get(self._global_cache, game_type, "global.yaml")

        cat_data = self._load_yaml(f"{game_type.lower()}/categories/{category.lower()}.yaml")
        g_rules = global_rules.get("global_constraints", "") if category.startswith("GLOBAL") else ""

        return {
            "common_rules": (
                f"### [BASIC SQL STANDARDS]\n{base.get('sql_basics', '')}\n\n"
                f"### [DYNAMIC TABLE SNAPSHOT RULES]\n{base.get('dynamic_table_rules', '')}\n\n"
                f"### [SYNTAX & CASTING]\n{base.get('syntax_rules', '')}"
            ),
            "response_format_rules": (
                f"### [FORMAT: {response_format}]\n"
                f"{formats.get('response_format_rules', {}).get(response_format, '해당 형식의 규칙이 정의되지 않았습니다.')}"
            ),
            "category_rules": (
                f"### [CATEGORY: {category}]\n"
                f"{cat_data.get('rules', '')}\n{g_rules}"
            ),
        }
