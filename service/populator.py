from sqlalchemy import text

class DataPopulator:

    def __init__(self, db):
        self.db = db

    def populate(self, ui_type: str, data: dict) -> dict:
        fn = getattr(self, f"_populate_{ui_type.lower()}", None)
        if fn:
            data = fn(data)
        return data

    def _populate_skill(self, data: dict) -> dict:
        skills = data.get("armory_skills_tb", [])

        pairs = list({(s["skill_name"], str(s["skill_level"]) + "레벨") for s in skills if s.get("skill_name") and s.get("skill_level") is not None})

        rows = self.db.execute(
            text("""
                SELECT skill_name, skill_icon_url, description, req_points, resource_cost
                FROM lostark.lostark_skill_level
                WHERE (skill_name, skill_level) = ANY(:pairs)
            """),
            {"pairs": pairs}
        ).mappings().all()

        skill_map = {r["skill_name"]: r for r in rows}
        data["armory_skills_tb"] = [
            {**s, **{k: v for k, v in skill_map.get(s["skill_name"], {}).items() if k != "skill_name"}}
            for s in skills
        ]
        return data
