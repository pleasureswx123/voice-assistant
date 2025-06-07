from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.endpoints import audio
import logging
import sys

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('app.log')
    ]
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 在生产环境中应该设置具体的域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(
    audio.router,
    prefix=f"{settings.API_V1_STR}/audio",
    tags=["audio"]
)

@app.on_event("startup")
async def startup_event():
    """应用启动时的初始化操作"""
    try:
        from app.services.audio_manager import audio_manager
        from app.services.asr_service import asr_service
        from app.services.tts_service import tts_service
        
        # 初始化各个服务
        await audio_manager.initialize_audio()
        await asr_service.initialize()
        await tts_service.initialize()
        
        logger.info("应用服务初始化完成")
    except Exception as e:
        logger.error(f"应用启动初始化失败: {str(e)}")
        raise HTTPException(status_code=500, detail="应用初始化失败")

@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭时的清理操作"""
    try:
        from app.services.asr_service import asr_service
        from app.services.tts_service import tts_service
        
        # 关闭各个服务
        await asr_service.close()
        await tts_service.close()
        
        logger.info("应用服务已关闭")
    except Exception as e:
        logger.error(f"应用关闭清理失败: {str(e)}")

@app.get("/")
async def root():
    """根路径响应"""
    return {
        "app_name": settings.PROJECT_NAME,
        "version": "1.0.0",
        "status": "running"
    }

@app.get("/health")
async def health_check():
    """健康检查端点"""
    return {"status": "healthy"} 