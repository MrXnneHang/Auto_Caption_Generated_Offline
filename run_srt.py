from time_stamp import write_long_txt ## 带有时间戳的语音识别
from short_text_to_long import convert_short_txt_to_long  ## 合并那些原本是同义句但是被拆分成多句的句子，同时也合并他们的时间线
import os
from tqdm import tqdm
from txt_to_srt import convert_to_srt
import subprocess
import sys
"""

"""

wav_name = "08"
def main(wav_name):
    print("开始语音识别")
    write_long_txt(wav_name=wav_name,cut_line=500000) ##./tmp/.txt
    
    #print("开始处理识别后的语句")
    #convert_short_txt_to_long(wav_name=wav_name) ## ./tmp/processed.txt
    """我这里出了点问题，于是打算先去除掉这些长句部分来训练看看"""
    ## 根据processed.txt来cut
    print("开始写入srt")
    ## ./tmp/name/srt
    srt_content = convert_to_srt("./tmp/"+wav_name+".txt")
    with open("./tmp/"+wav_name+".srt", 'w', encoding='utf-8') as file:
        file.write(srt_content)

if __name__ == "__main__":
    '''
    file_names = os.listdir("./raw_audio")
    '''
    # file_names 为拖到bat上所有文件的路径列表
    file_names = sys.argv[1:]
    #print(file_names)
    for i in tqdm(range(len(file_names))):
        mp4_file = file_names[i]
        # 保留文件名，去除后缀
        wav_name = os.path.basename(mp4_file).split('.')[0]
        subprocess.run(["ffmpeg","-vsync", "0", "-i", mp4_file, "-acodec", "pcm_s16le", "-vn", "./raw_audio/"+wav_name+".wav"])
        main(wav_name)
    print("All process were done!")
