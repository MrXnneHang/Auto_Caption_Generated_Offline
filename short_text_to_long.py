from time_stamp import write_lines_to_file

def convert_short_txt_to_long(wav_name, combine_line):
    latest_start = 0
    latest_end = 0
    latest_content = ""
    new_lines = []

    with open(f'./tmp/{wav_name}.txt', 'r', encoding='utf-8') as file:
        for line in file:
            # 分割行获取开始时间，结束时间和内容
            parts = line.strip().split("|")
            start = int(parts[0])
            end = int(parts[1])
            content = parts[2]

            # 检查是否需要合并
            if (start - latest_end < combine_line) and (latest_end != 0) and (len(latest_content)<20 or len(content)<5):
                # 合并行
                latest_content = latest_content.replace('\n', '')
                new_line = f"{latest_start}|{end}|{latest_content}{content}"
                # 更新最新行的结束时间和内容
                new_lines[-1] = new_line
                latest_end = end
                latest_start = latest_start
                latest_content = f"{latest_content}{content}"
            else:
                # 添加新行
                new_line = f"{start}|{end}|{content}"
                new_lines.append(new_line)
                # 更新最新开始时间
                latest_start = start

                # 更新最新的结束时间和内容
                latest_end = end
                latest_content = content

            # 调试打印，查看每行的处理结果
            print(f"Processed line: {new_line}")

    # 删除单独占行的回车 '\n'
    result = []
    for line in new_lines:
        parts = line.split("\n")
        filtered_parts = [part for part in parts if part != ""]
        result.append("\n".join(filtered_parts))

    new_lines = result

    # 写入处理后的文件
    write_lines_to_file(f"./tmp/processed_{wav_name}.txt", new_lines)

if __name__ == "__main__":
    convert_short_txt_to_long("建设工程合同纠纷_（2021）最高法民终749号", 400)
    print("done")