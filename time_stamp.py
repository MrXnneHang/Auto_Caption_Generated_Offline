from modelscope.pipelines import pipeline
from modelscope.utils.constant import Tasks
from sentences_method import generate_new_sentences


def write_long_txt(wav_name,cut_line):
    inference_pipeline = pipeline(
        task=Tasks.auto_speech_recognition,
        model='./model/speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-pytorch',
        param_dict={'use_timestamp': True}
    )
    rec_result = inference_pipeline(audio_in=f'./raw_audio/{wav_name}.wav')
    print(rec_result["sentences"])
    sentences = rec_result["sentences"]
    # write_lines_to_file(f'./tmp/{wav_name}_sentences.txt', str(sentences))

    ## 判断是否删除 n+1的start -  n的end > cu   tline
    sentences = generate_new_sentences(sentences=sentences,cutline=cut_line)  ##这个会把一个句子中两句话分开，如果两句话的间隔超过cutline ,default =1000ms
    lines = []
    for i in sentences:
                skip = False
                start_time_list = []
                end_time_list = []
                ## start - end too long 
                for j in i["ts_list"]:
                    ## 遍历start_end的元组
                    start_time_list.append(j[0])
                    end_time_list.append(j[1])
                # for index in range(len(start_time_list)-1): #这两个应该等长
                lines.append(str(i["ts_list"][0][0])+"|"+str(i["ts_list"][-1][-1])+"|"+i["text"])
                print(str(i["ts_list"][0][0])+"|"+str(i["ts_list"][-1][-1])+"|"+i["text"])
                # else:
                #     continue
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
