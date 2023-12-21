from modelscope.pipelines import pipeline
from modelscope.utils.constant import Tasks


def write_long_txt(wav_name,deleteshort,skip_line):
    inference_pipeline = pipeline(
        task=Tasks.auto_speech_recognition,
        model='./model/speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-pytorch',
        param_dict={'use_timestamp': True}
    )
    rec_result = inference_pipeline(audio_in=f'./raw_audio/{wav_name}.wav')
    print(rec_result["sentences"])
    sentences = rec_result["sentences"]
    lines = []
    for i in sentences:
        if deleteshort==True:
            if i["ts_list"][-1][-1]-i["ts_list"][0][0]<skip_line: #跳过不记录这些短文本
                continue
            else:
                skip = False
                ## 还需要检测，就是句中停顿超级长.那些实际上可以分成两句
                start_time_list = []
                end_time_list = []
                ## start - end too long 
                for j in i["ts_list"]:
                    ## 遍历start_end的元组
                    start_time_list.append(j[0])
                    end_time_list.append(j[1])
                ## 判断是否删除 n+1的start -  n的end > 2000ms
                for index in range(len(start_time_list)-1): #这两个应该等长
                    if start_time_list[index+1]-end_time_list[index]>2000: ## 发现断点
                        ## 后期可以切分成两句
                        ## 现在直接忽略
                        print("skip it ,it's not a warning.It's normal.")
                        skip = True

                if skip == False:
                    lines.append(str(i["ts_list"][0][0])+"|"+str(i["ts_list"][-1][-1])+"|"+i["text"])
                    print(str(i["ts_list"][0][0])+"|"+str(i["ts_list"][-1][-1])+"|"+i["text"])
                else:
                    continue
        else:
            lines.append(str(i["ts_list"][0][0])+"|"+str(i["ts_list"][-1][-1])+"|"+i["text"])
    write_lines_to_file(f'./tmp/{wav_name}.txt', lines)

def write_lines_to_file(file_path, lines):
    """
    将给定的文本行写入指定的文件。

    :param file_path: 要写入的文件的路径。
    :param lines: 要写入文件的行的列表。
    """
    with open(file_path, 'w', encoding='utf-8') as file:
        for line in lines:
            file.write(line + '\n')





