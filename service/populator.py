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

        pairs = {(s["skill_name"], s["skill_level"]) for s in skills if s.get("skill_name") and s.get("skill_level") is not None}
        names = [p[0] for p in pairs]

        rows = self.db.execute(
            text("""
                SELECT skill_name, skill_level, skill_icon_url, description, req_points, resource_cost
                FROM lostark.lostark_skill_level
                WHERE skill_name = ANY(:names)
            """),
            {"names": names}
        ).mappings().all()

        skill_map = {r["skill_name"]: r for r in rows if (r["skill_name"], r["skill_level"]) in pairs}
        data["armory_skills_tb"] = [
            {**s, **{k: v for k, v in skill_map.get(s["skill_name"], {}).items() if k != "skill_name"}}
            for s in skills
        ]
        return data
