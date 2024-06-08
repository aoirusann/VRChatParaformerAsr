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
import platform
import hashlib
import json
import logging
import logging.handlers
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
        # microphone: should recreate `MicCollector` after change
        self.micro_device_id = 3
        # dashscope api: should restart`DashscopeApiAsr` after change
        self.api_key = ""
        self.disfluency_removal_enabled = False

    def copy_from(self, another: "Setting") -> None:
        for key, value in another.__dict__.items():
            self.__dict__[key] = value

    def serialize(self) -> str:
        return json.dumps(self.__dict__)

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
    asr_callback = VRChatOscCallback(setting)
    asr = DashscopeApiAsr()
    asr.start(api_key=setting.api_key, callback=asr_callback)

    mic = MicCollector(setting)
    mic.start()

    try:
        while True:
            audio_data = await mic.read()
            asr.send_audio_frame(audio_data)
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
async def homepage():
    # Default Setting
    setting = Setting()

    # Declare page ui
    with ui.row():
        ctl_vrchat_ip = ui.input(
            label="VRChat OSC IP",
            placeholder="127.0.0.1",
            validation={"Invalid IP address(e.g. 127.0.0.1)": is_valid_ip},
        ).tooltip("VRChat OSC IP")
        ctl_vrchat_port = ui.number(
            label="VRChat OSC Port",
            placeholder="9000",
            min=0,
            max=65535,
            precision=0,
            step=1,
        ).tooltip("VRChat OSC Port")
    with ui.row():
        ctl_osc_bypass_keyboard = ui.checkbox("OSC bypass keyboard").tooltip("Disable if you want to open the keyboard when transcription is done.")
        ctl_osc_enableSFX = ui.checkbox("OSC enable SFX").tooltip("Disable if the sound effect when sending message is not needed.")
    ctl_micro_device_id = ui.select(
        options=get_micro_id2name(),
        label="Micro Device",
        with_input=True,
    )
    with ui.row():
        ctl_api_key = ui.input(
            label="Dashscope API Key",
        )

    with ui.row():
        btn_start = ui.button("Start", color="green")
        btn_stop = ui.button("Stop", color="red")
    with ui.expansion("Usually not used"):
        with ui.row():
            btn_load_default_setting = ui.button("Load Default Setting")
            ctl_disfluency_removal_enabled = ui.checkbox("disfluency_removal_enabled")
            ctl_dark_mode = ui.checkbox("UI dark mode")
    with ui.card():
        ui.label("Log:")
        ctl_log = ui.log(max_lines=None)

    # Declare dialog ui
    with ui.dialog() as load_default_setting_dialog, ui.card():
        ui.label("Really want to load default setting?\nThis will override all your current settings!")
        with ui.row() as r:
            ui.button("Yes").on_click(lambda: load_default_setting_dialog.submit(True))
            ui.button("No").on_click(lambda: load_default_setting_dialog.submit(False))

    # UI Runtime Context
    ctx = {
        "stt_worker": None
    }

    # Bind value
    ui.dark_mode().bind_value(setting, "dark_mode")
    ctl_dark_mode.bind_value(setting, "dark_mode")
    ctl_vrchat_ip.bind_value(setting, "vrchat_ip")
    ctl_vrchat_port.bind_value(setting, "vrchat_port")
    ctl_osc_bypass_keyboard.bind_value(setting, "osc_bypass_keyboard")
    ctl_osc_enableSFX.bind_value(setting, "osc_enableSFX")
    ctl_micro_device_id.bind_value(setting, "micro_device_id")
    ctl_api_key.bind_value(setting, "api_key")
    ctl_disfluency_removal_enabled.bind_value(setting, "disfluency_removal_enabled")

    # Bind enabled
    ctls_enabled_when_worker_is_None: list[nicegui.elements.input.DisableableElement] = [
        ctl_vrchat_ip, ctl_vrchat_port,
        ctl_micro_device_id, ctl_api_key,
        ctl_disfluency_removal_enabled,
        btn_load_default_setting,
        btn_start
    ]
    for ctl in ctls_enabled_when_worker_is_None:
        ctl.bind_enabled_from(ctx, "stt_worker", lambda worker: worker==None)
    ctls_disabled_when_worker_is_None: list[nicegui.elements.input.DisableableElement] = [
        btn_stop
    ]
    for ctl in ctls_disabled_when_worker_is_None:
        ctl.bind_enabled_from(ctx, "stt_worker", lambda worker: worker!=None)

    # Bind onclicked
    async def on_clicked_load_default_setting_btn():
        if await load_default_setting_dialog:
            setting.copy_from(Setting())
            logger.info("Default setting is load: " + setting.serialize())
    btn_load_default_setting.on_click(on_clicked_load_default_setting_btn)

    def on_clicked_start_btn():
        # Save Setting before start
        s: str = setting.serialize()
        logger.info(f"Save setting into app.storage.user for user {app.storage.browser['id']}: {s}")
        app.storage.user["VRCPASR_setting"] = s
        # Start async ARS worker
        ctx["stt_worker"] = asyncio.create_task(ARSWorker(setting))
        # Update UI
        ui.update(btn_start)
        ui.update(btn_stop)
    btn_start.on_click(on_clicked_start_btn)

    def on_clicked_stop_btn():
        if ctx["stt_worker"] != None:
            # Cancel async ARS worker
            ctx["stt_worker"].cancel()
            ctx["stt_worker"] = None
            # Update UI
            ui.update(btn_start)
            ui.update(btn_stop)
    btn_stop.on_click(on_clicked_stop_btn)

    # Attach to logger
    class LogElementHandler(logging.Handler):
        """A logging handler that emits messages to a log element."""
        def __init__(self, element: ui.log, level: int = logging.NOTSET) -> None:
            self.element = element
            super().__init__(level)
        def emit(self, record: logging.LogRecord) -> None:
            try:
                msg = self.format(record)
                self.element.push(msg)
            except Exception:
                self.handleError(record)
    log_format = '[%(levelname)s] %(message)s'
    log_handler = LogElementHandler(ctl_log)
    log_handler.setFormatter(logging.Formatter(log_format))
    logger.addHandler(log_handler)

    # Try load stored setting from localStorage
    saved_setting: None|str = app.storage.user.get("VRCPASR_setting", None)
    if saved_setting:
        logger.info(f"Load setting from app.storage.user for user {app.storage.browser['id']}: {saved_setting}")
        setting.deserialize(saved_setting)


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

    # Storage key
    def get_machine_identifier():
        system_info = platform.node() + platform.machine() + platform.processor()
        return hashlib.sha256(system_info.encode()).hexdigest()
    storage_key = os.environ.get("STORAGE_KEY", None) # Perfer get from environment var
    if not storage_key:
        storage_key = get_machine_identifier() # Otherwise use machine identifier

    # Register NiceGUI's events
    app.on_startup(lambda: logger.debug("NiceGUI startup"))
    app.on_connect(lambda: logger.debug("NiceGUI connect"))
    app.on_disconnect(lambda: logger.debug("NiceGUI disconnect"))
    app.on_shutdown(lambda: logger.debug("NiceGUI shutdown"))
    app.on_exception(lambda e: logger.error(f"NiceGUI exception: {e}"))

    # Start UI
    ui.run(reload=True, storage_secret=storage_key)