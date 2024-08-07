import os
import argparse
from tqdm import tqdm
from datetime import datetime
from time_stamp import write_long_txt_with_timestamp  # 带有时间戳的语音识别
from short_text_to_long import convert_short_txt_to_long  # 合并那些原本是同一句但是被拆分成多句的句子，同时也合并他们的时间线
from txt_to_srt import convert_to_srt, remove_chinese_commas_and_periods
from util import load_config,write_long_txt


def main(wav_name,output_dir):
    # try:
        print("开始语音识别")
        config = load_config()
        cut_line = config["cut_line"]
        combine_line = config["combine_line"]
        with open("./hot_words.txt", 'r', encoding="utf-8") as f:
            lines = f.readlines()
        hot_words = ""
        for line in lines:
            hot_words += line.strip() + " "  # 不加换行, hotwords 不支持换行等分隔，只认空格，其他无效。
        response = write_long_txt_with_timestamp(wav_name=wav_name, cut_line=cut_line, hot_word=hot_words)  # ./tmp/.txt
        write_long_txt(response=response,wav_name=wav_name,output_dir=output_dir)
        convert_short_txt_to_long(wav_name, combine_line=combine_line)
        remove_chinese_commas_and_periods(f"./tmp/processed_{wav_name}.txt", "./tmp/proc1.txt")
        srt_content = convert_to_srt("./tmp/proc1.txt")
        os.makedirs(output_dir, exist_ok=True)

        # 将 SRT 文件保存到带时间戳的文件夹中
        srt_path = os.path.join(output_dir, wav_name + ".srt")
        with open(srt_path, 'w', encoding='utf-8') as file:
            file.write(srt_content)
    # except Exception as e:
    #     print(f"Error processing {wav_name}: {e}")
    #     return wav_name





if __name__ == "__main__":
    # 删除 ./tmp 下的所有 txt 文件，除了 generate will be here.txt
    tmp_dir = "./tmp"
    error_files = []
    for filename in os.listdir(tmp_dir):
        file_path = os.path.join(tmp_dir, filename)
        if filename.endswith(".txt") and filename != "generate will be here.txt":
            try:
                os.remove(file_path)
            except Exception as e:
                print(f"Error deleting file {file_path}: {e}")
    # 获取当前时间，并创建带时间戳的文件夹
    timestamp = datetime.now().strftime("%Y-%m-%d-%H-%M")
    output_dir = os.path.join("./tmp", timestamp)
    os.makedirs(output_dir, exist_ok=True)
    # 处理 ./raw_audio 文件夹中的所有音频文件
    file_names = os.listdir("./raw_audio")
    if "desktop.ini" in file_names:
        file_names.remove("desktop.ini")
    if "put wav files here.txt" in file_names:
        file_names.remove("put wav files here.txt")
    for i in tqdm(range(len(file_names))):
        # bug fix one WAV尾缀的支持
        if not (file_names[i].endswith(".wav") or file_names[i].endswith(".WAV")):
            print(f"{file_names[i]}并不是支持的 wav 格式, skip...")
            continue
        error_file = main(wav_name=file_names[i].split(".")[0],output_dir=output_dir)
        error_files.append(error_file)
    print("All processes were done!")
    if error_files:
        print(f"以下文件由于错误未能转录: {error_files}")
