import yaml
import os


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