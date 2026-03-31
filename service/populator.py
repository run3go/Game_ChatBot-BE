from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

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

    def _populate_ark_passive(self, data: dict) -> dict:
        effects = data.get("ark_passive_effects_tb", [])
        names = list({e["effect_name"] for e in effects if e.get("effect_name")})
        if not names:
            return data

        rows = self.db.execute(
            text("""
                SELECT passive_name, tier, req_points, max_level,
                       lv1_effect, lv2_effect, lv3_effect, lv4_effect, lv5_effect,
                       lv10_effect, lv20_effect, lv30_effect
                FROM lostark.ark_passive
                WHERE passive_name = ANY(:names)
            """),
            {"names": names}
        ).mappings().all()

        meta_map = {r["passive_name"]: dict(r) for r in rows}

        enriched = []
        for e in effects:
            meta = meta_map.get(e["effect_name"], {})
            level = e.get("level")
            level_effect = None
            if level is not None:
                level_effect = meta.get(f"lv{level}_effect")
            enriched.append({
                **e,
                "req_points": meta.get("req_points"),
                "max_level": meta.get("max_level"),
                "level_effect": level_effect,
            })

        data["ark_passive_effects_tb"] = enriched
        return data

    def fetch_missing_tables(self, nickname: str, tables: list) -> dict:
        subqueries = ",\n".join(
            f"  (SELECT COALESCE(json_agg(t.*), '[]'::json) FROM lostark.{table} t "
            f"WHERE t.character_name = :nickname AND t.collected_at = "
            f"(SELECT MAX(t2.collected_at) FROM lostark.{table} t2 WHERE t2.character_name = :nickname)) AS {table}"
            for table in tables
        )
        try:
            row = self.db.execute(text(f"SELECT\n{subqueries}"), {"nickname": nickname}).mappings().fetchone()
            return dict(row) if row else {}
        except SQLAlchemyError:
            return {}

