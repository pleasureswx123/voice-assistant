from pydantic_settings import BaseSettings
from typing import Optional
from functools import lru_cache


class Settings(BaseSettings):
    # API配置
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "YiYuan Voice Assistant"
    
    # 音频配置
    AUDIO_FILE_PATH: str = "temp/input.wav"
    AUDIO_CHUNK_SIZE: int = 100
    AUDIO_VOLUME: int = 10
    AUDIO_PA_PIN: int = 33
    AUDIO_PA_LEVEL: int = 2
    
    # 设备配置
    DEVICE_CONFIG_PATH: str = "config/device_config.json"
    KEY1_GPIO_NUM: int = 28
    
    # 线程配置
    THREAD_STACK_SIZE: int = 256
    
    # 超时配置
    STARTUP_DELAY: int = 5
    RECORD_TIMEOUT: int = 3
    
    # 内存配置
    MEMORY_THRESHOLD: int = 10240  # 10KB
    GC_INTERVAL: int = 5  # 5秒
    
    # 安全配置
    SECRET_KEY: str = "your-secret-key-here"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    
    # API密钥配置
    ASR_API_KEY: Optional[str] = None
    TTS_API_KEY: Optional[str] = None
    
    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings() 