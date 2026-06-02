import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()
llm=ChatOpenAI(api_key=os.getenv("DASHSCOPE_API_KEY"),base_url=os.getenv("DASHSCOPE_BASE_URL"),model='qwen-max')
res=llm.invoke('什么是大模型')
print(res)