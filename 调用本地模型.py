# from modelscope import snapshot_download
# model_dir = snapshot_download('maidalun/bce-embedding-base_v1', cache_dir="D:\LLM\Local_model")

from langchain_huggingface import HuggingFaceEmbeddings

model_name = r'C:\Users\aaa\PycharmProjects\day24\models\BAAI\bge-large-zh-v1___5'

encode_kwargs={'normalize_embeddings': True}
# 获得本地向量模型对象
embeddings = HuggingFaceEmbeddings(
    model_name=model_name,
    encode_kwargs=encode_kwargs
)

# 调用
embeddings.embed_documents(['nihao','nihaohao'])
print(embeddings.embed_query('nihao'))