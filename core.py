from DashscopeApiAsr import DashscopeApiAsr, DashscopeCustomRecognitionCallback, RecognitionResult
from AlicloudApiTranslator import AlicloudApiTranslator
import json
import pythonosc
import pythonosc.udp_client
import logging
import asyncio
import pyaudio
import multiprocessing
logger = logging.getLogger("VRChatParaformerAsr")


class Setting:
    def __init__(self) -> None:
        # Setting ====
        # ui
        self.dark_mode = True
        # vrchat: should recreate `VRChatOscCallback` and restart `DashscopeApiAsr` after change
        self.vrchat_ip = r"127.0.0.1"
        self.vrchat_port = 9000
        # osc
        self.osc_bypass_keyboard = True
        self.osc_enableSFX = True
        # translate
        self.enable_translate = False
        self.src_lang = "zh" # zh, en, ja, ko # https://help.aliyun.com/zh/machine-translation/support/supported-languages-and-codes?spm=api-workbench.api_explorer.0.0.3d374eecSIT7xn
        self.dst_lang = "ja"
        # microphone: should recreate `MicCollector` after change
        self.micro_device_id = 3
        # dashscope api: should restart `DashscopeApiAsr` after change
        self.api_key = ""
        self.disfluency_removal_enabled = False
        # alicloud api: should restart `AlicloudApiTranslator` after change
        self.alicloud_access_key_id = ""
        self.alicloud_access_key_secret = ""
        self.alicloud_endpoint = 'mt.cn-hangzhou.aliyuncs.com'

    def copy_from(self, another: "Setting") -> None:
        for key, value in another.__dict__.items():
            self.__dict__[key] = value

    def serialize(self, indent=None) -> str:
        return json.dumps(self.__dict__, indent=indent)

    def deserialize(self, s: str) -> None:
        d = json.loads(s)
        for key, value in d.items():
            self.__dict__[key] = value

class VRChatOscCallback(DashscopeCustomRecognitionCallback):
    def __init__(self, setting: Setting, translator: AlicloudApiTranslator = None):
        self.setting = setting
        self.translator = translator
        self.osc_client = pythonosc.udp_client.SimpleUDPClient(self.setting.vrchat_ip, self.setting.vrchat_port)
        self.last_text = ""
        self.last_translated_text = ""

    def on_open(self) -> None:
        logger.info('RecognitionCallback open.')

    def on_close(self) -> None:
        logger.info('RecognitionCallback close.')

    def on_response_timeout(self, result: RecognitionResult):
        logger.info("RecognitionCallback is shutdown by the ASR server.")

    def on_error(self, result: RecognitionResult) -> None:
        logger.error(result)

    def on_complete(self) -> None:
        pass

    def on_event(self, result: RecognitionResult) -> None:
        try:
            # Get full sentence
            self.osc_client.send_message("/chatbox/typing", [True])
            sen = result.get_sentence()
            logger.debug(f'RecognitionCallback sentence: {sen}', )
            # If the sentence is completed, update last_text
            if result.is_sentence_end(sen):
                # Extract the text
                cur_text = sen["text"]
                logger.info(f"[Transcribed] {cur_text}")
                # If translator is presented, translate it
                cur_translated_text = ""
                if self.translator:
                    cur_translated_text = self.translator.translate(
                        self.setting.src_lang,
                        self.setting.dst_lang,
                        self.last_text,
                        cur_text,
                    )
                    logger.info(f"[Translated] {cur_translated_text}")
                # Merge with the last complete text
                text = ""
                if self.translator:
                    text = f"{self.last_text}({self.last_translated_text})\n{cur_text}({cur_translated_text})"
                else:
                    text = f"{self.last_text}\n{cur_text}"
                # Send to VRChat
                self.osc_client.send_message("/chatbox/typing", [False])
                self.osc_client.send_message("/chatbox/input", [text, self.setting.osc_bypass_keyboard, self.setting.osc_enableSFX])
                # Update last_text
                self.last_text = cur_text
                self.last_translated_text = cur_translated_text
        except Exception as e:
            logger.error(e)
            raise e

class MicCollector:
    def __init__(self, setting: Setting):
        self.setting = setting
        self.mic: pyaudio.PyAudio = None
        self.stream: pyaudio.Stream = None

    def __del__(self):
        self.stop()

    def start(self):
        self.mic = pyaudio.PyAudio()
        self.stream = self.mic.open(format=pyaudio.paInt16,
            channels=1,
            input_device_index=self.setting.micro_device_id,
            rate=16000,
            input=True,
            )

    def stop(self):
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
            self.stream = None
        if self.mic:
            self.mic.terminate()
            self.mic = None

    async def read(self):
        return await asyncio.to_thread(self.stream.read, 3200)

# Audio and Speech Recognition Workhorse
# Keep running until `Stop`
async def ARSWorker(setting: Setting):
    mic = MicCollector(setting)
    mic.start()

    try:
        # Init translator: text(src_language) -> text(dst_language)
        translator = None
        if setting.enable_translate:
            try:
                translator = AlicloudApiTranslator()
                translator.init_client(
                    setting.alicloud_access_key_id,
                    setting.alicloud_access_key_secret,
                    setting.alicloud_endpoint,
                )
            except Exception as e:
                logger.error(e)
                raise e

        # Init asr: audio -> text
        asr_callback = VRChatOscCallback(setting, translator)
        asr = DashscopeApiAsr()
        asr.start(api_key=setting.api_key, callback=asr_callback)

        while True:
            audio_data = await mic.read()
            if asr.is_stopped():
                break
            asr.send_audio_frame(audio_data)
    finally:
        mic.stop()
        if asr and not asr.is_stopped():
            asr.stop()


def InitLogger():
    # Initialize the logger
    # Note it is using a QueueHandler, meaning the actual log job is finished on another process
    logger.setLevel(logging.DEBUG)
    log_queue = multiprocessing.Queue(-1)
    queue_handler = logging.handlers.QueueHandler(log_queue)
    logger.addHandler(queue_handler)

    # Disable the progration
    logger.propagate = False

    # Initialize the QueueListener
    # Create a file handler and set its level
    file_log_format = 'VRCPASR: [%(asctime)s - %(filename)s Line %(lineno)d - %(processName)s - %(threadName)s ] [%(levelname)s] %(message)s'
    file_handler = logging.handlers.RotatingFileHandler('vrchat_paraformer_asr.log', maxBytes=5*1024, backupCount=1, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(file_log_format))

    # Create a console handler and set its level
    console_log_format = '[%(levelname)s] %(message)s'
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(console_log_format))

    # Add the handlers to the listener
    queue_listener = logging.handlers.QueueListener(log_queue, file_handler, console_handler, respect_handler_level=True)
    queue_listener.start()



def get_micro_id2name()->dict[int, str]:
    p = pyaudio.PyAudio()
    device_id2name = {}
    info = p.get_host_api_info_by_index(0)
    numdevices = info.get('deviceCount')
    for i in range(0, numdevices):
        if (p.get_device_info_by_host_api_device_index(0, i).get('maxInputChannels')) > 0:
            name = p.get_device_info_by_host_api_device_index(0, i).get('name')
            device_id2name[i] = name
    p.terminate()
    return device_id2name