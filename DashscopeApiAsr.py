# For prerequisites running the following sample, visit https://help.aliyun.com/document_detail/611472.html

import dashscope
from dashscope.audio.asr import (Recognition, RecognitionCallback,
                                 RecognitionResult)


class DefaultCallback(RecognitionCallback):
    def on_open(self) -> None:
        print('RecognitionCallback open.')

    def on_close(self) -> None:
        print('RecognitionCallback close.')

    def on_event(self, result: RecognitionResult) -> None:
        print('RecognitionCallback sentence: ', result.get_sentence())


class DashscopeApiAsr:
    def __init__(self):
        self.recognition: Recognition = None

    def start(self, api_key: str, callback: RecognitionCallback = DefaultCallback(), disfluency_removal_enabled=False):
        dashscope.api_key = api_key
        self.recognition = Recognition(
            model='paraformer-realtime-v1',
            format='pcm',
            sample_rate=16000,
            callback=callback,
            disfluency_removal_enabled=disfluency_removal_enabled,
        )
        self.recognition.start()

    def stop(self):
        self.recognition.stop()

    def send_audio_frame(self, audio_data):
        self.recognition.send_audio_frame(audio_data)



if __name__ == "__main__":
    import pyaudio
    import os
    asr = DashscopeApiAsr()
    asr.start(api_key=os.environ.get("API_KEY"))

    mic = pyaudio.PyAudio()
    device_id2name = {}
    info = mic.get_host_api_info_by_index(0)
    numdevices = info.get('deviceCount')
    for i in range(0, numdevices):
        if (mic.get_device_info_by_host_api_device_index(0, i).get('maxInputChannels')) > 0:
            name = mic.get_device_info_by_host_api_device_index(0, i).get('name')
            device_id2name[i] = name
    for i, name in device_id2name.items():
        print("Input Device id ", i, " - ", name)
    micro_device_id = int(input("Select Microphone: "))

    stream = mic.open(format=pyaudio.paInt16,
        channels=1,
        input_device_index=micro_device_id,
        rate=16000,
        input=True
        )

    try:
        while True:
            data = stream.read(3200, exception_on_overflow = False)
            asr.send_audio_frame(data)
    finally:
        asr.stop()
        stream.stop_stream()
        stream.close()
        mic.terminate()