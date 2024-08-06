import os
import subprocess
import threading
import tkinter as tk
from tkinter import ttk
from tkinterdnd2 import TkinterDnD, DND_FILES
import queue
from util import load_config
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
# 设置ffmpeg的路径
FFMPEG_PATH = r"D:\program\字幕生成V2\ffmpeg-master-latest-win64-gpl-shared\bin\ffmpeg.exe"
max_workers = 1  # 可以根据需要调整并发线程数
class AudioExtractorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("视频转音频提取器")
        self.root.geometry("600x400")
        
        self.max_workers = 1
        self.executor = ThreadPoolExecutor(max_workers=self.max_workers)
        
        self.progress_var = tk.DoubleVar()
        self.lock = threading.Lock()
        self.create_widgets()
        
        self.root.drop_target_register(DND_FILES)
        self.root.dnd_bind('<<Drop>>', self.drop_videos)
        
        self.progress_queue = queue.Queue()
        self.update_progress_loop()
        
        self.audio_extracted = False
        self.audio_paths = []
        
        # Handle window close event
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def create_widgets(self):
        self.video_paths = []
        
        tk.Label(self.root, text="将视频文件拖动至此处:").pack(pady=20)
        self.video_listbox = tk.Listbox(self.root, width=80)
        self.video_listbox.pack(pady=5)
        
        # Single progress bar for both audio and caption extraction
        self.progress_bar = ttk.Progressbar(self.root, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill=tk.X, expand=1, padx=20, pady=20)
        self.progress_label = tk.Label(self.root, text="")
        
        self.extract_button = tk.Button(self.root, text="提取音频", command=self.start_extract_audio)
        self.convert_button = tk.Button(self.root, text="提取字幕", command=self.start_extract_caption)
        
        self.extract_button.pack(pady=20)
        self.convert_button.pack(pady=5)

    def drop_videos(self, event):
        files = self.root.tk.splitlist(event.data)
        for file in files:
            self.video_paths.append(file.strip('{}'))
            self.video_listbox.insert(tk.END, file.strip('{}'))

    def start_extract_caption(self):
        if not self.audio_paths:
            return

        total_files = len(self.audio_paths)
        self.progress_var.set(0)
        futures = {self.executor.submit(self.extract_subtitle, audio_path): audio_path for audio_path in self.audio_paths}

        def update_progress():
            for i, future in enumerate(as_completed(futures), 1):
                result = future.result()
                with self.lock:
                    self.progress_var.set(i / total_files * 100)
                print(f"Processed: {result}")
            # 所有任务完成后可以执行一些操作
            print("All tasks completed.")

        # 在单独的线程中运行update_progress，以免阻塞GUI
        threading.Thread(target=update_progress).start()

    def start_extract_audio(self):
        if not self.video_paths:
            return

        self.progress_bar.pack(pady=5)
        self.progress_label.pack()

        # 使用多线程处理每个视频文件
        futures = {self.executor.submit(self.extract_audio, video_path): video_path for video_path in self.video_paths}

        def update_progress():
            for i, future in enumerate(as_completed(futures), 1):
                result = future.result()
                with self.lock:
                    self.progress_var.set(i / len(futures) * 100)
                print(f"Processed: {result}")
            # 所有任务完成后可以执行一些操作
            print("All tasks completed.")
            self.audio_extracted = True

        threading.Thread(target=update_progress).start()

    def update_progress_loop(self):
        try:
            while True:
                self.progress_queue.get_nowait()
                self.progress_var.set(self.progress_var.get() + 1)
        except queue.Empty:
            pass
        self.root.after(100, self.update_progress_loop)
    def extract_audio(self, video_path):
        if not os.path.isfile(video_path):
            self.progress_queue.put((video_path, "文件不存在", 0))
            return
        
        output_dir = os.path.dirname(video_path)
        output_filename = os.path.splitext(os.path.basename(video_path))[0] + ".wav"
        output_path = os.path.join(output_dir, output_filename)

        self.progress_queue.put((video_path, "", 0))
        try:
            command = [
                FFMPEG_PATH, 
                '-i', video_path, 
                '-vn', 
                '-af', 'aresample=async=1',
                '-acodec', 'pcm_s16le', 
                '-ar', '44100', 
                '-ac', '2', 
                '-y',  # 这个选项会覆盖输出文件
                output_path
            ]
            
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            while True:
                output = process.stderr.read(1)
                if process.poll() is not None and output == b'':
                    break
                if output:
                    progress = self.calculate_progress(output)
                    self.progress_queue.put((video_path, "", progress))
            
            process.wait()
            if process.returncode == 0:
                self.progress_queue.put((video_path, f"成功提取音频到: {output_path}", 100))
            else:
                self.progress_queue.put((video_path, f"提取失败: {video_path}", 0))
        
        except subprocess.CalledProcessError as e:
            self.progress_queue.put((video_path, f"发生错误: {video_path}", 0))
        """如果output_path存在,则添加到audio_paths，并且删除video_paths中的video_path,但不删除源文件"""
        if os.path.exists(output_path):
            self.audio_paths.append(output_path)
        self.video_paths.remove(video_path)
    def extract_subtitle(self,file_path):
        """如果extract_audio未结束,则打印等待extract_audio结束"""
        if self.video_paths:
            print("等待音频提取完成")
            return
        """如果extract_audio结束,则开始提取字幕"""
        print("开始语音识别")
        config = load_config()
        cut_line = config["cut_line"]
        combine_line = config["combine_line"]
        with open("./hot_words.txt", 'r', encoding="utf-8") as f:
            lines = f.readlines()
        hot_words = ""
        for line in lines:
            hot_words += line.strip() + " "  # 不加换行, hotwords 不支持换行等分隔，只认空格，其他无效。
        base_name = write_long_txt_with_timestamp_filepath_input(file_path=file_path, cut_line=cut_line, hot_word=hot_words)  # ./tmp/.txt
        convert_short_txt_to_long(base_name, combine_line=combine_line)
        remove_chinese_commas_and_periods(f"./tmp/processed_{base_name}.txt", "./tmp/proc1.txt")
        srt_content = convert_to_srt("./tmp/proc1.txt")
        """将file_path的endwith改成.srt作为srt_path"""
        srt_path = file_path[:-4]+".srt"
        with open(srt_path, 'w', encoding='utf-8') as file:
            file.write(srt_content)

    def calculate_progress(self, output):
        # 根据实际情况计算进度，这里只是一个示例
        return 50

    def update_progress(self, video_path, message, progress):
        self.progress_label.config(text=video_path if not message else message)
        self.progress_bar['value'] = progress

    def update_progress_loop(self):
        try:
            while True:
                video_path, message, progress = self.progress_queue.get_nowait()
                self.update_progress(video_path, message, progress)
        except queue.Empty:
            pass
        self.root.after(100, self.update_progress_loop)
    def on_closing(self):
        self.executor.shutdown(wait=False)
        self.root.destroy()
        os._exit(0)  # Force exit to ensure all threads are terminated


from short_text_to_long import convert_short_txt_to_long
from txt_to_srt import convert_to_srt, remove_chinese_commas_and_periods
from automodel_rec_to_sentences import convert_format
from sentences_method import generate_new_sentences
from util import FunASRModel,load_config
from time_stamp import write_lines_to_file
import os
# 定义长文本写入函数
def write_long_txt_with_timestamp_filepath_input(file_path, cut_line,hot_word,debug=True):
    Model = FunASRModel()
    model = Model.full_version()
    config = load_config()
    batch_size_s = config["batch_size_s"]
    response = model.generate(
                input=file_path,
                hotword=hot_word,
                batch_size_s=batch_size_s
            )
    sentences = convert_format(response)


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

    """写入file_path的base_name为名的txt文件"""
    base_name = os.path.basename(file_path)
    write_lines_to_file(f'./tmp/{base_name}.txt', lines)
    print("开始保存文本")
    # 将 文本文件保存到带时间戳的文件夹中
    txt_path = file_path[:-4]+".txt"
    with open(txt_path, 'w', encoding='utf-8') as file:
        file.write(response[0]["text"])
    return base_name



if __name__ == "__main__":
    root = TkinterDnD.Tk()
    app = AudioExtractorApp(root)
    root.mainloop()
