from time_stamp import write_long_txt ## 带有时间戳的语音识别
from short_text_to_long import convert_short_txt_to_long  ## 合并那些原本是同义句但是被拆分成多句的句子，同时也合并他们的时间线
import os
from tqdm import tqdm

from txt_to_srt import convert_to_srt, remove_chinese_commas_and_periods

"""

"""

def main(wav_name):
    print("开始语音识别")
    with open("./hot_words.txt",'r',encoding="utf-8") as f:
        lines = f.readlines()
    hot_words = ""
    for line in lines:
        hot_words += line[:-1] #不加换行
        hot_words += " "# hotwords不支持,换行等分隔，只认空格，其他无效。
    #print(hot_words)
    write_long_txt(wav_name=wav_name,cut_line=500000,hot_word=hot_words) ##./tmp/.txt

    #print("开始处理识别后的语句")
    #convert_short_txt_to_long(wav_name=wav_name) ## ./tmp/processed.txt
    ## 根据processed.txt来cut
    # remove_duplicate_lines("./tmp/"+wav_name+".txt")
    remove_chinese_commas_and_periods("./tmp/"+wav_name+".txt", "./tmp/proc1.txt")
    print("开始写入srt")

    ## ./tmp/name/srt
    # srt_content = convert_to_srt("./tmp/"+wav_name+".txt")
    # with open("./tmp/"+wav_name+".srt", 'w', encoding='utf-8') as file:
    #     file.write(srt_content)

    srt_content = convert_to_srt("./tmp/proc1.txt")
    with open("./tmp/"+wav_name+".srt", 'w', encoding='utf-8') as file:
        file.write(srt_content)

if __name__ == "__main__":
    file_names = os.listdir("./raw_audio")
    if "desktop.ini" in file_names:
        file_names.remove("desktop.ini")
    if "put wav files here.txt" in file_names:
        file_names.remove("put wav files here.txt")
    for i in tqdm(range(len(file_names))):
        if not file_names[i].endswith(".wav"):
            print(f"{file_names[i]}并不是支持的wav格式,skip..")
            continue
        main(wav_name=file_names[i].split(".")[0])
    print("All process were done!")