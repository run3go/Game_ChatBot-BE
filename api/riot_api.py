import os
import urllib.parse
import logging
import httpx

logger = logging.getLogger(__name__)

_ACCOUNT_BASE = "https://asia.api.riotgames.com"
_TFT_BASE = "https://asia.api.riotgames.com"
_PLATFORM_BASE = "https://kr.api.riotgames.com"


def _headers() -> dict:
    api_key = os.getenv("RIOT_API_KEY")
    if not api_key:
        raise ValueError("RIOT_API_KEY 환경변수가 설정되지 않았습니다.")
    return {"X-Riot-Token": api_key}


def get_puuid(game_name: str, tag_line: str) -> tuple[str | None, str]:
    """(puuid, error_reason) 반환. 성공 시 error_reason은 빈 문자열."""
    url = (
        f"{_ACCOUNT_BASE}/riot/account/v1/accounts/by-riot-id"
        f"/{urllib.parse.quote(game_name)}/{urllib.parse.quote(tag_line)}"
    )
    try:
        with httpx.Client(timeout=10) as client:
            r = client.get(url, headers=_headers())
        if r.status_code == 200:
            return r.json()["puuid"], ""
        if r.status_code == 404:
            logger.info("소환사 없음 (404): %s#%s", game_name, tag_line)
            return None, "not_found"
        if r.status_code in (401, 403):
            logger.error("Riot API 키 오류 (%s): %s#%s", r.status_code, game_name, tag_line)
            return None, "unauthorized"
        logger.error("Riot Account API 실패 (%s): %s", r.status_code, r.text[:200])
        return None, "api_error"
    except Exception:
        logger.exception("Riot Account API 통신 오류")
        return None, "network_error"


def get_tft_match_ids(puuid: str, count: int = 10) -> list[str]:
    url = f"{_TFT_BASE}/tft/match/v1/matches/by-puuid/{urllib.parse.quote(puuid)}/ids"
    try:
        with httpx.Client(timeout=10) as client:
            r = client.get(url, headers=_headers(), params={"count": count})
        if r.status_code == 200:
            return r.json()
        logger.error("TFT Match IDs API 실패 (%s)", r.status_code)
        return []
    except Exception:
        logger.exception("TFT Match IDs API 통신 오류")
        return []


def get_league_by_puuid(puuid: str) -> list[dict]:
    """puuid로 TFT 리그 엔트리 목록 조회 (queue_type별 tier/LP/wins/losses 등)."""
    url = f"{_PLATFORM_BASE}/tft/league/v1/by-puuid/{urllib.parse.quote(puuid)}"
    try:
        with httpx.Client(timeout=10) as client:
            r = client.get(url, headers=_headers())
        if r.status_code == 200:
            data = r.json()
            return data if isinstance(data, list) else [data]
        logger.error("TFT League by-puuid API 실패 (%s): %s", r.status_code, puuid)
        return []
    except Exception:
        logger.exception("TFT League by-puuid API 통신 오류: %s", puuid)
        return []


def get_tft_match(match_id: str) -> dict | None:
    url = f"{_TFT_BASE}/tft/match/v1/matches/{match_id}"
    try:
        with httpx.Client(timeout=10) as client:
            r = client.get(url, headers=_headers())
        if r.status_code == 200:
            return r.json()
        logger.error("TFT Match API 실패 (%s): %s", r.status_code, match_id)
        return None
    except Exception:
        logger.exception("TFT Match API 통신 오류: %s", match_id)
        return None
