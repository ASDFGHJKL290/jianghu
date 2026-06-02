import os
# 加载网页资源
import bs4
# 文本分段器
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import WebBaseLoader
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_community.vectorstores import FAISS
from dotenv import load_dotenv
load_dotenv()
# 用于获取网页上的数据
loader = WebBaseLoader("https://www.gov.cn/zhengce/content/202604/content_7065030.htm")
# print(loader.load())
# 数据分段器
text_spl = RecursiveCharacterTextSplitter(chunk_size=300,chunk_overlap=50)
docs = text_spl.split_documents(loader.load())
# print(docs) # 元数据：描述数据的数据称为元数据
# 让数据多一些
docs = docs + docs + docs + docs
#文档转换成向量
# 拿到一个向量模型
embs = DashScopeEmbeddings(dashscope_api_key=os.getenv("DASHSCOPE_API_KEY"),model='text-embedding-v4')
# 使用FAISS向量数据库
vect = None
batch_size = 10
for i in range(0,len(docs),batch_size):
     batch_docs = docs[i:i+batch_size]
     print(f'第{i // batch_size + 1}批次 文档数量: {len(batch_docs)}')
     if i==0:
        # 第一次创建:FAISS向量数据库对象将batch_docs这一批的文档转换成了向量
        vect = FAISS.from_documents(batch_docs,embs)
     else:
        new_vect = FAISS.from_documents(batch_docs, embs)
        vect.merge_from(new_vect)
# 合并完后将向量数据保存到向量数据库faiss_store中
vect.save_local('faiss_store')
