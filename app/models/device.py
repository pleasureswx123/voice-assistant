from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class DeviceBase(BaseModel):
    bot_id: Optional[str] = None
    voice_id: Optional[str] = None
    user_id: Optional[str] = None


class DeviceCreate(DeviceBase):
    pass


class DeviceUpdate(DeviceBase):
    pass


class DeviceInDB(DeviceBase):
    id: int
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        from_attributes = True


class Device(DeviceInDB):
    pass


class DeviceInfo(BaseModel):
    device_id: str
    name: str
    status: str
    last_active: datetime = Field(default_factory=datetime.utcnow)
    battery_level: Optional[float] = None
    firmware_version: Optional[str] = None
    
    class Config:
        from_attributes = True 