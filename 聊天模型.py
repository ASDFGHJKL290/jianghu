import os

from dotenv import load_dotenv
from langchain_community.chat_models import ChatTongyi
from langchain_core.messages import SystemMessage, HumanMessage

load_dotenv()

human_text='你好啊'
system_text='你是一个聊天小助手，你的代号是0731'
chat_model=ChatTongyi(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url=os.getenv("DASHSCOPE_BASE_URL"),
    model='qwen-plus'
)
messages=[SystemMessage(content=system_text),HumanMessage(content=human_text)]
res=chat_model.invoke(messages)
print(res)