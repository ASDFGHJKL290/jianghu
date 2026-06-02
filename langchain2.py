import os

from dotenv import load_dotenv
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.prompts import ChatPromptTemplate

load_dotenv()
embs = DashScopeEmbeddings(dashscope_api_key=os.getenv("DASHSCOPE_API_KEY"),model='text-embedding-v4')
save_path = 'faiss_store'
vector_store=FAISS.load_local(
    filepath='faiss_store',
    embs=embs,
    allow_dangerous_deserialization=True,
)
input = '转诊的规则有哪些？'
prompt = ChatPromptTemplate.from_template()