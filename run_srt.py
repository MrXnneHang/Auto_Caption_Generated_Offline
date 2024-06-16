import os
from tqdm import tqdm
from datetime import datetime
from time_stamp import write_long_txt  # 带有时间戳的语音识别
from short_text_to_long import convert_short_txt_to_long  # 合并那些原本是同义句但是被拆分成多句的句子，同时也合并他们的时间线
from txt_to_srt import convert_to_srt, remove_chinese_commas_and_periods

def main(wav_name):
    print("开始语音识别")
    with open("./hot_words.txt", 'r', encoding="utf-8") as f:
        lines = f.readlines()
    hot_words = ""
    for line in lines:
        hot_words += line.strip() + " "  # 不加换行, hotwords 不支持换行等分隔，只认空格，其他无效。

    write_long_txt(wav_name=wav_name, cut_line=500000, hot_word=hot_words)  # ./tmp/.txt

    remove_chinese_commas_and_periods("./tmp/" + wav_name + ".txt", "./tmp/proc1.txt")
    print("开始写入 srt")

    srt_content = convert_to_srt("./tmp/proc1.txt")

    # 获取当前时间，并创建带时间戳的文件夹
    timestamp = datetime.now().strftime("%Y-%m-%d-%H-%M")
    output_dir = os.path.join("./tmp", timestamp)
    os.makedirs(output_dir, exist_ok=True)

    # 将 SRT 文件保存到带时间戳的文件夹中
    srt_path = os.path.join(output_dir, wav_name + ".srt")
    with open(srt_path, 'w', encoding='utf-8') as file:
        file.write(srt_content)

if __name__ == "__main__":
    # 删除 ./tmp 下的所有 txt 文件，除了 generate will be here.txt
    tmp_dir = "./tmp"
    for filename in os.listdir(tmp_dir):
        file_path = os.path.join(tmp_dir, filename)
        if filename.endswith(".txt") and filename != "generate will be here.txt":
            try:
                os.remove(file_path)
            except Exception as e:
                print(f"Error deleting file {file_path}: {e}")

    # 处理原始音频文件
    file_names = os.listdir("./raw_audio")
    if "desktop.ini" in file_names:
        file_names.remove("desktop.ini")
    if "put wav files here.txt" in file_names:
        file_names.remove("put wav files here.txt")
    for i in tqdm(range(len(file_names))):
        if not file_names[i].endswith(".wav"):
            print(f"{file_names[i]}并不是支持的 wav 格式, skip...")
            continue
        main(wav_name=file_names[i].split(".")[0])
    print("All processes were done!")
