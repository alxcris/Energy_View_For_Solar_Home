from pydantic import BaseModel
from typing import Optional, List


class RecommendationResponse(BaseModel):
    site_id: str
    recommendations: List[str]
    summary_data: Optional[dict] = None