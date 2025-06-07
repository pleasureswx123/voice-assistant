from fastapi import APIRouter, HTTPException, BackgroundTasks
from typing import List
from app.services.audio_manager import audio_manager
from app.services.asr_service import asr_service
from app.services.tts_service import tts_service
from pydantic import BaseModel

router = APIRouter()

class AudioDeviceInfo(BaseModel):
    id: str
    name: str
    type: str

class VoiceInfo(BaseModel):
    id: str
    name: str
    language: str
    gender: str

class TextToSpeechRequest(BaseModel):
    text: str
    voice_id: str = None

@router.post("/record/start")
async def start_recording(duration: int = None):
    """开始录音"""
    file_path = await audio_manager.start_recording(duration)
    return {"status": "success", "file_path": file_path}

@router.post("/record/stop")
async def stop_recording():
    """停止录音"""
    await audio_manager.stop_recording()
    return {"status": "success"}

@router.post("/transcribe")
async def transcribe_audio(file_path: str):
    """语音识别"""
    text = await asr_service.transcribe(file_path)
    return {"text": text}

@router.post("/synthesize")
async def synthesize_text(request: TextToSpeechRequest):
    """文字转语音"""
    audio_data = await tts_service.synthesize(request.text, request.voice_id)
    return {"audio_data": audio_data}

@router.get("/devices", response_model=List[AudioDeviceInfo])
async def get_audio_devices():
    """获取音频设备列表"""
    return await audio_manager.get_audio_devices()

@router.get("/voices", response_model=List[VoiceInfo])
async def get_available_voices():
    """获取可用语音列表"""
    return await tts_service.get_available_voices()

@router.post("/volume/{level}")
async def set_volume(level: int):
    """设置音量"""
    await audio_manager.set_volume(level)
    return {"status": "success"}

@router.get("/health")
async def check_health():
    """检查服务健康状态"""
    asr_health = await asr_service.check_health()
    tts_health = await tts_service.check_health()
    
    return {
        "status": "healthy" if asr_health and tts_health else "unhealthy",
        "services": {
            "asr": "healthy" if asr_health else "unhealthy",
            "tts": "healthy" if tts_health else "unhealthy"
        }
    } 