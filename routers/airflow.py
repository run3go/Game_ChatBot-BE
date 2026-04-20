import logging
from fastapi import APIRouter, HTTPException

from service.airflow_service import AirflowManager, CharacterRequest

logger = logging.getLogger(__name__)
router = APIRouter()
_airflow = AirflowManager()


@router.post("/trigger-update")
async def update_character_data(req: CharacterRequest):
    try:
        result = await _airflow.trigger_dag(
            dag_id="chatbot_response_processor",
            conf={"character_name": req.character_name, "request_source": "fastapi"},
        )
        if result.status_code in [200, 201, 202]:
            return {"status": "success", "run_id": result.json().get("dag_run_id")}
        raise HTTPException(status_code=result.status_code, detail=result.text)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("trigger-update 실패")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dag-status/{run_id}")
async def get_dag_status(run_id: str):
    try:
        status = await _airflow.get_dag_run_status("chatbot_response_processor", run_id)
        return {"status": status}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
