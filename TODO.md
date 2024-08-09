* [x] browser local storage
* [x] log view
* [ ] better UI
	* `ui.number` will hide some text... (e.g. `VRChat OSC Port`)
	* `ui.selector` is too narrow, which will hide some option (e.g. `Micro Device`)
	* `ui.input` is too narrow for `Dashscope API Key`
* [x] pyinstaller package
	* `_ssl` import error
		* Conda is unsupported by pyinstaller: https://github.com/pyinstaller/pyinstaller/issues/7510	
* [x] VRChat typing indicator
* [x] document for API key
* [ ] chinese
* [x] Handle `ResponseTimeout` bug
	* The connection will be shutdown by the remote server if there has been no audio data sent for 60 seconds.
* [x] Refactor to split setting & runtime to reduce the runtime overhead (which is caused by gui mainly) (reported by LL)