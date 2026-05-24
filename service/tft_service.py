import re
import logging
from datetime import datetime
from sqlalchemy import text
from api.riot_api import get_puuid, get_tft_match_ids, get_tft_match
from service.sql_pipeline import SQLPipeline

logger = logging.getLogger(__name__)

_API_CATEGORIES = {"USER_MATCH_HISTORY"}

# 태그라인 패턴 — 이름은 공백 포함 가능하므로 역방향으로 추출
_TAG_RE = re.compile(r"#([A-Za-z0-9]+)")
# 태그 앞의 이름 부분: 한글·영문·숫자·공백의 연속 (맨 끝에 위치)
_NAME_BEFORE_TAG_RE = re.compile(r"([가-힣A-Za-z0-9][가-힣A-Za-z0-9 ]*)$")


def extract_summoner_from_question(question: str) -> str | None:
    tag_m = _TAG_RE.search(question)
    if not tag_m:
        return None
    tag_line = tag_m.group(1)
    before_tag = question[: tag_m.start()]
    name_m = _NAME_BEFORE_TAG_RE.search(before_tag)
    if not name_m:
        return None
    game_name = name_m.group(1).rstrip()
    return f"{game_name}#{tag_line}" if game_name else None


def fetch_match_history(summoner_name: str, count: int = 10) -> dict:
    parts = summoner_name.strip().split("#", 1)
    if len(parts) != 2 or not parts[1]:
        return {"error": f"'{summoner_name}'은 올바른 소환사명 형식이 아닙니다. (예: 이름#KR1)"}

    game_name, tag_line = parts
    puuid, reason = get_puuid(game_name, tag_line)
    if not puuid:
        if reason == "not_found":
            return {"error": f"'{summoner_name}' 소환사를 찾을 수 없습니다. 소환사명과 태그를 다시 확인해 주세요."}
        if reason == "unauthorized":
            return {"error": "Riot API 키가 만료되었거나 유효하지 않습니다. 관리자에게 문의해 주세요."}
        return {"error": "Riot API 서버와 통신 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."}

    match_ids = get_tft_match_ids(puuid, count=count)
    if not match_ids:
        return {"summoner": summoner_name, "matches": []}

    matches = []
    for mid in match_ids:
        raw = get_tft_match(mid)
        if not raw:
            continue
        participant = _find_participant(raw, puuid)
        if participant:
            game_datetime = raw.get("info", {}).get("game_datetime", 0)
            matches.append(_format_participant(participant, game_datetime))

    return {"summoner": summoner_name, "matches": matches}


class TFTService:

    def __init__(self, db, sql_generator, answer_generator):
        self.db = db
        self.answer_generator = answer_generator
        self.sql_pipeline = SQLPipeline(db, sql_generator, answer_generator)

    def handle(self, question, analysis, history, filtered_entries, abbr_hints, **_):
        if analysis.category == "GENERAL":
            yield "status", "답변을 생성하는 중이에요..."
            yield "result", self.answer_generator.answer_general(question, history, game_type="TFT")
            return

        if analysis.category in _API_CATEGORIES:
            yield from self._handle_riot_api(question, analysis, history)
        else:
            yield from self._handle_sql(question, analysis, history, filtered_entries, abbr_hints)

    def _handle_riot_api(self, question, analysis, history):
        summoner_name = extract_summoner_from_question(question)
        if not summoner_name and analysis.nicknames:
            summoner_name = analysis.nicknames[0]
        if not summoner_name:
            yield "result", ["어떤 소환사의 전적을 알고 싶으신가요? 소환사명#태그를 알려주세요! (예: 이름#KR1)"]
            return

        yield "status", f"'{summoner_name}' 전적을 가져오는 중이에요..."
        try:
            data = fetch_match_history(summoner_name)
        except Exception:
            logger.exception("TFT 전적 조회 실패")
            yield "result", ["전적 조회 중 오류가 발생했어요. 잠시 후 다시 시도해 주세요."]
            return

        if "error" in data:
            yield "result", [data["error"]]
            return

        yield "nicknames", [summoner_name]

        yield "status", "답변을 생성하는 중이에요..."
        yield "result", {
            "ui_type": "TFT_MATCH_HISTORY",
            "summoner": data["summoner"],
            "matches": data["matches"],
        }

        strip = lambda s: re.sub(r'^TFT\d+_', '', s, flags=re.IGNORECASE).lower()
        umap = {strip(r["unit_name"]): r["kor_name"] for r in self.db.execute(text("SELECT unit_name, kor_name FROM tft.unit_meta_tb WHERE kor_name IS NOT NULL AND unit_name IS NOT NULL")).mappings()}
        tmap = {strip(r["eng_name"]): r["kor_name"] for r in self.db.execute(text("SELECT eng_name, kor_name FROM tft.trait_meta_tb WHERE kor_name IS NOT NULL AND eng_name IS NOT NULL")).mappings()}
        amap = {strip(r["item_name"]): r["kor_name"] for r in self.db.execute(text("SELECT item_name, kor_name FROM tft.item_meta_tb WHERE kor_name IS NOT NULL AND item_name IS NOT NULL")).mappings()}
        for m in data["matches"]:
            for u in m["units"]: u["name"] = umap.get(strip(u["name"]), u["name"])
            for t in m["traits"]: t["name"] = tmap.get(strip(t["name"]), t["name"])
            m["augments"] = [amap.get(strip(a), a) for a in m.get("augments", [])]

        yield "result_text", self.answer_generator.answer_tft_api(question, data, history)

    def _handle_sql(self, question, analysis, history, filtered_entries, abbr_hints):
        yield "status", "데이터를 조회하는 중이에요..."
        try:
            result, sql = self.sql_pipeline.run(
                question, [], analysis, history,
                filtered_entries, abbr_hints, game_type="TFT",
            )
        except ValueError as e:
            logger.warning("TFT 질문 처리 실패 (ValueError): %s", e)
            yield "result", ["질문을 좀 더 구체적으로 해주시면 더 잘 답변드릴 수 있어요."]
            return
        except Exception:
            logger.exception("TFT 데이터 조회 실패")
            yield "result", ["잠시 후 다시 시도해 주세요."]
            return

        if sql:
            yield "sql", sql
        yield "result", result


def _find_participant(match: dict, puuid: str) -> dict | None:
    for p in match.get("info", {}).get("participants", []):
        if p.get("puuid") == puuid:
            return p
    return None


def _format_participant(p: dict, game_datetime: int) -> dict:
    # 활성화된 특성만, 유닛 수 내림차순으로 최대 5개
    traits = sorted(
        [t for t in p.get("traits", []) if t.get("tier_current", 0) > 0],
        key=lambda t: -t.get("num_units", 0),
    )[:5]

    units = sorted(p.get("units", []), key=lambda u: -u.get("tier", 0))

    return {
        "placement": p.get("placement"),
        "game_date": datetime.fromtimestamp(game_datetime / 1000).strftime("%Y-%m-%d %H:%M"),
        "level": p.get("level"),
        "augments": p.get("augments", []),
        "traits": [
            {
                "name": t["name"],
                "num_units": t["num_units"],
                # style: 1=브론즈, 2=실버, 3=골드, 4=프리즘
                "style": t.get("style", 0),
            }
            for t in traits
        ],
        "units": [
            {
                "name": u.get("character_id", ""),
                "tier": u.get("tier", 1),
                "items": u.get("itemNames", u.get("items", [])),
            }
            for u in units
        ],
        "total_damage_to_players": p.get("total_damage_to_players"),
        "last_round": p.get("last_round"),
    }
