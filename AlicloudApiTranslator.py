# -*- coding: utf-8 -*-
# This file is auto-generated, don't edit it. Thanks.
import os
import sys

from typing import List

from alibabacloud_alimt20181012.client import Client as alimt20181012Client
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_alimt20181012 import models as alimt_20181012_models
from alibabacloud_tea_util import models as util_models
from alibabacloud_tea_util.client import Client as UtilClient


class AlicloudApiTranslator:
    def __init__(self):
        self.client: alimt20181012Client = None

    def init_client(self, key_id: str, key_secret: str, endpoint: str = f'mt.cn-hangzhou.aliyuncs.com'):
        """
        使用AK&SK初始化账号Client
        @return: Client
        @throws Exception
        """
        config = open_api_models.Config(
            access_key_id=key_id,
            access_key_secret=key_secret,
        )
        # Endpoint 请参考 https://api.aliyun.com/product/alimt
        config.endpoint = endpoint
        self.client = alimt20181012Client(config)

    def translate(self, source_language, target_language, context, source_text, read_timeout_ms=1000, connect_timeout_ms=1000) -> str:
        # Create Request
        translate_general_request = alimt_20181012_models.TranslateGeneralRequest(
            scene='general',
            format_type='text',
            context=context,
            source_text=source_text,
            source_language=source_language,
            target_language=target_language,
        )
        # Set network options
        runtime = util_models.RuntimeOptions(
            read_timeout=read_timeout_ms,
            connect_timeout=connect_timeout_ms,
        )
        # Send Request (block)
        respond = self.client.translate_general_with_options(translate_general_request, runtime)
        return respond.body.data.translated


if __name__ == '__main__':
    translator = AlicloudApiTranslator()
    translator.init_client(os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_ID"), os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_SECRET"), endpoint='mt.cn-hangzhou.aliyuncs.com')
    res = translator.translate(
        "zh", "ja",
        "这是上一句话，可以为空的。",
        "这是现在在说的话。",
    )
    print(res)