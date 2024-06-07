from DashscopeApiAsr import DashscopeApiAsr, RecognitionCallback, RecognitionResult
import nicegui.elements
import nicegui.elements.input
from nicegui import ui, app
import re
import os
import pyaudio
import asyncio
import pythonosc
import pythonosc.udp_client
import multiprocessing
import json
import logging
import logging.handlers
logger = logging.getLogger("VRChatParaformerAsr")

class Setting:
    def __init__(self) -> None:
        # Setting ====
        # vrchat: should recreate `VRChatOscCallback` and restart `DashscopeApiAsr` after change
        self.vrchat_ip = r"127.0.0.1"
        self.vrchat_port = 9000
        # osc
        self.osc_bypass_keyboard = True
        self.osc_enableSFX = True
        # microphone: should recreate `MicCollector` after change
        self.micro_device_id = 3
        # dashscope api: should restart`DashscopeApiAsr` after change
        self.api_key = ""
        self.disfluency_removal_enabled = False

    def serialize(self) -> str:
        return json.dumps(self)

    def deserialize(self, s: str) -> None:
        d = json.loads(s)
        for key, value in d.items():
            self.__dict__[key] = value

class VRChatOscCallback(RecognitionCallback):
    def __init__(self, setting: Setting):
        self.setting = setting
        self.osc_client = pythonosc.udp_client.SimpleUDPClient(self.setting.vrchat_ip, self.setting.vrchat_port)
        self.last_text = ""

    def on_open(self) -> None:
        logger.info('RecognitionCallback open.')

    def on_close(self) -> None:
        logger.info('RecognitionCallback close.')

    def on_error(self, result: RecognitionResult) -> None:
        logger.error(result)

    def on_complete(self) -> None:
        pass

    def on_event(self, result: RecognitionResult) -> None:
        # Get full sentence
        sen = result.get_sentence()
        logger.debug(f'RecognitionCallback sentence: {sen}', )
        # If the sentence is completed, update last_text
        if result.is_sentence_end(sen):
            # Extract the text
            cur_text = sen["text"]
            logger.info(f"[Transcribed] {cur_text}")
            # Merge with the last complete text
            text = self.last_text + "\n" + cur_text
            self.osc_client.send_message("/chatbox/input", [text, self.setting.osc_bypass_keyboard, self.setting.osc_enableSFX])
            # Update last_text
            self.last_text = cur_text

class MicCollector:
    def __init__(self, setting: Setting):
        self.setting = setting
        self.mic: pyaudio.PyAudio = None
        self.stream: pyaudio.Stream = None

    def __del__(self):
        self.stop()

    def start(self, callback):
        self.mic = pyaudio.PyAudio()
        self.stream = self.mic.open(format=pyaudio.paInt16,
            channels=1,
            input_device_index=self.setting.micro_device_id,
            rate=16000,
            input=True,
            stream_callback=callback,
            frames_per_buffer=3200
            )

    def stop(self):
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
            self.stream = None
        if self.mic:
            self.mic.terminate()
            self.mic = None

# Audio and Speech Recognition Workhorse
# Keep running until `Stop`
async def ARSWorker(setting: Setting):
    asr_callback = VRChatOscCallback(setting)
    asr = DashscopeApiAsr()
    asr.start(api_key=setting.api_key, callback=asr_callback)

    def mic_callback(in_data, frame_count, time_info, status_flags):
        asr.send_audio_frame(in_data)
        return None, pyaudio.paContinue
    mic = MicCollector(setting)
    mic.start(mic_callback)

    try:
        while mic.stream.is_active():
            await asyncio.sleep(0.01)
    finally:
        mic.stop()
        asr.stop()

# ===============
# UI
def is_valid_ip(ip):
    """
    检查给定的字符串是否为合法的 IP 地址
    """
    pattern = r'^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$'
    if re.match(pattern, ip):
        parts = [int(part) for part in ip.split('.')]
        if all(0 <= part <= 255 for part in parts):
            return True
    return False

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

@ui.page("/")
def homepage():
    # Default Setting
    setting = Setting()
    setting.api_key = os.environ.get("API_KEY")

    # Declare all ui elements
    ctl_vrchat_ip = ui.input(
        label="VRChat IP",
        placeholder="127.0.0.1",
        validation={"Invalid IP address": is_valid_ip},
    ).bind_value(setting, "vrchat_ip")
    ctl_vrchat_port = ui.number(
        label="VRChat OSC port",
        placeholder="9000",
        min=0,
        max=65535,
        precision=0,
        step=1,
    ).bind_value(setting, "vrchat_port")
    ctl_osc_bypass_keyboard = ui.checkbox("OSC bypass keyboard").bind_value(setting, "osc_bypass_keyboard"),
    ctl_osc_enableSFX = ui.checkbox("OSC enable SFX").bind_value(setting, "osc_enableSFX"),
    ctl_micro_device_id = ui.select(
        options=get_micro_id2name(),
        label="Micro Device",
        with_input=True,
    ).bind_value(setting, "micro_device_id")
    ctl_api_key = ui.input(
        label="Dashscope API Key",
    ).bind_value(setting, "api_key")
    ctl_disfluency_removal_enabled = ui.checkbox("disfluency_removal_enabled").bind_value(setting, "disfluency_removal_enabled")

    start_btn = ui.button("Start")
    stop_btn = ui.button("Stop")

    # UI Runtime Context
    ctx = {
        "stt_worker": None
    }

    # Bind enabled
    ctls_enabled_when_worker_is_None: list[nicegui.elements.input.DisableableElement] = [
        ctl_vrchat_ip, ctl_vrchat_port,
        ctl_micro_device_id, ctl_api_key,
        ctl_disfluency_removal_enabled,
        start_btn
    ]
    for ctl in ctls_enabled_when_worker_is_None:
        ctl.bind_enabled_from(ctx, "stt_worker", lambda worker: worker==None)
    ctls_disabled_when_worker_is_None: list[nicegui.elements.input.DisableableElement] = [
        stop_btn
    ]
    for ctl in ctls_disabled_when_worker_is_None:
        ctl.bind_enabled_from(ctx, "stt_worker", lambda worker: worker!=None)

    # Bind onclick
    def on_start_btn_clicked():
        ctx["stt_worker"] = asyncio.create_task(ARSWorker(setting))
        ui.update(start_btn)
        ui.update(stop_btn)
    start_btn.on_click(on_start_btn_clicked)
    def on_end_btn_clicked():
        if ctx["stt_worker"] != None:
            ctx["stt_worker"].cancel()
            ctx["stt_worker"] = None
            ui.update(start_btn)
            ui.update(stop_btn)
    stop_btn.on_click(on_end_btn_clicked)


if __name__ in {"__main__", "__mp_main__"}:
    # ============
    # Logger

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
    file_handler = logging.handlers.RotatingFileHandler('vrchat_paraformer_asr.log', maxBytes=5*1024, backupCount=1)
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


    # =======================
    # UI
    ui.run(reload=True)

    app.on_startup(lambda: logger.debug("NiceGUI startup"))
    app.on_connect(lambda: logger.debug("NiceGUI connect"))
    app.on_disconnect(lambda: logger.debug("NiceGUI disconnect"))
    app.on_shutdown(lambda: logger.debug("NiceGUI shutdown"))
    app.on_exception(lambda e: logger.error(f"NiceGUI exception: {e}"))