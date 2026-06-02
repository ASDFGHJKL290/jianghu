from langchain_openai import ChatOpenAI
# 导入LangChain中的提示模板
from langchain_core.prompts import ChatPromptTemplate
import os
from dotenv import load_dotenv
load_dotenv()

# 提示词文本
template = "你是一个翻译专家,擅长将 {input_language} 语言翻译成 {output_language}语言."
# 得到聊天提示词模版
# ("system",template)：给AI设定固定角色
# ("human","{text}")：用户输入的内容
chat_prompt = ChatPromptTemplate.from_messages(
    [("system",template),("human","{text}")]
)

# 创建模型实例
model = ChatOpenAI(api_key=os.getenv("DASHSCOPE_API_KEY"),
                   base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                   model='qwen-plus')

# 传入提示词模版中的变量的值
messages = chat_prompt.format_messages(input_language='中文',output_language='英文',text='今天周五啦，晚上嗨一下！')

# print(messages)

# 调用模型
result = model.invoke(messages)
print(result)