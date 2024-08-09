from core import InitLogger, Setting, ARSWorker
import asyncio
import argparse
import logging
import logging.handlers
logger = logging.getLogger("VRChatParaformerAsr")


if __name__ in {"__main__", "__mp_main__"}:
    # ============
    # Logger
    InitLogger()

    # =======================
    # Commandline arguments
    parser = argparse.ArgumentParser(description='VRChatParaformerAsr')
    parser.add_argument('--setting', type=str, default='setting.json', help='The path to `setting.json` which should be the serialized `core.Setting` object. Default `setting.json`.')
    args = parser.parse_args()

    setting_filepath = args.setting

    # TODO try init setting.json from .nicegui

    # =======================
    # Load setting
    with open(setting_filepath, "rt") as f:
        setting_str = f.read()
    setting: Setting = Setting()
    setting.deserialize(setting_str)

    # =======================
    # Main job for launching async ARS worker
    async def main():
        while True:
            await ARSWorker(setting)

    # =======================
    # Infinite Loop
    asyncio.run(main())