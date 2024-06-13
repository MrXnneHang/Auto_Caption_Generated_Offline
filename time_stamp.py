from funasr import AutoModel
from sentences_method import generate_new_sentences
from automodel_rec_to_sentences import convert_format #把automodel 返回的rec转换成以前Pipline的格式。

# 定义模型
model = AutoModel(
    model="./models/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch", # base
    vad_model="./models/speech_fsmn_vad_zh-cn-16k-common-pytorch", #支持长音频，自动分隔
    punc_model="./models/punc_ct-transformer_zh-cn-common-vocab272727-pytorch", # 检测语音活动，给出标点。
    #model_revision="v2.0.4",
    device="cuda:0"
)


# 生成结果并写入文件
def generate_results(wav_name, hot_word):
    res = model.generate(
        input=f"./raw_audio/{wav_name}.wav",
        hotword=hot_word,
        batch_size_s=300,
    )
    sentences = convert_format(res)
    return sentences



# 定义长文本写入函数
def write_long_txt(wav_name, cut_line,hot_word):
    sentences = generate_results(wav_name=wav_name,hot_word=hot_word)
    print("=====")
    print(sentences)
    print("=====")
    # 拆分句子
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


# 写入行到文件
def write_lines_to_file(file_path, lines):
    with open(file_path, 'w', encoding='utf-8') as file:
        for line in lines:
            file.write(line + '\n')


if __name__ == "__main__":
    write_long_txt(wav_name="example",cut_line=1000000,hot_word="饶口令")
