# 模型调用的几种方式

import os
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
load_dotenv()

# 使用langchain调用deepseek模型
# "deepseek-reasoner":带思维链
llm = init_chat_model(
    "deepseek-reasoner",
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url=os.getenv("DEEPSEEK_BASE_URL"),
    temperature=1
)

res = llm.invoke("你是谁")
print(res.content)
print("*"*50)

from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url=os.getenv("DEEPSEEK_BASE_URL"),
    model_name="deepseek-reasoner"
)

res = llm.invoke("你是谁")
print(res.content)
print("*"*50)

from langchain_deepseek import ChatDeepSeek

llm = ChatDeepSeek(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url=os.getenv("DEEPSEEK_BASE_URL"),
    model_name="deepseek-reasoner"
)
res = llm.invoke("你是谁")
print(res.content)
print("*"*50)