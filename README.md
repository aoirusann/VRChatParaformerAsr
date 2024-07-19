# 介绍

VRChatParaformerAsr会读取你的语音，再利用阿里云提供的服务将其转换成文字，最后通过OSC发送给vrchat。

用法：
1. 前往[Release界面](https://github.com/aoirusann/VRChatParaformerAsr/releases)下载`.exe`文件，并执行它
2. 然后浏览器应该会自动弹出访问`http://127.0.0.1:8080/`的网页（没弹出的话就自己开一个网页）：![](pic/2024-07-19-23-20-26.png)
3. 修改`Micro Device`，选择你使用的麦克风设备
4. 在`Dashscope API Key`处填入Dashscope的API Key（获取方法见后文）
5. （可选）如果需要使用翻译功能的话
	1. 勾选`Enable translation`
	2. 选择你的语言`Source Language`
	3. 选择你想翻译成什么语言`Destination Language`
	4. 在`Alicloud Access Key ID`和`Alicloud Access Key Secret`处填入阿里云的Access Key（获取方法见后文，注意和上面的`Dashscope API Key`是两回事）
	5. `Alicloud Endpoint`通常不用管
6. 点`START`
7. 记得VRChat里要启用OSC

附带一提两个勾选框的含义分别为：
* `OSC bypass keyboard`：不勾选的话好像会自动打开vrchat里的键盘？没测试过
* `OSC enable SFX`：不勾选的话vrchat里头上冒气泡的时候就不会有音效了

目前已知的bug：
* 点`STOP`时有时会闪退掉
* 还遇到什么别的bug的话请在[issues](https://github.com/aoirusann/VRChatParaformerAsr/issues)里提出，不过因为该项目只是我为朋友写的，在够用的情况下我并不一定会去修别的bug……

另外，
* 底层调用的模型主要是支持中文普通话，也支持一些英语
* 如果你是别的语种的使用者或者不在国内的话，我推荐你使用[VRCT](https://github.com/misyaguziya/VRCT)或者[vrc stt](https://vrcstt.com/)
* 本仓库的主要特点是底层调用的是阿里云专门为中文实时语音识别训练的模型（paraformer-realtime-v1），因此对中文的支持比较好，而且从国内访问的话网速很快
  * 我考虑过要不要给VRCT写个pull request的，但是因为paraformer-realtime-v1是实时语音识别模型，而非whisper那种离线的，两者的接口差太多了，所以没办法我就只好自己重新搓了个轮子




# 语音转文字相关：阿里云的Dashscope API Key获得方法

1. 打开dashscope控制台（该注册账号就注册账号，可能还得先实名认证）: https://dashscope.console.aliyun.com
2. 左边侧栏打开`API-KEY管理`，然后点`创建新的API-KEY`：![](pic/2024-07-11-01-49-23.png)
	* 或者参考[官方文档](https://help.aliyun.com/zh/dashscope/developer-reference/acquisition-and-configuration-of-api-key?spm=a2c4g.11186623.0.0.7675756ealb7K7)来给子账户赋权再创建API Key
3. 把弹出来的那串字符串给复制下来保存好，它就是API key，就是你应该填进`Dashscope API Key`里的东西

备注：
* 请妥善保管，API key借给别人的话可能会导致欠款
* 阿里云提供了每个月36000秒的免费额度，常规的个人使用应该是够用了
	* 在dashscope控制台处（就是上面第一步那个链接）可以看到概略的使用情况：![](pic/2024-07-11-01-55-57.png)
	* 在调用统计处可以看到详细的使用情况：![](pic/2024-07-11-01-58-36.png)
	* 不过该统计是有延迟的（可能晚半天一天才会有统计结果），并非即时统计


# 文本翻译相关：阿里云的Access Key ID/Secret获得方法

照着[官方文档](https://help.aliyun.com/zh/sls/developer-reference/accesskey-pair?spm=a2c4g.11186623.0.0.4fbb1674OV2Moi)做就可以获得主账户的Access Key了。

子账户赋权可以不管，或者参考[这份官方文档](https://help.aliyun.com/zh/machine-translation/getting-started/ram-user-authorization?spm=a2c4g.11186623.0.0.278225811DurTv)来给子账户赋权，使用子账户的access key（好处是key泄露的时候别人也只能使用机器翻译的功能，更安全点）。

备注：
* 请妥善保管，Access Key借给别人的话可能会导致欠款
* 阿里云提供了每个月100万个字符的免费额度，常规的个人使用应该是够用了
	* [计费相关的常见问题的官方文档](https://help.aliyun.com/zh/machine-translation/support/faq-about-billing-for-developers?spm=a2c4g.11186623.0.0.6fd43ad7KXF7P8)
	* [免费额度查询](https://mt.console.aliyun.com/service?spm=a2c4g.11186623.0.0.5efa10170wYvNW)
* 我调用的是通用版接口，不是专业版的（专业版是指词汇专业，并不是指翻译效果更好）
* 其实有道、讯飞他们都直接提供了`语音->文本+文本翻译`的服务，但都好贵的
	* 例如[有道](https://ai.youdao.com/streamingAudio.s)的，20小时204块，一次性免费额度
	* 所以最后还是选择分开来白嫖阿里云两个AI平台的服务了
	* 也因此会需要在两个地方分别申请Api Key/Access Key，毕竟虽然都是阿里云的，但一个是灵积（语音转文字），一个是灵杰（文本翻译）



# 常见问题

## 我的8080端口被占了怎么办？
1. 给`.exe`文件创建个快捷方式
2. 右键快捷方式，`目标`那里在.exe后面加上` --port 14512`（14512是你想换成的新端口）
3. 执行这个快捷方式



# 面向开发者

## 一些启动参数

命令行选项：
* `--title VRChat Paraformer Asr`
* `--host 0.0.0.0`
* `--port 8080`

环境变量：
* `STORAGE_KEY`：用于存储用户数据的，不指定的话就会根据机器码自动生成一个

## 调试

1. git clone这个库
2. `pip install -r requirements.txt`
3. `python main.py`

## 打包

安装pyinstaller，然后：

``` shell
nicegui-pack --onefile --name "VRChatParaformerAsr" main.py
```

打包后的文件为`dist\VRChatParaformerAsr.exe`
