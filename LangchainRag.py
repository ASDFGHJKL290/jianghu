from langchain_classic.chains.combine_documents import create_stuff_documents_chain
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langchain_classic.chains import create_retrieval_chain
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import DashScopeEmbeddings
from dotenv import load_dotenv
import os

load_dotenv()
# 拿到一个向量模型
embs = DashScopeEmbeddings(dashscope_api_key=os.getenv("DASHSCOPE_API_KEY"), model="text-embedding-v4")
# 指明向量数据库的地址
save_path = 'faiss_store'
# 获得向量数据库对象
vector_store = FAISS.load_local(
    folder_path=save_path,
    embeddings=embs,
    allow_dangerous_deserialization=True # 允许加载PKL文件
)
# 检索——向量数据库中做相似度匹配
input = '转诊的规则有哪些？'

# 创建提示词模版
prompt = ChatPromptTemplate.from_template("""仅根据提供的上下文回答以下问题:
<context>
{context}
</context>
问题: {input}""")


# 增强生成——LLM介入

# 通过langchain的方式获得模型
llm = ChatOpenAI(api_key=os.getenv("DASHSCOPE_API_KEY"),base_url=os.getenv("DASHSCOPE_BASE_URL"),model='qwen3-max')
# 检索、拼接提示词、推理
# 创建文档处理链：把提示词模版交给大模型
docs_chain = create_stuff_documents_chain(llm,prompt)
# 获得向量数据库的检索器：用于做把输入的内容，和向量数据库中的内容进行相似度计算，获得返回的结果
retr = vector_store.as_retriever()
# 获得检索链对象
res_chain = create_retrieval_chain(retr,docs_chain)
# 调用检索链对象，实现对用户问题的检索增强生成（RAG）
result = res_chain.invoke({"input":input})
print(result)
