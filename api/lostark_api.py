import os
import urllib.parse
import logging
import httpx

logger = logging.getLogger(__name__)

_BASE_URL = "https://developer-lostark.game.onstove.com"


def fetch_armory_data(character_name: str) -> dict | None:
    api_key = os.getenv("LOSTARK_API_KEY")
    if not api_key:
        logger.error("LOSTARK_API_KEY 환경변수가 설정되지 않았습니다.")
        return None

    encoded_name = urllib.parse.quote(character_name)
    url = f"{_BASE_URL}/armories/characters/{encoded_name}"
    headers = {
        "accept": "application/json",
        "authorization": f"bearer {api_key}",
    }

    try:
        with httpx.Client(timeout=30) as client:
            response = client.get(url, headers=headers)

        if response.status_code == 200:
            return response.json()
        if response.status_code == 404:
            logger.info("캐릭터 없음 (404): %s", character_name)
            return None
        logger.error("Lost Ark API 호출 실패 (%s): %s", response.status_code, response.text[:200])
        return None
    except Exception:
        logger.exception("Lost Ark API 통신 오류: %s", character_name)
        return None
