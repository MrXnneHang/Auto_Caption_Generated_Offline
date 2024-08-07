import yaml
import os
from funasr import AutoModel
from datetime import datetime

def load_config():

    # 加载YAML文件
    if not os.path.isfile("./config.yml"):
        print("error:你的config.yml不存在，请创建，并且这样初始化")
        print("cut_line: 1000")
        print("combine_line: 400")
        return 0
    else:
        with open('./config.yml', 'r', encoding='utf-8') as file:
            config = yaml.safe_load(file)

        return config
class FunASRModel:

    def __init__(self):
        """
        """
        self.config = load_config()
        self.base_model = self.config["base_model"]
        self.vad_model = self.config["vad_model"]
        self.punc_model = self.config["punc_model"]
        self.device = self.config["device"]

    def full_version(self):
        funasr_model = AutoModel(
            model=self.base_model,  # base
            vad_model=self.vad_model,  # 检测语音活动，自动分隔
            punc_model=self.punc_model,  # 给出标点。
            # model_revision="v2.0.4",
            device=self.device
        )
        return funasr_model

    def only_vad(self):
        model = AutoModel(model=self.vad_model,
                          device=self.device)
        return model

    def only_txt(self):
        model = AutoModel(model = self.base_model,
                          device=self.device)
    def only_puc(self):
        model = AutoModel(model = self.punc_model,
                          device=self.device)
        return model


def generate_results(model,wav_name, hot_word="",debug=False):
    config = load_config()
    batch_size_s = config["batch_size_s"]
    if type(wav_name) is list:
        if hot_word!="":
            res = model.generate(
                input=wav_name,
                hotword=hot_word,
                batch_size_s=batch_size_s,
            )
        else:
            res = model.generate(
                input=wav_name,
                batch_size_s=batch_size_s,
            )
    else:
        if hot_word!="":
            res = model.generate(
                input=f"./raw_audio/{wav_name}.wav",
                hotword=hot_word,
                batch_size_s=batch_size_s
            )
        else:
            res = model.generate(
                input=f"./raw_audio/{wav_name}.wav",
                batch_size_s=batch_size_s,
            )

    return res


def write_long_txt(response,wav_name,output_dir):

    print("开始保存文本")
    # 将 文本文件保存到带时间戳的文件夹中
    srt_path = os.path.join(output_dir,f"{wav_name}.txt")
    with open(srt_path, 'w', encoding='utf-8') as file:
        file.write(response[0]["text"])