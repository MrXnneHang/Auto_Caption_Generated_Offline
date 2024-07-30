from time_stamp import write_long_txt_with_timestamp
import re

ignore = [",",".","!","?","！","。","，","？","、"]
def convert_to_srt(response, output):
    def ms_to_timecode(ms):
        hours = ms // 3600000
        ms = ms % 3600000
        minutes = ms // 60000
        ms = ms % 60000
        seconds = ms // 1000
        ms = ms % 1000
        return f"{hours:02}:{minutes:02}:{seconds:02},{ms:03}"
    srt_index = 1
    biaodian = 0
    for index,text in enumerate(response["text"]): 
        if text not in ignore:
            #print(text)
            print(index-biaodian)
            start = ms_to_timecode(response["timestamp"][index-biaodian][0])
            end = ms_to_timecode(response["timestamp"][index-biaodian][1])
            with open(output, 'a', encoding='utf-8') as file:
                file.write(f"{srt_index}\n")
                file.write(f"{start} --> {end}\n")
                file.write(f"{text}\n\n")
                srt_index += 1
        else:
            biaodian += 1

            
    print(f"SRT file saved to {output}")

response = write_long_txt_with_timestamp(wav_name="part2", cut_line=300, hot_word="")
print(len(response[0]["timestamp"]))
print(convert_to_srt(response[0],"./srt.srt"))
with open("tx.txt","w",encoding="utf-8") as f:
    f.write(response[0]["text"])
    f.close()
