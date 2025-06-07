import request
import ujson as json
import gc
from usr.threading import Lock
import os

class CozeASRConfig:
    # 配置常量
    API_KEY = 'pat_4E5LC6KuSUVLZzv0kVbEdGuyL5ala8ykM0w4ZNVeLYk1spTCljpnkaVvF0FERiYS'
    ASR_URL = 'https://api.coze.cn/v1/audio/transcriptions'
    CHUNK_SIZE = 8192  # 8KB 块大小
    MAX_RETRIES = 3    # 最大重试次数
    RETRY_DELAY = 1    # 重试延迟(秒)
    
    # 支持的音频格式
    CONTENT_TYPES = {
        '.wav': 'audio/wav',
        '.mp3': 'audio/mpeg',
        '.ogg': 'audio/ogg'
    }

class CozeASRError(Exception):
    """ASR 相关异常"""
    def __init__(self, message, error_type=None, status_code=None):
        super().__init__(message)
        self.error_type = error_type
        self.status_code = status_code

class ASRManager:
    _instance = None
    _lock = Lock()
    
    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(ASRManager, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._request_lock = Lock()
    
    @staticmethod
    def guess_content_type(filename):
        """获取文件的Content-Type"""
        ext = filename.lower()[filename.rfind('.'):]
        return CozeASRConfig.CONTENT_TYPES.get(ext, 'application/octet-stream')
    
    def _prepare_request_data(self, audio_file_path):
        """准备请求数据"""
        boundary = '----WebKitFormBoundary7MA4YWxkTrZu0gW'
        filename = audio_file_path.split('/')[-1]
        content_type = self.guess_content_type(filename)
        
        headers = {
            "Authorization": f"Bearer {CozeASRConfig.API_KEY}",
            "Content-Type": f"multipart/form-data; boundary={boundary}"
        }
        
        # 构建multipart表单数据
        form_data = (
            f'--{boundary}\r\n'
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f'Content-Type: {content_type}\r\n\r\n'
        ).encode()
        
        return boundary, headers, form_data
    
    def _handle_response(self, resp):
        """处理响应数据"""
        if resp.status_code != 200:
            raise CozeASRError(
                f"HTTP错误: {resp.status_code}",
                error_type="http_error",
                status_code=resp.status_code
            )
        
        try:
            data = resp.json()
        except Exception as e:
            raise CozeASRError(
                f"JSON解析错误: {str(e)}",
                error_type="parse_error"
            )
        
        if data.get('code', -1) != 0:
            raise CozeASRError(
                f"业务错误: {data.get('msg', '')}",
                error_type="business_error"
            )
        
        return data.get('data', {}).get('text', '')
    
    def transcribe(self, audio_file_path, retry_count=0):
        """
        音频转写主函数
        :param audio_file_path: 音频文件路径
        :param retry_count: 当前重试次数
        :return: 识别文本
        """
        if retry_count >= CozeASRConfig.MAX_RETRIES:
            raise CozeASRError("超过最大重试次数", error_type="max_retries_exceeded")
        
        try:
            # 验证文件存在性和大小
            if not os.path.exists(audio_file_path):
                raise CozeASRError(
                    "音频文件不存在",
                    error_type="file_not_found"
                )
            
            file_size = os.path.getsize(audio_file_path)
            if file_size == 0:
                raise CozeASRError(
                    "音频文件为空",
                    error_type="empty_file"
                )
            
            # 验证文件格式
            ext = audio_file_path.lower()[audio_file_path.rfind('.'):]
            if ext not in CozeASRConfig.CONTENT_TYPES:
                raise CozeASRError(
                    f"不支持的音频格式: {ext}",
                    error_type="unsupported_format"
                )
            
            boundary, headers, form_data = self._prepare_request_data(audio_file_path)
            
            with self._request_lock:
                with open(audio_file_path, 'rb') as f:
                    # 分块读取文件
                    total_size = 0
                    while True:
                        chunk = f.read(CozeASRConfig.CHUNK_SIZE)
                        if not chunk:
                            break
                        form_data += chunk
                        total_size += len(chunk)
                        
                        # 定期清理内存
                        if total_size % (CozeASRConfig.CHUNK_SIZE * 10) == 0:
                            gc.collect()
                    
                    # 添加结束边界
                    form_data += f'\r\n--{boundary}--\r\n'.encode()
                    
                    try:
                        resp = request.post(
                            CozeASRConfig.ASR_URL,
                            headers=headers,
                            data=form_data,
                            timeout=30  # 30秒超时
                        )
                        return self._handle_response(resp)
                    except (request.RequestError, request.RequestTimeoutError) as e:
                        if retry_count < CozeASRConfig.MAX_RETRIES:
                            import utime
                            utime.sleep(CozeASRConfig.RETRY_DELAY)
                            return self.transcribe(
                                audio_file_path,
                                retry_count + 1
                            )
                        raise CozeASRError(
                            f"请求失败: {str(e)}",
                            error_type="request_error"
                        )
                    finally:
                        gc.collect()
        
        except (OSError, IOError) as e:
            raise CozeASRError(
                f"文件操作错误: {str(e)}",
                error_type="file_error"
            )
        except Exception as e:
            if not isinstance(e, CozeASRError):
                raise CozeASRError(
                    f"未知错误: {str(e)}",
                    error_type="unknown_error"
                )
            raise

# 全局ASR管理器实例
asr_manager = ASRManager()

def coze_asr_transcribe(audio_file_path):
    """
    对外暴露的转写接口
    :param audio_file_path: str, 音频文件路径
    :return: str, 识别文本
    """
    return asr_manager.transcribe(audio_file_path)

if __name__ == "__main__":
    audio_path = "/usr/input.wav"
    try:
        text = coze_asr_transcribe(audio_path)
        print("识别结果:", text)
    except CozeASRError as e:
        print(f"识别失败 [{e.error_type}]: {str(e)}")
    except Exception as e:
        print(f"系统错误: {str(e)}")
    finally:
        gc.collect()



