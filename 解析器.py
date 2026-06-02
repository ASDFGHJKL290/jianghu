#  pip install defusedxml
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
#JsonOutputParser 输出解析器
from langchain_core.output_parsers import JsonOutputParser, StrOutputParser, XMLOutputParser
from langchain_classic.chains import LLMChain
from dotenv import load_dotenv
import os

load_dotenv()

model = ChatOpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    model="qwen-plus",
)
# 字符串输出解析器
# output_parser = StrOutputParser()
# json输出解析器
# output_parser = JsonOutputParser()
# xml输出解析器
output_parser = XMLOutputParser()

# 提示模板
prompt = ChatPromptTemplate.from_messages([
    ("system", "你是一个专业的程序员"),
    ("user", "{input}")
])

# 使用LLMChain构建了一个链（0.2版本的用法）
chain = LLMChain(
    prompt=prompt,
    llm=model,
    output_parser=output_parser
)
# res = chain.invoke({"input": "langchain是什么? 问题用question 回答用ans 返回一个JSON格式"})
res = chain.invoke({"input": "langchain是什么? 使用xml格式输出"})
print(res)