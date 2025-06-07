import request
import modem
import ql_fs
import audio
import gc
from usr.threading import Lock

class DeviceConfig:
    """设备配置类"""
    # API配置
    REQUEST_URL = 'https://mnsj.versekeys.com/prod-api/system/management'
    REQUEST_URL2 = 'https://mnsj.versekeys.com/prod-api/system/management/list'
    
    # 文件路径
    CONFIG_FILE = "/usr/devConfig.json"
    
    # 音频配置
    DEFAULT_VOLUME = 10
    PLAYER_ID = 1
    PA_PIN = 0
    PA_CHANNEL = 2
    
    # 提示音配置
    MESSAGES = {
        "DEVICE_REGISTERED": "设备已备案",
        "BIND_BOT": "请打开APP分配智能体",
        "BIND_SUCCESS": "智能体绑定成功，关闭电源后重新启动"
    }

class DeviceError(Exception):
    """设备相关异常"""
    def __init__(self, message, error_type=None):
        super().__init__(message)
        self.error_type = error_type

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
        self._initialized = True
        
        try:
            self.audio = audio.Audio(0)
            self.audio.setVolume(DeviceConfig.DEFAULT_VOLUME)
            self.tts = audio.TTS(0)
        except Exception as e:
            raise DeviceError(f"音频初始化失败: {str(e)}", "audio_init_error")
    
    def _get_device_info(self):
        """获取设备信息"""
        try:
            return {
                "imei": modem.getDevImei(),
                "model": modem.getDevModel(),
                "sn": modem.getDevSN(),
                "fw_version": modem.getDevFwVersion(),
                "product_id": modem.getDevProductId()
            }
        except Exception as e:
            raise DeviceError(f"获取设备信息失败: {str(e)}", "device_info_error")
    
    def _save_config(self, data):
        """保存配置文件"""
        try:
            # 验证必要的字段
            required_fields = ["macAddress"]
            if "appUserId" in data:
                required_fields.extend(["botId", "voiceId"])
            
            for field in required_fields:
                if field not in data or not data[field]:
                    raise DeviceError(
                        f"缺少必要配置字段: {field}",
                        "invalid_config"
                    )
            
            # 创建临时文件
            temp_file = DeviceConfig.CONFIG_FILE + ".tmp"
            try:
                ql_fs.touch(temp_file, data)
                
                # 如果原文件存在，先删除
                if ql_fs.path_exists(DeviceConfig.CONFIG_FILE):
                    ql_fs.remove(DeviceConfig.CONFIG_FILE)
                
                # 重命名临时文件
                ql_fs.rename(temp_file, DeviceConfig.CONFIG_FILE)
                
            except Exception as e:
                # 清理临时文件
                if ql_fs.path_exists(temp_file):
                    try:
                        ql_fs.remove(temp_file)
                    except:
                        pass
                raise e
                
        except Exception as e:
            raise DeviceError(f"保存配置失败: {str(e)}", "save_config_error")
    
    def _load_config(self):
        """加载配置文件"""
        try:
            if not ql_fs.path_exists(DeviceConfig.CONFIG_FILE):
                raise DeviceError("配置文件不存在", "file_not_found")
            
            data = ql_fs.read_json(DeviceConfig.CONFIG_FILE)
            if not isinstance(data, dict):
                raise DeviceError("配置文件格式错误", "invalid_format")
            
            # 验证必要的字段
            if "macAddress" not in data:
                raise DeviceError("配置文件缺少必要字段", "missing_field")
            
            return data
            
        except Exception as e:
            if not isinstance(e, DeviceError):
                raise DeviceError(f"读取配置失败: {str(e)}", "load_config_error")
            raise
    
    def _play_tts(self, message):
        """播放TTS语音"""
        try:
            self.tts.play(
                DeviceConfig.PLAYER_ID,
                DeviceConfig.PA_PIN,
                DeviceConfig.PA_CHANNEL,
                message
            )
        except Exception as e:
            raise DeviceError(f"TTS播放失败: {str(e)}", "tts_error")
    
    def register_device(self):
        """注册设备信息"""
        try:
            info = self._get_device_info()
            
            print("获取到的设备信息:")
            print(f"IMEI: {info['imei']}")
            print(f"型号: {info['model']}")
            print(f"SN: {info['sn']}")
            print(f"固件版本: {info['fw_version']}")
            print(f"产品ID: {info['product_id']}")
            
            payload = {
                "remark": "556654654655456",
                "deviceName": info["model"],
                "macAddress": info["imei"],
                "sn": info["sn"],
                "ip": info["product_id"]
            }
            
            resp = request.post(
                DeviceConfig.REQUEST_URL,
                headers={"Content-Type": "application/json"},
                json=payload
            )
            
            print("Response Body:", resp.json())
            
            # 保存设备配置
            self._save_config({"macAddress": info["imei"]})
            
            # 播放提示音
            self._play_tts(DeviceConfig.MESSAGES["DEVICE_REGISTERED"])
            
        except Exception as e:
            if not isinstance(e, DeviceError):
                raise DeviceError(f"设备注册失败: {str(e)}", "register_error")
            raise
        finally:
            gc.collect()
    
    def find_user_info(self, mac_address):
        """查找用户信息"""
        try:
            # 构建请求URL
            url = f"{DeviceConfig.REQUEST_URL2}?pageNum=1&pageSize=10&macAddress={mac_address}"
            
            # 发送请求
            resp = request.get(
                url,
                headers={"Content-Type": "application/json"}
            )
            
            # 解析响应数据
            data = resp.json()
            if not data.get("rows"):
                raise DeviceError("未找到用户信息", "user_not_found")
                
            row = data["rows"][0]
            app_user_id = row.get("appUserId")
            bot_id = row.get("cozeBotId")
            voice_id = row.get("wifiStatus")
            
            print(f"AppUserId: {app_user_id}")
            print(f"BotId: {bot_id}")
            print(f"VoiceId: {voice_id}")
            
            # 更新配置
            config = self._load_config()
            
            if app_user_id:
                config["appUserId"] = app_user_id
            if bot_id:
                config["botId"] = bot_id
            if voice_id:
                config["voiceId"] = voice_id
                
            self._save_config(config)
            
            # 根据状态播放提示音
            if app_user_id and not bot_id:
                self._play_tts(DeviceConfig.MESSAGES["BIND_BOT"])
            elif app_user_id and bot_id:
                self._play_tts(DeviceConfig.MESSAGES["BIND_SUCCESS"])
                
        except Exception as e:
            if not isinstance(e, DeviceError):
                raise DeviceError(f"查找用户信息失败: {str(e)}", "find_user_error")
            raise
        finally:
            gc.collect()

# 全局设备管理器实例
device_manager = DeviceManager()

if __name__ == "__main__":
    try:
        #device_manager.register_device()
        device_manager.find_user_info("860116075787112")
    except DeviceError as e:
        print(f"设备错误 [{e.error_type}]: {str(e)}")
    except Exception as e:
        print(f"系统错误: {str(e)}")
    finally:
        gc.collect()






