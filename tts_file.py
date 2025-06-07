import request
import gc
import audio
from usr.threading import Lock

class CozeTTSConfig:
    # 配置常量
    API_KEY = 'pat_4E5LC6KuSUVLZzv0kVbEdGuyL5ala8ykM0w4ZNVeLYk1spTCljpnkaVvF0FERiYS'
    TTS_URL = 'https://api.coze.cn/v1/audio/speech'
    VOICE_ID = '7468512265151463451'
    
    # 音频参数
    SAMPLE_RATE = 8000
    CHUNK_SIZE = 8192  # 8KB 块大小
    MAX_RETRIES = 3    # 最大重试次数
    RETRY_DELAY = 1    # 重试延迟(秒)
    
    # 音频播放参数
    DEFAULT_VOLUME = 7
    PA_PIN = 33
    PA_CHANNEL = 2
    PLAYER_ID = 3

class CozeTTSError(Exception):
    """TTS 相关异常"""
    def __init__(self, message, error_type=None, status_code=None):
        super().__init__(message)
        self.error_type = error_type
        self.status_code = status_code

class TTSManager:
    _instance = None
    _lock = Lock()
    
    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(TTSManager, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._request_lock = Lock()
        self._audio_lock = Lock()
        self._audio_player = None
    
    def _get_audio_player(self):
        """获取或初始化音频播放器"""
        if self._audio_player is None:
            with self._audio_lock:
                if self._audio_player is None:
                    self._audio_player = audio.Audio(0)
                    self._audio_player.setVolume(CozeTTSConfig.DEFAULT_VOLUME)
                    self._audio_player.set_pa(
                        CozeTTSConfig.PA_PIN,
                        CozeTTSConfig.PA_CHANNEL
                    )
        return self._audio_player
    
    def _prepare_request_data(self, text, voice_id):
        """准备请求数据"""
        headers = {
            "Authorization": f"Bearer {CozeTTSConfig.API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "input": text,
            "voice_id": voice_id or CozeTTSConfig.VOICE_ID,
            "response_format": "mp3",
            "sample_rate": CozeTTSConfig.SAMPLE_RATE
        }
        return headers, payload
    
    def _handle_response(self, resp):
        """处理响应数据"""
        if resp.status_code != 200:
            raise CozeTTSError(
                f"HTTP错误: {resp.status_code}",
                error_type="http_error",
                status_code=resp.status_code
            )
        
        audio_content = bytearray()
        try:
            # 分块读取响应内容
            for chunk in resp.content:
                audio_content.extend(chunk)
                gc.collect()  # 及时清理内存
        except TypeError:
            # 如果content不是生成器，直接使用
            audio_content = resp.content
            
        return bytes(audio_content)
    
    def synthesize(self, text, voice_id=None, retry_count=0):
        """
        文本转语音主函数
        :param text: 要合成的文本
        :param voice_id: 语音ID
        :param retry_count: 当前重试次数
        :return: 音频二进制数据
        """
        if retry_count >= CozeTTSConfig.MAX_RETRIES:
            raise CozeTTSError("超过最大重试次数", error_type="max_retries_exceeded")
        
        try:
            headers, payload = self._prepare_request_data(text, voice_id)
            
            with self._request_lock:
                try:
                    # 设置请求超时
                    resp = request.post(
                        CozeTTSConfig.TTS_URL,
                        headers=headers,
                        json=payload,
                        stream=True,
                        timeout=10  # 10秒超时
                    )
                    return self._handle_response(resp)
                except (request.RequestError, request.RequestTimeoutError) as e:
                    if retry_count < CozeTTSConfig.MAX_RETRIES:
                        import utime
                        utime.sleep(CozeTTSConfig.RETRY_DELAY)
                        return self.synthesize(
                            text,
                            voice_id,
                            retry_count + 1
                        )
                    raise CozeTTSError(
                        f"请求失败: {str(e)}",
                        error_type="request_error"
                    )
                finally:
                    gc.collect()
        
        except Exception as e:
            raise CozeTTSError(
                f"未知错误: {str(e)}",
                error_type="unknown_error"
            )
    
    def play_audio(self, audio_data):
        """
        播放音频数据
        :param audio_data: 音频二进制数据
        :return: 播放结果
        """
        with self._audio_lock:
            player = self._get_audio_player()
            try:
                # 检查是否有正在播放的音频
                try:
                    if player.getState() == 1:  # 1表示正在播放
                        player.stop()
                        utime.sleep_ms(100)  # 等待停止完成
                except:
                    pass
                
                return player.playStream(
                    CozeTTSConfig.PLAYER_ID,
                    audio_data
                )
            except Exception as e:
                raise CozeTTSError(
                    f"音频播放失败: {str(e)}",
                    error_type="playback_error"
                )
            finally:
                gc.collect()

# 全局TTS管理器实例
tts_manager = TTSManager()

def coze_tts_synthesize(text, voice_id=None):
    """
    对外暴露的语音合成接口
    :param text: str, 要合成的文本
    :param voice_id: str, 可选，语音ID
    :return: bytes, 音频内容
    """
    return tts_manager.synthesize(text, voice_id)

def play_synthesized_audio(audio_data):
    """
    对外暴露的音频播放接口
    :param audio_data: bytes, 音频数据
    :return: 播放结果
    """
    return tts_manager.play_audio(audio_data)

if __name__ == "__main__":
    text = "播放音频，响应状态码"
    voice_id = CozeTTSConfig.VOICE_ID
    
    try:
        # 合成音频
        audio_bytes = coze_tts_synthesize(text, voice_id)
        print(f"音频数据长度: {len(audio_bytes)} 字节")
        
        # 播放音频
        print("开始播放音频...")
        result = play_synthesized_audio(audio_bytes)
        print(f"播放结果: {result}")
        
    except CozeTTSError as e:
        print(f"TTS处理失败 [{e.error_type}]: {str(e)}")
    except Exception as e:
        print(f"系统错误: {str(e)}")
    finally:
        gc.collect()


