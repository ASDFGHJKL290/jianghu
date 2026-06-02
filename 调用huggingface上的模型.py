import os
from langchain_huggingface import HuggingFaceEndpoint, ChatHuggingFace
from dotenv import load_dotenv
load_dotenv()

model_name = 'Qwen/Qwen3-8B'

HF_TOKEN = os.getenv('HF_TOKEN')
# 调用huggingface上的模型
llm = HuggingFaceEndpoint(
    endpoint_url=model_name,
    huggingfacehub_api_token=HF_TOKEN
)
# 得到一个聊天模型
chat_model = ChatHuggingFace(llm=llm)
# 模型调用
resp = chat_model.invoke("周末杭州哪里好玩")
print(resp)