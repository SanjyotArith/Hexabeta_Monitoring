from datetime import datetime
from typing import Optional, Dict
from pydantic import BaseModel, Field

class ApiCheckBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    url: str
    request_method: str = "GET"
    headers: Optional[Dict[str, str]] = None
    request_payload: Optional[str] = None
    expected_status_code: int = 200
    expected_response_match: Optional[str] = None
    check_interval_seconds: int = Field(60, ge=5)
    timeout_seconds: int = Field(10, ge=1, le=60)
    is_active: bool = True

class ApiCheckCreate(ApiCheckBase):
    pass

class ApiCheckUpdate(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    request_method: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    request_payload: Optional[str] = None
    expected_status_code: Optional[int] = None
    expected_response_match: Optional[str] = None
    check_interval_seconds: Optional[int] = Field(None, ge=5)
    timeout_seconds: Optional[int] = Field(None, ge=1, le=60)
    is_active: Optional[bool] = None

class ApiCheckResponse(ApiCheckBase):
    id: int
    environment_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ApiCheckHistoryResponse(BaseModel):
    id: int
    api_check_id: int
    timestamp: datetime
    is_up: bool
    response_time_ms: Optional[int] = None
    status_code: Optional[int] = None
    error_message: Optional[str] = None

    class Config:
        from_attributes = True
