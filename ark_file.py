import ujson as json
import request
import gc
from usr.threading import Lock
import utime

class ARKConfig:
    # API配置
    CHAT_COMPLETIONS_POST_URL = 'https://api.coze.cn/v3/chat'
    BOT_ID = '7491118368578568192'
    API_KEY = 'pat_4E5LC6KuSUVLZzv0kVbEdGuyL5ala8ykM0w4ZNVeLYk1spTCljpnkaVvF0FERiYS'
    USER_ID = '1'
    
    # 请求配置
    MAX_RETRIES = 3
    RETRY_DELAY = 1  # 秒
    CHUNK_SIZE = 4096  # 4KB
    BUFFER_SIZE = 8192  # 8KB
    
    # 事件类型
    EVENT_MESSAGE_DELTA = "conversation.message.delta"
    EVENT_DONE = "[DONE]"

class ChatCompletionsError(Exception):
    """聊天相关异常"""
    def __init__(self, message, error_type=None, status_code=None):
        super().__init__(message)
        self.error_type = error_type
        self.status_code = status_code

class ChatManager:
    _instance = None
    _lock = Lock()
    
    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(ChatManager, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._request_lock = Lock()
        self._buffer = bytearray(ARKConfig.BUFFER_SIZE)
    
    def _prepare_request_data(self, question, bot_id, user_id):
        """准备请求数据"""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {ARKConfig.API_KEY}"
        }
        
        payload = {
            "bot_id": bot_id or ARKConfig.BOT_ID,
            "user_id": user_id or ARKConfig.USER_ID,
            "stream": True,
            "additional_messages": [
                {
                    "content": question,
                    "content_type": "text",
                    "role": "user",
                    "type": "question"
                }
            ],
            "parameters": {}
        }
        
        return headers, payload
    
    def _process_event(self, event_line, data_line):
        """处理事件数据"""
        try:
            if data_line == ARKConfig.EVENT_DONE:
                return None, True
            
            data = json.loads(data_line)
            event_type = event_line.strip()
            
            if event_type == ARKConfig.EVENT_MESSAGE_DELTA:
                if data.get("role") == "assistant":
                    content = data.get("content", "")
                    msg_type = data.get("type", "")
                    if content and msg_type == "answer":
                        return content, False
            
            return None, False
            
        except json.JSONDecodeError as e:
            raise ChatCompletionsError(
                f"JSON解析错误: {str(e)}",
                error_type="json_error"
            )
        except Exception as e:
            raise ChatCompletionsError(
                f"事件处理错误: {str(e)}",
                error_type="event_error"
            )
    
    def _handle_response(self, resp, retry_count=0):
        """处理响应数据"""
        if resp.status_code != 200:
            raise ChatCompletionsError(
                f"HTTP错误: {resp.status_code}",
                error_type="http_error",
                status_code=resp.status_code
            )
        
        raw = ""
        is_done = False
        last_data_time = utime.ticks_ms()
        timeout = 30000  # 30秒超时
        
        try:
            for chunk in resp.text:
                current_time = utime.ticks_ms()
                if utime.ticks_diff(current_time, last_data_time) > timeout:
                    raise ChatCompletionsError(
                        "响应数据接收超时",
                        error_type="timeout_error"
                    )
                
                raw += chunk
                while True:
                    line_index = raw.find("\n\n")
                    if line_index == -1:
                        break
                    
                    block = raw[:line_index].strip()
                    raw = raw[line_index + 2:]
                    
                    if not block:
                        continue
                    
                    lines = block.split('\n')
                    event_line = None
                    data_line = None
                    
                    for line in lines:
                        line = line.strip()
                        if not line:
                            continue
                        
                        if line.startswith("event:"):
                            event_line = line[6:].strip()
                        elif line.startswith("data:"):
                            data_line = line[5:].strip()
                    
                    if event_line and data_line:
                        content, is_done = self._process_event(event_line, data_line)
                        if content:
                            yield content
                            last_data_time = current_time  # 更新最后接收数据的时间
                        if is_done:
                            return
                
                if len(raw) > ARKConfig.BUFFER_SIZE:
                    raw = raw[-ARKConfig.BUFFER_SIZE:]  # 保留最后的缓冲区数据
                gc.collect()  # 定期清理内存
                
        except Exception as e:
            if retry_count < ARKConfig.MAX_RETRIES:
                utime.sleep(ARKConfig.RETRY_DELAY)
                yield from self._handle_response(resp, retry_count + 1)
            else:
                raise ChatCompletionsError(
                    f"响应处理错误: {str(e)}",
                    error_type="response_error"
                )
    
    def chat(self, question, bot_id=None, user_id=None):
        """
        聊天主函数
        :param question: 问题内容
        :param bot_id: 机器人ID
        :param user_id: 用户ID
        :return: 生成器，产生回复内容
        """
        if not isinstance(question, str) or not question.strip():
            raise ChatCompletionsError(
                "问题不能为空",
                error_type="invalid_input"
            )
        
        try:
            headers, payload = self._prepare_request_data(
                question.strip(),
                bot_id,
                user_id
            )
            
            with self._request_lock:
                try:
                    resp = request.post(
                        ARKConfig.CHAT_COMPLETIONS_POST_URL,
                        headers=headers,
                        json=payload
                    )
                    yield from self._handle_response(resp)
                except request.RequestError as e:
                    raise ChatCompletionsError(
                        f"请求失败: {str(e)}",
                        error_type="request_error"
                    )
                finally:
                    gc.collect()
                    
        except Exception as e:
            if not isinstance(e, ChatCompletionsError):
                raise ChatCompletionsError(
                    f"未知错误: {str(e)}",
                    error_type="unknown_error"
                )
            raise

# 全局聊天管理器实例
chat_manager = ChatManager()

class ChatCompletions:
    """聊天会话类"""
    def __init__(self, question, bot_id=None, user_id=None):
        self.question = question
        self.bot_id = bot_id
        self.user_id = user_id
        self.resp = None
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.resp:
            self.resp.close()
        gc.collect()
    
    @property
    def answer(self):
        """获取回答生成器"""
        return chat_manager.chat(
            self.question,
            self.bot_id,
            self.user_id
        )

if __name__ == "__main__":
    try:
        with ChatCompletions("你好啊", "7489339376636477440", "107") as cc:
            response_received = False
            print("开始对话...")
            
            for text in cc.answer:
                response_received = True
                print(f"收到回复: {text}")
            
            if not response_received:
                print("未收到任何回复")
                
    except ChatCompletionsError as e:
        print(f"对话失败 [{e.error_type}]: {str(e)}")
    except Exception as e:
        print(f"系统错误: {str(e)}")
    finally:
        gc.collect()





