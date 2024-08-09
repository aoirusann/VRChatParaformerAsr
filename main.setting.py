from core import Setting, InitLogger, get_micro_id2name
import nicegui.elements
import nicegui.elements.input
from nicegui import ui, app
import re
import os
import platform
import hashlib
import pyaudio
import argparse
import logging
import logging.handlers

logger = logging.getLogger("VRChatParaformerAsr")
setting_filepath = None

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
        btn_save = ui.button("Save", color="green")
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
    for ctl in [ctl_src_lang, ctl_dst_lang, ctl_alicloud_access_key_id, ctl_alicloud_access_key_secret, ctl_alicloud_endpoint]:
        ctl: nicegui.elements.input.DisableableElement
        ctl.bind_enabled_from(setting, "enable_translate")

    # Bind onclicked
    async def on_clicked_load_default_setting_btn():
        if await load_default_setting_dialog:
            setting.copy_from(Setting())
            logger.info("Default setting is load: " + setting.serialize())
    btn_load_default_setting.on_click(on_clicked_load_default_setting_btn)

    def on_clicked_save_btn():
        # Save Setting
        s: str = setting.serialize(indent=2)
        logger.info(f"Saving setting: {s}")

        logger.info(f"Save setting into app.storage.user for user {app.storage.browser['id']}")
        app.storage.user["VRCPASR_setting"] = s

        logger.info(f"Save setting into {setting_filepath}")
        with open(setting_filepath, "wt") as f:
            f.write(s)
    btn_save.on_click(on_clicked_save_btn)

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

    #############################
    # Try load stored setting from localStorage
    saved_setting: None|str = app.storage.user.get("VRCPASR_setting", None)
    if saved_setting:
        logger.info(f"Load setting from app.storage.user for user {app.storage.browser['id']}: {saved_setting}")
        setting.deserialize(saved_setting)
    
    # Try load setting from `setting.json`
    if os.path.exists(setting_filepath):
        with open(setting_filepath) as f:
            setting_str = f.read()
        setting.deserialize(setting_str)


if __name__ in {"__main__", "__mp_main__"}:
    # ============
    # Logger
    InitLogger()

    # =======================
    # Commandline arguments
    parser = argparse.ArgumentParser(description='VRChatParaformerAsr')
    parser.add_argument('--title', type=str, default='VRChat Paraformer Asr Setting Panel', help='Page Title')
    parser.add_argument('--host', type=str, default='0.0.0.0', help='Host to listen on')
    parser.add_argument('--port', type=int, default=8080, help='Port to listen on')
    parser.add_argument('--setting', type=str, default='setting.json', help='The path to `setting.json` which should be the serialized `core.Setting` object. Default `setting.json`.')
    args = parser.parse_args()

    title = args.title
    host = args.host
    port = args.port
    setting_filepath = args.setting


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