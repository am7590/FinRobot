from pydantic import BaseModel
from typing import Dict, Any, Optional

class ResponseModel(BaseModel):
    response: Dict[str, Any]

    class Config:
        arbitrary_types_allowed = True 