import os
import httpx
from datetime import datetime, timezone
from pydantic import BaseModel


class CharacterRequest(BaseModel):
    character_name: str


class AirflowManager:
    def __init__(self):
        self.base_url = os.getenv("AIRFLOW_BASE_URL")
        self.username = os.getenv("AIRFLOW_USERNAME")
        self.password = os.getenv("AIRFLOW_PASSWORD")

    async def trigger_dag(self, dag_id: str, conf: dict = None):
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        payload = {"logical_date": now_iso, "conf": conf or {}}

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/api/v1/dags/{dag_id}/dagRuns",
                json=payload,
                auth=(self.username, self.password),
            )

        return response

    async def get_dag_run_status(self, dag_id: str, dag_run_id: str) -> str:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/api/v1/dags/{dag_id}/dagRuns/{dag_run_id}",
                auth=(self.username, self.password),
            )
        response.raise_for_status()
        return response.json().get("state", "unknown")
