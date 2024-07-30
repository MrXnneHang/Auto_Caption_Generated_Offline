from time_stamp import write_lines_to_file

def convert_short_txt_to_long(wav_name,combine_line):
    latest_start = 0
    latest_end = 0
    latest_content = ""
    new_lines = []
    with open(f'./tmp/{wav_name}.txt', 'r', encoding='utf-8') as file:
        for line in file:
            start_and_end = line.split("|")[:2]
            content = line.split("|")[2]
            if (int(start_and_end[0])-int(latest_end)<combine_line) and (latest_end!=0): #合并这两行
                new_line = latest_start+"|"+start_and_end[1]+"|"+latest_content.replace("\n","")+content
                new_lines.pop(-1)
                new_lines.append(new_line)
            else:
                new_lines.append(line)
            latest_content = content
            latest_start=start_and_end[0]
            latest_end=start_and_end[1]
 
    # 删除单独占行的回车'\n'
    result = []
    for line in new_lines:
        parts = line.split("\n")
        filtered_parts = [part for part in parts if part != ""]
        result.append("\n".join(filtered_parts))
    new_lines = result
 
 
    write_lines_to_file(f"./tmp/processed_{wav_name}.txt",new_lines)