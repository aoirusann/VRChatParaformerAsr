from DashscopeApiAsr import DashscopeApiAsr, DashscopeCustomRecognitionCallback, RecognitionResult
from AlicloudApiTranslator import AlicloudApiTranslator
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
import argparse
import logging
import logging.handlers
logger = logging.getLogger("VRChatParaformerAsr")
main_event_loop = None

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

    def serialize(self) -> str:
        return json.dumps(self.__dict__)

    def deserialize(self, s: str) -> None:
        d = json.loads(s)
        for key, value in d.items():
            self.__dict__[key] = value

class VRChatOscCallback(DashscopeCustomRecognitionCallback):
    def __init__(self, setting: Setting, ctx, translator: AlicloudApiTranslator = None):
        self.setting = setting
        self.ctx = ctx
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
        self.ctx["stt_worker"] = None
        self.ctx["stt_worker"] = asyncio.run_coroutine_threadsafe(ARSWorker(self.setting, self.ctx), main_event_loop)

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
async def ARSWorker(setting: Setting, ctx):
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
        asr_callback = VRChatOscCallback(setting, ctx, translator)
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
    global main_event_loop
    main_event_loop = asyncio.get_running_loop()

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

    with ui.card():
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
        ctl_enable_translate = ui.checkbox("Enable translation")
    with ui.card():
        with ui.row():
            langs = {
                "zh": "中文",
                "en": "English",
                "ja": "日本語",
                "ko": "한국인",
            }
            ctl_src_lang = ui.select(
                options=langs,
                label="Source Language",
                new_value_mode="add-unique",
                value="zh",
            ).tooltip("Language of your voice.")
            ctl_dst_lang = ui.select(
                options=langs,
                label="Destination Language",
                new_value_mode="add-unique",
                value="ja",
            ).tooltip("Language of the translated text.")
            ui.link("Complete language code list", "https://help.aliyun.com/zh/machine-translation/support/supported-languages-and-codes?spm=api-workbench.api_explorer.0.0.3d374eecSIT7xn")
        with ui.row():
            ctl_alicloud_access_key_id = ui.input(
                label="Alicloud Access Key ID"
            )
            ctl_alicloud_access_key_secret = ui.input(
                label="Alicloud Access Key Secret"
            )
        with ui.row():
            ctl_alicloud_endpoint = ui.input(
                label="Alicloud Endpoint",
                value='mt.cn-hangzhou.aliyuncs.com',
                placeholder='mt.cn-hangzhou.aliyuncs.com',
            ).tooltip("Service endpoint to access. Generally no modification is necessary.")
            ui.link("Complete endpoint list", "https://help.aliyun.com/zh/machine-translation/developer-reference/api-alimt-2018-10-12-endpoint?spm=a2c4g.11186623.0.0.1067c747e9ZNcY")

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
        ctl_log = ui.log(max_lines=100)

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
    ctl_enable_translate.bind_value(setting, "enable_translate")
    ctl_src_lang.bind_value(setting, "src_lang")
    ctl_dst_lang.bind_value(setting, "dst_lang")
    ctl_alicloud_access_key_id.bind_value(setting, "alicloud_access_key_id")
    ctl_alicloud_access_key_secret.bind_value(setting, "alicloud_access_key_secret")
    ctl_alicloud_endpoint.bind_value(setting, "alicloud_endpoint")

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
    for ctl in [ctl_src_lang, ctl_dst_lang, ctl_alicloud_access_key_id, ctl_alicloud_access_key_secret, ctl_alicloud_endpoint]:
        ctl: nicegui.elements.input.DisableableElement
        ctl.bind_enabled_from(setting, "enable_translate")

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
        ctx["stt_worker"] = asyncio.create_task(ARSWorker(setting, ctx))
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
    # Commandline arguments
    parser = argparse.ArgumentParser(description='VRChatParaformerAsr')
    parser.add_argument('--title', type=str, default='VRChat Paraformer Asr', help='Page Title')
    parser.add_argument('--host', type=str, default='0.0.0.0', help='Host to listen on')
    parser.add_argument('--port', type=int, default=8080, help='Port to listen on')
    args = parser.parse_args()

    title = args.title
    host = args.host
    port = args.port


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
    ui.run(title=title, host=host, port=port, reload=False, storage_secret=storage_key)