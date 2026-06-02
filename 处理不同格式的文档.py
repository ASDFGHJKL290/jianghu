# 处理pdf文档
# pip install pypdf
from langchain_community.document_loaders import PyPDFLoader

loader = PyPDFLoader('财务管理文档.pdf')
print(loader.load())
print("*"*50)
print(loader.load()[0])


# 处理word文档
# pip install unstructured
import nltk
nltk.download('punkt')
nltk.download('averaged_perceptron_tagger')
from langchain_community.document_loaders import UnstructuredWordDocumentLoader

loader = UnstructuredWordDocumentLoader('人事管理流程.docx')
print(loader.load())

# 读取在线pdf
from langchain_community.document_loaders import PyPDFLoader

loader = PyPDFLoader("https://arxiv.org/pdf/2302.03803")
data = loader.load()
print(f"第0页：\n{data[0].page_content}")