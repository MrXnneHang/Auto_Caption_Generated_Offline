## 项目介绍:

#### 使用Funasr的带time_stamp的语音识别后转换成srt,并不复杂,

#### 注意:

Models 会自动下载，不过会下到C盘的User用户路径下，如果有需要自己配置环境的,可以手动下载然后放到当前根目录的Model下方。

环境配置见:https://github.com/modelscope/FunASR



有bug，请在b站私信反映，或者放在Isuue中。

b站:https://space.bilibili.com/556737824?spm_id_from=333.788.0.0

## 2024/6/13更新:  
* 更新了新的模型，包括:  
speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch    2024.4
语音检测base模型.  
speech_fsmn_vad_zh-cn-16k-common-pytorch  2024.2
长音频自动划分模型，可以接受长音频输入。   
punc_ct-transformer_zh-cn-common-vocab272727-pytorch  2024.2
语音活动检测模型，用于生成time_stamp   
* 支持热词功能。  
* 整合bilibili@不知雪孤的代码，各方面使用更加舒适。  

**注意：**  
请不要在旧版本环境基础上构建新版本代码，旧版本的funasr不支持AutoModel模块，而新版本代码去掉了以前pipline的inference，可以自由搭配模型。  

你可以自己在modelscope中下载模型然后放在./models 下方。或者使用我们的整合包。    
链接：https://pan.baidu.com/s/1_RUIsaaAJkfx1EsJlbdv3A?pwd=4v4e   
提取码：4v4e    
6.13对应V2版本   
关于演示视频：    
待制作  
