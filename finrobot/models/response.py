from typing import Dict, Any, Optional, Union
from pydantic import BaseModel, validator

class ResponseModel(BaseModel):
    response: Union[Dict[str, Any], str]

    @validator('response')
    def validate_response(cls, v):
        if isinstance(v, str):
            try:
                # Try to parse string as JSON if it looks like a dictionary
                if v.strip().startswith('{') and v.strip().endswith('}'):
                    import json
                    return json.loads(v)
            except:
                pass
        return v

    class Config:
        arbitrary_types_allowed = True 