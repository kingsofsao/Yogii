from fastapi import APIRouter, Depends

from backend.api.deps import get_current_user
from backend.domain.risk_policy import RiskPolicy
from backend.ml.inference import inference_service
from backend.schemas import ModelInfoResponse

router = APIRouter(prefix="/model", tags=["Model"])

DISCLAIMER = ("This model was trained only on synthetic, fictional data. Its metrics describe how well it recovers "
              "labels we generated ourselves; they say nothing about real-world fraud detection. Risk scores are "
              "signals for a prototype, not findings that a person or payment is fraudulent.")


@router.get("/info", response_model=ModelInfoResponse, dependencies=[Depends(get_current_user)])
def model_info():
    info = inference_service.info()
    return ModelInfoResponse(**info, risk_bands=RiskPolicy().describe(), disclaimer=DISCLAIMER)
