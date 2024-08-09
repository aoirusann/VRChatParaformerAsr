REM Remove build & dist
if exist build rd /s /q build
if exist dist rd /s /q dist

nicegui-pack --onefile --name "VRChatParaformerAsr_setting" main.setting.py
pyinstaller --onefile --name "VRChatParaformerAsr" main.cmd.py