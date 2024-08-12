import time
import os
import threading
from http import HTTPStatus
from typing import Any, Dict, List

from dashscope.api_entities.dashscope_response import RecognitionResponse
from dashscope.client.base_api import BaseApi
from dashscope.common.constants import ApiProtocol
from dashscope.common.error import (InputDataRequired, InputRequired,
                                    InvalidParameter, InvalidTask,
                                    ModelRequired)
from dashscope.common.logging import logger
from dashscope.common.utils import _get_task_group_and_task
from dashscope.protocol.websocket import WebsocketStreamingMode

from dashscope.audio.asr import RecognitionCallback, RecognitionResult

class DashscopeCustomRecognitionCallback(RecognitionCallback):
    def on_response_timeout(self, result: RecognitionResult):
        pass

# Almost identity with dashscope.audio.asr.Recogntion
# But has no timeout event when long time not receive audio-data
class DashscopeCustomRecognition(BaseApi):
    """Speech recognition interface.

    Args:
        model (str): The requested model_id.
        callback (RecognitionCallback): A callback that returns
            speech recognition results.
        format (str): The input audio format for speech recognition.
        sample_rate (int): The input audio sample rate for speech recognition.
        workspace (str): The dashscope workspace id.

        **kwargs:
            phrase_id (list, `optional`): The ID of phrase.
            disfluency_removal_enabled(bool, `optional`): Filter mood words,
                turned off by default.
            diarization_enabled (bool, `optional`): Speech auto diarization,
                turned off by default.
            speaker_count (int, `optional`): The number of speakers.
            timestamp_alignment_enabled (bool, `optional`): Timestamp-alignment
                calibration, turned off by default.
            special_word_filter(str, `optional`): Sensitive word filter.
            audio_event_detection_enabled(bool, `optional`):
                Audio event detection, turned off by default.

    Raises:
        InputRequired: Input is required.
    """

    def __init__(self,
                 model: str,
                 callback: DashscopeCustomRecognitionCallback,
                 format: str,
                 sample_rate: int,
                 workspace: str = None,
                 **kwargs):
        if model is None:
            raise ModelRequired('Model is required!')
        if format is None:
            raise InputRequired('format is required!')
        if sample_rate is None:
            raise InputRequired('sample_rate is required!')

        self.model = model
        self.format = format
        self.sample_rate = sample_rate
        # continuous recognition with start() or once recognition with call()
        self._recognition_once = False
        self._callback = callback
        self._running = False
        self._stream_data = []
        self._worker = None
        self._kwargs = kwargs
        self._workspace = workspace

    def __del__(self):
        if self._running:
            self._running = False
            self._stream_data.clear()
            if self._worker is not None and self._worker.is_alive():
                self._worker.join()
            if self._callback:
                self._callback.on_close()

    def __receive_worker(self):
        """Asynchronously, initiate a real-time speech recognition request and
           obtain the result for parsing.
        """
        responses = self.__launch_request()
        for part in responses:
            if part.status_code == HTTPStatus.OK:
                if len(part.output) == 0:
                    self._callback.on_complete()
                else:
                    usage: Dict[str, Any] = None
                    useags: List[Any] = None
                    if 'sentence' in part.output and part.usage is not None:
                        usage = {
                            'end_time': part.output['sentence']['end_time'],
                            'usage': part.usage
                        }
                        useags = [usage]

                    self._callback.on_event(
                        RecognitionResult(
                            RecognitionResponse.from_api_response(part),
                            usages=useags))
            elif part.status_code == 44 and part.code=="ResponseTimeout":
                self._running = False
                self._stream_data.clear()
                self._callback.on_response_timeout(
                    RecognitionResult(
                        RecognitionResponse.from_api_response(part)))
                self._callback.on_close()
            else:
                self._running = False
                self._stream_data.clear()
                self._callback.on_error(
                    RecognitionResult(
                        RecognitionResponse.from_api_response(part)))
                self._callback.on_close()
                break

    def __launch_request(self):
        """Initiate real-time speech recognition requests.
        """
        resources_list: list = []
        if self._phrase is not None and len(self._phrase) > 0:
            item = {'resource_id': self._phrase, 'resource_type': 'asr_phrase'}
            resources_list.append(item)

            if len(resources_list) > 0:
                self._kwargs['resources'] = resources_list

        self._tidy_kwargs()
        task_name = "asr"
        responses = super().call(model=self.model,
                                 task_group='audio',
                                 task=task_name,
                                 function='recognition',
                                 input=self._input_stream_cycle(),
                                 api_protocol=ApiProtocol.WEBSOCKET,
                                 ws_stream_mode=WebsocketStreamingMode.DUPLEX,
                                 is_binary_input=True,
                                 sample_rate=self.sample_rate,
                                 format=self.format,
                                 stream=True,
                                 workspace=self._workspace,
                                 **self._kwargs)
        return responses

    def start(self, phrase_id: str = None, **kwargs):
        """Real-time speech recognition in asynchronous mode.
           Please call 'stop()' after you have completed recognition.

        Args:
            phrase_id (str, `optional`): The ID of phrase.

            **kwargs:
                disfluency_removal_enabled(bool, `optional`):
                    Filter mood words, turned off by default.
                diarization_enabled (bool, `optional`):
                    Speech auto diarization, turned off by default.
                speaker_count (int, `optional`): The number of speakers.
                timestamp_alignment_enabled (bool, `optional`):
                    Timestamp-alignment calibration, turned off by default.
                special_word_filter(str, `optional`): Sensitive word filter.
                audio_event_detection_enabled(bool, `optional`):
                    Audio event detection, turned off by default.

        Raises:
            InvalidParameter: This interface cannot be called again
                if it has already been started.
            InvalidTask: Task create failed.
        """
        assert self._callback is not None, 'Please set the callback to get the speech recognition result.'  # noqa E501

        if self._running:
            raise InvalidParameter('Speech recognition has started.')

        self._phrase = phrase_id
        self._kwargs.update(**kwargs)
        self._recognition_once = False
        self._worker = threading.Thread(target=self.__receive_worker)
        self._worker.start()
        if self._worker.is_alive():
            self._running = True
            self._callback.on_open()
        else:
            self._running = False
            raise InvalidTask('Invalid task, task create failed.')

    def call(self,
             file: str,
             phrase_id: str = None,
             **kwargs) -> RecognitionResult:
        """Real-time speech recognition in synchronous mode.

        Args:
            file (str): The path to the local audio file.
            phrase_id (str, `optional`): The ID of phrase.

            **kwargs:
                disfluency_removal_enabled(bool, `optional`):
                    Filter mood words, turned off by default.
                diarization_enabled (bool, `optional`):
                    Speech auto diarization, turned off by default.
                speaker_count (int, `optional`): The number of speakers.
                timestamp_alignment_enabled (bool, `optional`):
                    Timestamp-alignment calibration, turned off by default.
                special_word_filter(str, `optional`): Sensitive word filter.
                audio_event_detection_enabled(bool, `optional`):
                    Audio event detection, turned off by default.

        Raises:
            InvalidParameter: This interface cannot be called again
                if it has already been started.
            InputDataRequired: The supplied file was empty.

        Returns:
            RecognitionResult: The result of speech recognition.
        """
        if self._running:
            raise InvalidParameter('Speech recognition has been called.')

        if os.path.exists(file):
            if os.path.isdir(file):
                raise IsADirectoryError('Is a directory: ' + file)
        else:
            raise FileNotFoundError('No such file or directory: ' + file)

        self._recognition_once = True
        self._stream_data.clear()
        self._phrase = phrase_id
        self._kwargs.update(**kwargs)
        error_flag: bool = False
        sentences: List[Any] = []
        usages: List[Any] = []
        response: RecognitionResponse = None
        result: RecognitionResult = None

        try:
            audio_data: bytes = None
            f = open(file, 'rb')
            if os.path.getsize(file):
                while True:
                    audio_data = f.read(12800)
                    if not audio_data:
                        break
                    else:
                        self._stream_data = self._stream_data + [audio_data]
            else:
                raise InputDataRequired(
                    'The supplied file was empty (zero bytes long)')
            f.close()
        except Exception as e:
            logger.error(e)
            raise e

        if self._stream_data is not None and len(self._stream_data) > 0:
            self._running = True
            responses = self.__launch_request()
            for part in responses:
                if part.status_code == HTTPStatus.OK:
                    if 'sentence' in part.output:
                        sentence = part.output['sentence']
                        if RecognitionResult.is_sentence_end(sentence):
                            sentences.append(sentence)

                            if part.usage is not None:
                                usage = {
                                    'end_time':
                                    part.output['sentence']['end_time'],
                                    'usage': part.usage
                                }
                                usages.append(usage)

                    response = RecognitionResponse.from_api_response(part)
                else:
                    response = RecognitionResponse.from_api_response(part)
                    logger.error(response)
                    error_flag = True
                    break

        if error_flag:
            result = RecognitionResult(response)
        else:
            result = RecognitionResult(response, sentences, usages)

        self._stream_data.clear()
        self._recognition_once = False
        self._running = False

        return result

    def stop(self):
        """End asynchronous speech recognition.

        Raises:
            InvalidParameter: Cannot stop an uninitiated recognition.
        """
        if self._running is False:
            raise InvalidParameter('Speech recognition has stopped.')

        self._running = False
        if self._worker is not None and self._worker.is_alive():
            self._worker.join()
        self._stream_data.clear()
        if self._callback:
            self._callback.on_close()

    def send_audio_frame(self, buffer: bytes):
        """Push speech recognition.

        Raises:
            InvalidParameter: Cannot send data to an uninitiated recognition.
        """
        if self._running is False:
            raise InvalidParameter('Speech recognition has stopped.')

        self._stream_data = self._stream_data + [buffer]

    def is_stopped(self) -> bool:
        return not self._running

    def _tidy_kwargs(self):
        for k in self._kwargs.copy():
            if self._kwargs[k] is None:
                self._kwargs.pop(k, None)

    def _input_stream_cycle(self):
        while self._running:
            while len(self._stream_data) == 0:
                if self._running:
                    time.sleep(0.01)
                    continue
                else:
                    break

            for frame in self._stream_data:
                yield bytes(frame)
            self._stream_data.clear()

            if self._recognition_once:
                self._running = False

        # drain all audio data when invoking stop().
        if self._recognition_once is False:
            for frame in self._stream_data:
                yield bytes(frame)