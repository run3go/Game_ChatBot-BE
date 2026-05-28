import copy
import re
import logging
import threading
from collections import Counter
from datetime import datetime, timezone
from sqlalchemy import text
from api.riot_api import get_puuid, get_tft_match_ids, get_tft_match, get_league_by_puuid
from service.sql_pipeline import SQLPipeline

# DB에 없는 특성명의 영→한 폴백 (game_knowledge.py의 [시너지 영→한]과 동기화 유지)
_TRAIT_KO: dict[str, str] = {
    "admin": "중재자", "primordian": "태고족", "aptrait": "복제자",
    "psyops": "초능력", "drx": "N.O.V.A.", "fateweaver": "운명술사",
    "rangedtrait": "저격수", "timebreaker": "시간 균열자", "resisttank": "요새",
    "shieldtank": "선봉대", "hptank": "싸움꾼", "meleetrait": "습격자",
    "mecha": "메카", "summontrait": "길잡이", "astrait": "도전자",
    "manatrait": "전달자", "assassintrait": "불한당", "anima": "동물특공대",
    "animasquad": "동물특공대", "darkstar": "암흑의 별", "astronaut": "정령족",
    "spacegroove": "우주 그루브", "flextrait": "여행자", "stargazer": "별돌보미",
    "shenuniquetrait": "보루", "tahmkenchuniquetrait": "지휘관",
    "sonauniquetrait": "지휘관", "morganauniquetrait": "어둠의 여인",
    "fiorauniquetrait": "신성 결투가", "vexuniquetrait": "파멸자",
    "jhinuniquetrait": "말살자", "gravesuniquetrait": "최신상",
    "zeduniquetrait": "은하계 사냥꾼", "misfortuneuniquetrait": "기동총격여신",
    "rhaastuniquetrait": "구원자", "blitzcrankuniquetrait": "파티광",
}

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

    return {"summoner": summoner_name, "puuid": puuid, "matches": matches}


def _save_account_and_league_bg(puuid: str, game_name: str, tag_line: str, league_entries: list[dict] | None = None) -> None:
    """전적 조회 후 백그라운드에서 tft_acc_tb + normal_user_info_tb에 저장.
    league_entries를 넘기면 API 재호출 없이 해당 데이터를 사용한다."""
    from database import SessionLocal
    db = SessionLocal()
    try:
        db.execute(text("""
            INSERT INTO tft.tft_acc_tb (puuid, user_name, tag_line)
            VALUES (:puuid, :user_name, :tag_line)
            ON CONFLICT (puuid) DO UPDATE
                SET user_name  = EXCLUDED.user_name,
                    tag_line   = EXCLUDED.tag_line,
                    updated_at = NOW()
        """), {"puuid": puuid, "user_name": game_name, "tag_line": tag_line})

        entries = league_entries if league_entries is not None else get_league_by_puuid(puuid)
        if entries:
            snapshot_at = datetime.now(timezone.utc)
            for e in entries:
                if not e.get("queueType"):
                    continue
                db.execute(text("""
                    INSERT INTO tft.normal_user_info_tb (
                        snapshot_at, puuid, queue_type, region,
                        league_id, tier, rank,
                        league_points, wins, losses,
                        veteran, inactive, fresh_blood, hot_streak
                    ) VALUES (
                        :snapshot_at, :puuid, :queue_type, 'KR',
                        :league_id, :tier, :rank,
                        :league_points, :wins, :losses,
                        :veteran, :inactive, :fresh_blood, :hot_streak
                    )
                    ON CONFLICT (snapshot_at, puuid, queue_type) DO NOTHING
                """), {
                    "snapshot_at":    snapshot_at,
                    "puuid":          puuid,
                    "queue_type":     e.get("queueType"),
                    "league_id":      e.get("leagueId"),
                    "tier":           e.get("tier"),
                    "rank":           e.get("rank"),
                    "league_points":  e.get("leaguePoints", 0),
                    "wins":           e.get("wins", 0),
                    "losses":         e.get("losses", 0),
                    "veteran":        e.get("veteran"),
                    "inactive":       e.get("inactive"),
                    "fresh_blood":    e.get("freshBlood"),
                    "hot_streak":     e.get("hotStreak"),
                })
        db.commit()
    except Exception:
        logger.exception("계정/리그 스냅샷 저장 실패 (puuid=%s)", puuid)
        db.rollback()
    finally:
        db.close()


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

        league_entries: list[dict] = []
        ranked_entry: dict | None = None
        if "puuid" in data:
            try:
                league_entries = get_league_by_puuid(data["puuid"])
                ranked_entry = next((e for e in league_entries if e.get("queueType") == "RANKED_TFT"), None)
            except Exception:
                logger.exception("TFT 리그 정보 조회 실패")

        yield "status", "답변을 생성하는 중이에요..."
        yield "result", {
            "ui_type": "TFT_MATCH_HISTORY",
            "summoner": data["summoner"],
            "matches": data["matches"],
            "league": ranked_entry,
        }

        # LLM용 데이터는 deepcopy — 원본 data는 프론트 직렬화에 쓰이므로 변경 금지
        llm_data = copy.deepcopy(data)

        strip_prefix = lambda s: re.sub(r'^(?:TFT|Set)\d+_?', '', s, flags=re.IGNORECASE).lower()
        umap = {strip_prefix(r["unit_name"]): r["kor_name"] for r in self.db.execute(text("SELECT unit_name, kor_name FROM tft.unit_meta_tb WHERE kor_name IS NOT NULL AND unit_name IS NOT NULL")).mappings()}
        tmap = {strip_prefix(r["eng_name"]): r["kor_name"] for r in self.db.execute(text("SELECT eng_name, kor_name FROM tft.trait_meta_tb WHERE kor_name IS NOT NULL AND eng_name IS NOT NULL")).mappings()}
        amap = {strip_prefix(r["item_name"]): r["kor_name"] for r in self.db.execute(text("SELECT item_name, kor_name FROM tft.item_meta_tb WHERE kor_name IS NOT NULL AND item_name IS NOT NULL")).mappings()}
        for m in llm_data["matches"]:
            for u in m["units"]:
                key = strip_prefix(u["name"])
                u["name"] = umap.get(key, u["name"])
            for t in m["traits"]:
                key = strip_prefix(t["name"])
                t["name"] = tmap.get(key) or _TRAIT_KO.get(key) or key
            m["augments"] = [amap.get(strip_prefix(a), a) for a in m.get("augments", [])]

        # 아이템 3개 풀착용 유닛을 Python에서 직접 집계 (LLM이 JSON 배열을 직접 세는 것은 불안정)
        core_counter: Counter = Counter()
        for m in llm_data["matches"]:
            for u in m["units"]:
                if len(u.get("items", [])) == 3:
                    tier_suffix = f" {u['tier']}성" if u.get("tier", 1) >= 2 else ""
                    core_counter[f"{u['name']}{tier_suffix}"] += 1
        llm_data["core_units"] = [
            {"name": name, "count": cnt}
            for name, cnt in core_counter.most_common(3)
            if cnt >= 2
        ]

        yield "result_text", self.answer_generator.answer_tft_api(question, llm_data, history)

        if "puuid" in data:
            game_name, tag_line = summoner_name.split("#", 1)
            threading.Thread(
                target=_save_account_and_league_bg,
                args=(data["puuid"], game_name, tag_line, league_entries),
                daemon=True,
            ).start()

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
