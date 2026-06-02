from dotenv import load_dotenv
from langchain_community.document_loaders import WebBaseLoader
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

load_dotenv()
loader=WebBaseLoader("https://www.gov.cn/zhengce/content/202604/content_7065030.htm")
text_spl=RecursiveCharacterTextSplitter(chunk_size=300,chunk_overlap=50)
docs=text_spl.split_documents(loader.load())
# print(docs)
docs=docs + docs + docs + docs
embs = DashScopeEmbeddings(api_k)