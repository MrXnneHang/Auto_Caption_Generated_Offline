def seg_sentences(sentences,cutline):
    all_cut_points_in_sentences = []
    new_texts_in_sentences = []
    new_ts_list_in_sentences = []
    new_seg_text_in_sentences = []
    for sentence_index,sentence in enumerate(sentences):
        cut_points = []

        
        latest_end = 0
        latest_start = 0
        #print(sentence["ts_list"])
        for ts_index,start_end in enumerate(sentence["ts_list"]):
            if start_end[0] - latest_end > 1000 and latest_end != 0:     # 这一个字的开始时间 - 上一个字的结束时间 > cutline
                cut_points.append((sentence_index, ts_index))
            latest_end = start_end[1]
            latest_start = start_end[0]
        # print(f"找到所有断点:{cut_points}")
        all_cut_points_in_sentences.append(cut_points)
        ## 一句内有多个断点
        # 一个index 代表了一个断点
        left_text = ''
        right_text = ''
        last_text = ''
        new_texts = []
        new_ts_lists = []
        new_seg_text_list = []
        if cut_points !=[]:
            ## 获取 new_ts_list
            for index,cut_point in enumerate(cut_points):
                new_ts_list = []
                if index == 0 :##第一字句
                    new_ts_list = sentence["ts_list"][:cut_point[1]]
                    new_ts_lists.append(new_ts_list)
                elif index!=0 and index<len(cut_points): ## 中间字句
                    new_ts_list = sentence["ts_list"][cut_points[index-1][1]:cut_point[1]]
                    new_ts_lists.append(new_ts_list)
                #最后字句

            new_ts_list = sentence["ts_list"][cut_points[-1][1]:]
            new_ts_lists.append(new_ts_list)

            ## 获取new texts
            for index,cut_point in enumerate(cut_points):
                ## cut texts
                if index != 0:
                    for n in range(cut_points[index-1][1],cut_points[index][1]):
                        left_text+=sentence["text_seg"][n*2]
                    new_texts.append(left_text)
                    # print(f"拆分短句1:{left_text}")
                    left_text="" ## 防止被叠加
                else:
                    for n in range(cut_point[1]):
                        left_text+=sentence["text_seg"][n*2]
                    new_texts.append(left_text)
                    # print(f"拆分短句2:{left_text}")
                    left_text=""
                last_text=""
                for n in range(cut_points[-1][1],len(sentence["text"])-1):
                    last_text+=sentence["text_seg"][n*2]
            new_texts.append(last_text)
            # print(f"拆分短句3:{last_text}")
            print(f"新短句:{new_texts}")
            

            ## 生成new_seg_texts
            for index,text in enumerate(new_texts):
                new_seg_text = ''
                for i,char in enumerate(text):
                    new_seg_text += char
                    new_seg_text += " "
                new_seg_text_list.append(new_seg_text)
            new_texts_in_sentences.append(new_texts)
            new_ts_list_in_sentences.append(new_ts_lists)
            new_seg_text_in_sentences.append(new_seg_text_list)
            # print(f"new_seg_text_list:{new_seg_text_list}")

        else:
            new_texts_in_sentences.append("")
            new_ts_list_in_sentences.append([])
            new_seg_text_in_sentences.append("")
            continue
            ## 如果没有断点，就不操作.
        print(f"找到所有断点:{cut_points}")

    return new_texts_in_sentences,new_ts_list_in_sentences,new_seg_text_in_sentences,all_cut_points_in_sentences

def replace_and_expand(lst, replacements):
    offset = 0
    for index, new_sublist in replacements:
        adjusted_index = index + offset
        lst = lst[:adjusted_index] + new_sublist + lst[adjusted_index + 1:]
        offset += len(new_sublist) - 1
    return lst

def generate_replacements(sentences,cutline):
    new_texts_in_sentences,new_ts_list_in_sentences_,new_seg_text_in_sentences,all_cut_points_in_sentences = seg_sentences(sentences,cutline=cutline)
    print(f"新短句集:{new_texts_in_sentences}\n")
    print(f"新Ts集:{new_ts_list_in_sentences_}\n")
    print(f"新单字集:{new_seg_text_in_sentences}\n")
    print(f"断点集:{all_cut_points_in_sentences}\n")
    # 替换规则：(索引, 新子列表)
    replacements = []
    for sentence_index,cut_points in enumerate(all_cut_points_in_sentences):
        if len(cut_points)!=0:
            new_sentences = []
            for i in range(len(cut_points)+1):
                new_sentences.append({"text":new_texts_in_sentences[sentence_index][i],"ts_list":new_ts_list_in_sentences_[sentence_index][i],
                                 "text_seg":new_seg_text_in_sentences[sentence_index][i]})
            print(f"新句子{new_sentences}")
            replacements.append((sentence_index,new_sentences))
    return replacements

def generate_new_sentences(sentences,cutline):
    replacements = generate_replacements(sentences=sentences,cutline=cutline)
    all_new_sentences = replace_and_expand(sentences,replacements)
    return all_new_sentences