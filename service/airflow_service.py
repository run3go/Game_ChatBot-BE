import os
import time
import requests
from datetime import datetime, timezone
from pydantic import BaseModel


class CharacterRequest(BaseModel):
    character_name: str


class AirflowManager:
    def __init__(self):
        self.base_url = os.getenv("AIRFLOW_BASE_URL")
        self.username = os.getenv("AIRFLOW_USERNAME")
        self.password = os.getenv("AIRFLOW_PASSWORD")
        self._access_token = None
        self._token_expires_at = 0

    def _fetch_new_token(self):
        try:
            resp = requests.post(
                f"{self.base_url}/auth/token",
                json={"username": self.username, "password": self.password}
            )
            resp.raise_for_status()
            self._access_token = resp.json()["access_token"]
            self._token_expires_at = time.time() + 3000
            return self._access_token
        except Exception as e:
            print(f"토큰 발급 에러: {e}")
            return None

    def get_token(self):
        if not self._access_token or time.time() > (self._token_expires_at - 300):
            return self._fetch_new_token()
        return self._access_token

    def trigger_dag(self, dag_id: str, conf: dict = None, _retry: bool = True):
        token = self.get_token()
        if not token:
            raise Exception("Airflow 인증 토큰을 확보할 수 없습니다.")

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        payload = {"logical_date": now_iso, "conf": conf or {}}

        response = requests.post(
            f"{self.base_url}/api/v2/dags/{dag_id}/dagRuns",
            json=payload,
            headers=headers
        )

        if response.status_code == 401 and _retry:
            print("토큰 만료 감지, 재갱신 후 재시도합니다.")
            self._fetch_new_token()
            return self.trigger_dag(dag_id, conf, _retry=False)

        return response
