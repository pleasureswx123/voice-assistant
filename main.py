# -*- coding: utf-8 -*-  # Add encoding declaration
import utime
import audio
import gc
from machine import ExtInt
from usr.ark_file import ChatCompletions
from usr.asr_file import coze_asr_transcribe
from usr.tts_file import coze_tts_synthesize
from usr.dev_file import set_device_info, find_user_info
from usr.threading import Queue, Thread, Lock
import ql_fs

# 常量配置
class Config:
    AUDIO_FILE = "/usr/input.wav"
    DEV_CONFIG = "/usr/devConfig.json"
    KEY1_GPIO_NUM = 28
    AUDIO_CHUNK_SIZE = 100
    AUDIO_VOLUME = 10
    AUDIO_PA_PIN = 33
    AUDIO_PA_LEVEL = 2
    THREAD_STACK_SIZE = 256
    STARTUP_DELAY = 5
    RECORD_TIMEOUT = 3
    MEMORY_THRESHOLD = 10240  # 10KB
    GC_INTERVAL = 5  # 5秒

class DeviceManager:
    _instance = None
    _lock = Lock()
    
    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(DeviceManager, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        self.bot_id = None
        self.voice_id = None
        self.user_id = None
        self.tts_queue = Queue()
        self._audio = None
        self._tts = None
        self._audio_lock = Lock()
        self._tts_lock = Lock()
        self._last_gc_time = 0
        self._initialized = True
    
    @property
    def audio(self):
        with self._audio_lock:
            if not self._audio:
                self._audio = audio.Audio(0)
                self._audio.setVolume(Config.AUDIO_VOLUME)
                self._audio.set_pa(Config.AUDIO_PA_PIN, Config.AUDIO_PA_LEVEL)
            return self._audio
    
    @property
    def tts(self):
        with self._tts_lock:
            if not self._tts:
                self._tts = audio.TTS(0)
            return self._tts
    
    def check_memory(self):
        if utime.ticks_diff(utime.ticks_ms(), self._last_gc_time) > Config.GC_INTERVAL * 1000:
            gc.collect()
            self._last_gc_time = utime.ticks_ms()

# 全局设备管理器实例
device_manager = DeviceManager()

class AudioRecorder:
    @staticmethod
    def record():
        print("开始录音...")
        flag = [1]
        recorder = None
        
        def callback(args):
            if args[2] == 3:
                print(f"录音完成，保存到: {Config.AUDIO_FILE}")
                flag[0] = 0
            elif args[2] == -1:
                print("录音失败")
                flag[0] = 0
        
        try:
            recorder = audio.Record()
            recorder.end_callback(callback)
            recorder.start(Config.AUDIO_FILE, Config.RECORD_TIMEOUT)
            
            start_time = utime.ticks_ms()
            while flag[0]:
                if utime.ticks_diff(utime.ticks_ms(), start_time) > Config.RECORD_TIMEOUT * 1000:
                    print("录音超时")
                    if recorder:
                        recorder.stop()
                    break
                utime.sleep_ms(50)
                device_manager.check_memory()
        except Exception as e:
            print(f"录音异常: {str(e)}")
            if recorder:
                try:
                    recorder.stop()
                except:
                    pass
        finally:
            if recorder:
                try:
                    recorder.stop()
                except:
                    pass
            gc.collect()
            try:
                if ql_fs.path_exists(Config.AUDIO_FILE):
                    size = ql_fs.stat(Config.AUDIO_FILE)[6]
                    if size == 0:
                        ql_fs.remove(Config.AUDIO_FILE)
                        print("删除空录音文件")
            except Exception as e:
                print(f"文件清理异常: {str(e)}")
                pass

class DialogueManager:
    @staticmethod
    def process_ai_response(cc):
        response_received = False
        reply = []  # 使用列表存储文本块
        
        try:
            for text_chunk in cc.answer:
                if text_chunk:
                    response_received = True
                    reply.append(text_chunk)
                    if len(reply) > 10:  # 防止列表过大
                        reply = [''.join(reply)]
                    device_manager.check_memory()
            return ''.join(reply) if response_received else None
        except Exception as e:
            print(f"处理回复流时出错: {str(e)}")
            return ''.join(reply) if response_received else None
        finally:
            reply.clear()
            gc.collect()
    
    @staticmethod
    def synthesize_speech(text):
        if not text:
            return None
            
        chunk_audios = []
        try:
            text_length = len(text)
            estimated_chunks = (text_length + Config.AUDIO_CHUNK_SIZE - 1) // Config.AUDIO_CHUNK_SIZE
            if estimated_chunks > 100:  # 防止过大的文本
                print("文本过长，将被截断")
                text = text[:Config.AUDIO_CHUNK_SIZE * 100]
                estimated_chunks = 100
                
            chunk_audios = [None] * estimated_chunks
            chunk_count = 0
            
            for i in range(0, len(text), Config.AUDIO_CHUNK_SIZE):
                chunk = text[i:i+Config.AUDIO_CHUNK_SIZE].strip()
                if chunk:
                    chunk_audios[chunk_count] = coze_tts_synthesize(chunk, device_manager.voice_id)
                    chunk_count += 1
                    device_manager.check_memory()
            
            return b''.join(chunk_audios[:chunk_count])
        except Exception as e:
            print(f"语音合成错误: {str(e)}")
            return None
        finally:
            chunk_audios.clear()
            gc.collect()

def chat_flow():
    gc.enable()
    audio_data = None
    try:
        # 1. 录音
        AudioRecorder.record()
        if not ql_fs.path_exists(Config.AUDIO_FILE):
            print("录音文件不存在")
            return
            
        device_manager.check_memory()
        
        # 2. 语音识别
        print("语音识别中...")
        text = coze_asr_transcribe(Config.AUDIO_FILE)
        if not text or not text.strip():
            print("识别内容为空")
            return
        print(f"识别结果: {text}")
        
        # 3. AI对话
        print("与AI对话中...")
        if not all([device_manager.bot_id, device_manager.user_id]):
            print("设备未完成初始化")
            return
            
        with ChatCompletions(text, device_manager.bot_id, device_manager.user_id) as cc:
            reply = DialogueManager.process_ai_response(cc)
            if not reply:
                print("AI回复为空")
                return
            
            print(f"\nAI完整回复: {reply}")
            
            # 4. 语音合成
            print("开始语音合成...")
            if not device_manager.voice_id:
                print("未设置语音ID")
                return
                
            audio_data = DialogueManager.synthesize_speech(reply)
            if audio_data:
                device_manager.audio.playStream(3, audio_data)
            else:
                print("语音合成失败")
            
    except Exception as e:
        print(f"流程错误: {repr(e)}")
    finally:
        if audio_data:
            del audio_data
        gc.collect()

def set_base_info():
    retry_count = 3
    while retry_count > 0:
        try:
            if ql_fs.path_exists(Config.DEV_CONFIG):
                print("配置已存在")
                find_user()
                if all([device_manager.bot_id, device_manager.voice_id, device_manager.user_id]):
                    break
            else:
                print("配置不存在")
                set_device_info()
            retry_count -= 1
        except Exception as e:
            print(f"设备信息初始化错误: {str(e)}")
            retry_count -= 1
            utime.sleep(1)
    
    if retry_count == 0:
        print("设备初始化失败")

def find_user():
    try:
        data = ql_fs.read_json(Config.DEV_CONFIG)
        print("读取到的设备配置：", data)
        
        app_user_id = data.get("appUserId")
        bot_id = data.get("botId")
        mac_address = data.get("macAddress")
        voice_id = data.get("voiceId")
        
        if not all([app_user_id, bot_id, voice_id]):
            print("缺少必要配置")
            find_user_info(mac_address)
            return
            
        device_manager.bot_id = bot_id
        device_manager.voice_id = voice_id
        device_manager.user_id = app_user_id
        print(f"成功设置参数：bot_id={bot_id}, voice_id={voice_id}, user_id={app_user_id}")
            
    except Exception as e:
        print(f"用户信息获取错误: {str(e)}")

def key1_cb(args):
    try:
        gpio_num, level = args
        if level:
            print("请对AI说话...")
            Thread(target=chat_flow).start(stack_size=Config.THREAD_STACK_SIZE)
        else:
            print("说话结束，等待AI回复...")
    except Exception as e:
        print(f"按键处理错误: {str(e)}")

if __name__ == "__main__":
    try:
        gc.enable()
        utime.sleep(Config.STARTUP_DELAY)
        
        # 初始化设备
        try:
            device_manager.tts.play(1, 0, 2, '设备已开机')
        except Exception as e:
            print(f"开机提示播放失败: {str(e)}")
        
        # 初始化设备信息
        set_base_info()
        
        # 设置按键中断
        key1 = None
        try:
            key1 = ExtInt(
                getattr(ExtInt, f"GPIO{Config.KEY1_GPIO_NUM}"),
                ExtInt.IRQ_RISING_FALLING,
                ExtInt.PULL_PU,
                key1_cb
            )
            key1.enable()
        except Exception as e:
            print(f"按键初始化失败: {str(e)}")
            if key1:
                try:
                    key1.disable()
                except:
                    pass
        
        print("coze ai 启动成功...\n请按下按键S2开始")
        
    except Exception as e:
        print(f"启动错误: {str(e)}")
    finally:
        gc.collect()








