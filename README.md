## 项目介绍:

#### 使用Funasr的带time_stamp的语音识别后转换成srt,并不复杂,

#### 注意:

Models 会自动下载，不过会下到C盘的User用户路径下，如果有需要自己配置环境的,可以手动下载然后放到当前根目录的Model下方。

###  环境配置见:https://github.com/modelscope/FunASR



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
[b站](https://www.bilibili.com/video/BV1bz421z7gj/?spm_id_from=333.999.0.0)



## 2024/6/21的更新:(主要是Bug-fix)

1.部分用户转成.wav文件时是大写的.WAV，被认为不是支持的wav

2.偶尔的吞字现象。

3.cut_line未引用导致调整cut_line无效

4.你可以在config.yml中调整cut_line和combine_line



**详细见:[字幕生成V2.1:更新介绍、Bug Fix | XnneHang's Blog](http://xnnehang.top/blog/27)**



## 2024/7/7的更新(主要是bug-fix)

1.识别到英文的时候偶尔就会碰到List out of Index.

2.可以在config.yml中更改device

3.写入srt的时候顺便写入了whole_text

**详细见：[字幕生成V2.2:Bug Fix,支持手动修改device，可选择文本标点恢复。 | XnneHang's Blog](http://xnnehang.top/blog/44)**



## 2024/7/30更新:

1.英文单词被拆开,字母被当成单词

2.如果异常，不退出，继续执行。

3.将batch_size_s改成可以修改的值。

**详细见：[字幕生成V2.3 : 英文单词的兼容，batch_size的自定义. | XnneHang's Blog](http://xnnehang.top/blog/81)**


##  更新预告:
1.部分使用者反馈mp4 -> wav 的时候，wav比mp4短，导致字幕偏移. fix
2.用tk制作一个简单的交互ui,支持直接拖入mp4并且->srt和txt。届时需要额外install一些依赖，比如ffmpeg和extra_requirements.txt。
感谢bilibili@是谁住在深海的大菠萝屋里,贡献了大部分代码。