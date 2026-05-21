import json
import re

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_db

router = APIRouter()


def _clean_desc(raw: str) -> str:
    raw = raw.replace('<br><br>', '\n\n').replace('<br>', '\n')
    raw = re.sub(r'\(%i:[^)]*\)', '', raw)
    raw = re.sub(r'%i:[^%]+%', '', raw)
    return raw.strip()


def _parse_pg_array(val) -> list:
    if val is None:
        return []
    if isinstance(val, list):
        return val
    s = str(val).strip()
    if s.startswith('{') and s.endswith('}'):
        inner = s[1:-1]
        if not inner:
            return []
        return [item.strip().strip('"') for item in inner.split(',')]
    return []


def _build_trait_map(db) -> dict[str, str]:
    rows = db.execute(text(
        "SELECT eng_name, kor_name FROM tft.trait_meta_tb WHERE kor_name IS NOT NULL"
    )).mappings().all()
    mapping: dict[str, str] = {}
    for r in rows:
        eng = r["eng_name"] or ""
        kor = r["kor_name"]
        mapping[eng.lower()] = kor
        # TFT17_Bastion → bastion 형태도 등록
        stripped = re.sub(r'^tft\d+_', '', eng, flags=re.IGNORECASE).lower()
        if stripped not in mapping:
            mapping[stripped] = kor
    return mapping


def _resolve_trait(eng: str, trait_map: dict[str, str]) -> str:
    key = eng.lower()
    if key in trait_map:
        return trait_map[key]
    stripped = re.sub(r'^tft\d+_', '', eng, flags=re.IGNORECASE).lower()
    return trait_map.get(stripped, eng)


@router.get("/tft/assets")
def get_tft_assets(db: Session = Depends(get_db)):
    item_rows = db.execute(text(
        "SELECT kor_name, image_url, description FROM tft.item_meta_tb WHERE image_url IS NOT NULL"
    )).mappings().all()

    unit_rows = db.execute(text("""
        SELECT DISTINCT ON (kor_name)
            kor_name, image_url, skill, traits
        FROM tft.unit_meta_tb
        WHERE image_url IS NOT NULL AND kor_name IS NOT NULL
        ORDER BY kor_name, season DESC, fetched_at DESC
    """)).mappings().all()

    trait_map = _build_trait_map(db)

    items = {}
    for r in item_rows:
        items[r["kor_name"]] = {
            "imageUrl": r["image_url"],
            "description": _clean_desc(r["description"]) if r["description"] else "",
        }

    champions = {}
    for r in unit_rows:
        raw_traits = _parse_pg_array(r["traits"])
        entry: dict = {
            "imageUrl": r["image_url"],
            "traits": [_resolve_trait(t, trait_map) for t in raw_traits],
        }
        if r["skill"]:
            try:
                skill = r["skill"] if isinstance(r["skill"], dict) else json.loads(r["skill"])
                entry["skillName"] = skill.get("name", "")
                entry["skillDesc"] = _clean_desc(skill.get("desc", ""))
                entry["skillImageUrl"] = skill.get("imageUrl", "")
            except Exception:
                pass
        champions[r["kor_name"]] = entry

    trait_desc_rows = db.execute(text(
        "SELECT kor_name, description, stats FROM tft.trait_meta_tb WHERE kor_name IS NOT NULL"
    )).mappings().all()

    traits = {}
    for r in trait_desc_rows:
        raw_stats = r["stats"]
        if raw_stats:
            if isinstance(raw_stats, str):
                try:
                    raw_stats = json.loads(raw_stats)
                except Exception:
                    raw_stats = {}
            cleaned_stats = {k: _clean_desc(v) for k, v in raw_stats.items()}
        else:
            cleaned_stats = {}
        traits[r["kor_name"]] = {
            "description": _clean_desc(r["description"]) if r["description"] else "",
            "stats": cleaned_stats,
        }

    return {"items": items, "champions": champions, "traits": traits}
