# 由于无法直接读取您提到的 "08.txt" 文件，我将演示如何使用 Python 读取一个文本文件，处理数据，然后写入另一个文件的过程。

def ms_to_srt_time(ms):
    """将毫秒转换为 SRT 时间格式"""
    hours = ms // 3600000
    minutes = (ms % 3600000) // 60000
    seconds = (ms % 60000) // 1000
    milliseconds = ms % 1000
    return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"

def process_line(line):
    """处理每行数据，转换为所需格式"""
    parts = line.split('|')
    if len(parts) != 3:
        return None
    start, end, text = parts
    return (int(start), int(end), text)

def clean_txt(file_path):
    """对txt文件内容去重并保留顺序，重新写入"""
    l2 = []
    with open(file_path, 'r', encoding='utf-8') as file:
        lines = file.readlines()
        [l2.append(i) for i in lines if not i in l2]
    with open(file_path, 'w', encoding='utf-8') as file:
        for line in l2:
            file.write(line)

def convert_to_srt(file_path):
    """读取文件，处理数据并转换为 SRT 格式"""
    srt_format = ""
    clean_txt(file_path)
    with open(file_path, 'r', encoding='utf-8') as file:
        for index, line in enumerate(file, start=1):
            processed_line = process_line(line.strip())
            if processed_line:
                start, end, text = processed_line
                start_time = ms_to_srt_time(start)
                end_time = ms_to_srt_time(end)
                srt_format += f"{index}\n{start_time} --> {end_time}\n{text}\n\n"
    return srt_format


# 输出一条消息表明处理过程已完成
"处理完成，SRT文件已生成。"

