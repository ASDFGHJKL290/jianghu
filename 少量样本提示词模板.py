import os

from dotenv import load_dotenv
from langchain_core.prompts import PromptTemplate, FewShotPromptTemplate
import langchain_openai
load_dotenv()

# 创建示例
examples = [
    {"input": "2+2", "output": "4", "description": "加法运算"},
    {"input": "5-2", "output": "3", "description": "减法运算"},
]
prompt_template = "你是一个数学专家,算式： {input} 值： {output} 使用： {description} "

prompt_sample = PromptTemplate.from_template(prompt_template)

prompt = FewShotPromptTemplate(
    examples=examples,
    example_prompt=prompt_sample,
    # 告诉大模型要按照这个格式输出description
    suffix="""你是一个数学专家,请计算： {input} 值： {output} """,
    input_variables=["input", "output"],
)

print(prompt.format(input="2*5", output="10"))

llm = langchain_openai.ChatOpenAI(api_key=os.getenv("DASHSCOPE_API_KEY"),
                                  base_url=os.getenv("DASHSCOPE_BASE_URL"),
                                  model_name='qwen-plus')

result = llm.invoke(prompt.format(input="2*5", output="10"))
print(result)