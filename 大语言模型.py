from langchain_community.llms import Tongyi
from dotenv import load_dotenv
import os
load_dotenv()
# 普通的大语言模型，非聊天模型
llm = Tongyi(api_key=os.getenv("DASHSCOPE_API_KEY"),
                 base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                 model='qwen-plus')
print(llm.invoke("周末杭州哪里好玩"))