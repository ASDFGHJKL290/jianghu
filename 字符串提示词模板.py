from langchain_openai import ChatOpenAI
# 导入LangChain中的提示模板
from langchain_core.prompts import PromptTemplate
import os
from dotenv import load_dotenv

load_dotenv()

# 创建模型实例
model = ChatOpenAI(api_key=os.getenv("DASHSCOPE_API_KEY"),
                   base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                   model='qwen-plus')

# 创建一个字符串提示词模版
prompt = PromptTemplate(
    template="您是一位专业的程序员。\n对于信息 {text} 进行简短描述"
)
# 使用指明提示词中的变量值
inputs = prompt.format(text="大模型")
result = model.invoke(inputs)
print(result)