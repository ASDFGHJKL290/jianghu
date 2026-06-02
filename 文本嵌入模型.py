# 文本嵌入模型就是将文本转换成向量

import os
from langchain_community.embeddings import DashScopeEmbeddings
from dotenv import load_dotenv

load_dotenv()

embeddings = DashScopeEmbeddings(dashscope_api_key=os.getenv("DASHSCOPE_API_KEY"), model='text-embedding-v3')

# 将列表数据作为参数，处理列表数据获得向量

doc_res = embeddings.embed_documents(["nihao","woyehao"])
doc_res = embeddings.embed_documents("nihao")