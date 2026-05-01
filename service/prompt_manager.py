import yaml
from pathlib import Path

class PromptManager:
    def __init__(self):
        self.root = Path("prompts")
        self.base = self._load_yaml("base.yaml")
        self.formats = self._load_yaml("formats.yaml")
        self.global_rules = self._load_yaml("global.yaml")
        self.analysis = self._load_yaml("analysis.yaml")

    def _load_yaml(self, file_name: str):
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

    def build_analysis_template(self) -> str:
        """AnalysisGenerator에 주입할 프롬프트 템플릿 문자열 반환"""
        a = self.analysis
        return (
            "너는 로스트아크 질문 분석기야.\n\n"
            f"{a.get('category_rules', '')}\n"
            "[카테고리 힌트 - embedding 검색 결과]\n"
            "{embedding_context}\n\n"
            "[게임 지식]\n"
            "{game_knowledge}\n\n"
            f"{a.get('response_format_rules', '')}\n"
            f"{a.get('nickname_rules', '')}\n"
            f"{a.get('followup_rules', '')}\n"
            "[이전 대화]\n"
            "{history}\n\n"
            "[사용자 질문]\n"
            "{question}"
        )

    def build_sql_rules(self, category: str, response_format: str):
        """SQLGenerator에 주입할 핵심 규칙 세트를 반환"""
        # 1. 카테고리별 파일 로드 (예: categories/auction.yaml)
        cat_file = f"categories/{category.lower()}.yaml"
        cat_data = self._load_yaml(cat_file)
        
        # 2. 글로벌 규칙 (Global 카테고리일 경우)
        g_rules = self.global_rules.get("global_constraints", "") if category.startswith("GLOBAL") else ""

        return {
            "common_rules": (
                f"### [BASIC SQL STANDARDS]\n{self.base.get('sql_basics', '')}\n\n"
                f"### [DYNAMIC TABLE SNAPSHOT RULES]\n{self.base.get('dynamic_table_rules', '')}\n\n"
                f"### [SYNTAX & CASTING]\n{self.base.get('syntax_rules', '')}"
            ),
            "response_format_rules": (
                f"### [FORMAT: {response_format}]\n"
                f"{self.formats.get('response_format_rules', {}).get(response_format, '해당 형식의 규칙이 정의되지 않았습니다.')}"
            ),
            "category_rules": (
                f"### [CATEGORY: {category}]\n"
                f"{cat_data.get('rules', '')}\n{g_rules}"
            )
        }