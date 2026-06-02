from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
# faiss  InMemoryVectorStore 基于内存的向量数据库
from langchain_core.vectorstores import InMemoryVectorStore
# 导入Langchain的runnable组件
from langchain_core.runnables import RunnableMap, RunnableBranch, RunnableLambda
from langchain_tavily import TavilySearch
from langchain_huggingface import HuggingFaceEmbeddings
from dotenv import load_dotenv
import os

load_dotenv()

class TravelQASystem:
    def __init__(self,openai_api_key,serpapi_api_key,embed_path):
        # 初始化语言模型
        self.llm = ChatOpenAI(api_key=openai_api_key,
                              base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                              model="qwen-plus")

        # 初始化搜索工具
        self.search = TavilySearch(tavily_api_key=serpapi_api_key)

        # 初始化嵌入模型
        self.embeddings = HuggingFaceEmbeddings(model_name=embed_path)

        # 构建景点知识库（后期可以补充全国的完整的知识库)
        self.attraction_data = [
            "故宫：北京地标，明清皇宫，开放时间8:30-17:00",
            "颐和园：皇家园林，昆明湖、长廊等景点",
            "八达岭长城：距离市区70公里，建议游览3-4小时"
        ]

        # 使用内存型向量存储类
        self.vector_store = InMemoryVectorStore.from_texts(
            self.attraction_data, self.embeddings, k=1
        )

    # 管道：
    # 1.问题解析：识别地点（景点）和天气（可选）
    # 2.去本地知识库查询景点 和 通过TavilySearch查询该地点的天气（可选）
    # 3.把获得的结果整合好后交给大模型进行推理生成答案
    def setup_runnable_pipeline(self):
        # 1.问题解析：识别地点（景点）和天气（可选）
        # input_data = {"user_question": "今天故宫天气怎么样"}
        parse_prompt = ChatPromptTemplate.from_messages([
            SystemMessage(content="你是旅游助手，需从用户问题中提取地点和查询类型（天气/景点介绍/行程规划）"),
            ("user","""问题：{user_question}请以JSON格式返回：{{"location": "地点", "type": "查询类型"}}""")
        ])
        # 解析问题的模块
        parse_module = parse_prompt | self.llm | JsonOutputParser()

        # 2.获取数据（并行获取）：天气信息+景点的信息
        # 天气查询： RunnableLambda:是一个可以被并行处理的Lambda
        weather_query = RunnableLambda(
            lambda x: self.search.invoke(f"{x['location']}的天气怎么样")
        )
        # 景点信息查询：在本地知识库查询。管道符号会对数据做自动类型转换。检索器的类型（Runnable类型），管道符自定把lambda转换成Runnable类型
        # "故宫：北京地标，明清皇宫，开放时间8:30-17:00",
        # json: {"location": "故宫", "type": "景点查询"}
        attraction_retrieve = (lambda x: x['location']) | self.vector_store.as_retriever() | (
            lambda x: x[0].page_content)#  "故宫：北京地标，明清皇宫，开放时间8:30-17:00",

        # RunnableMap 3个方法并行执行
        data_acquisition = RunnableMap({
            "weather":weather_query,
            "attraction":attraction_retrieve,
            "location":(lambda x: x['location'])
        })

        # 3.回答生成模块：整合信息并格式化
        generate_prompt = ChatPromptTemplate.from_messages([
            SystemMessage(content="你是专业旅游顾问，需结合景点信息和天气生成建议"),
            ("user","""地点：{location}
                        景点信息：{attraction}
                        天气情况：{weather}
                        请生成1条行程建议，包含注意事项（如天气相关准备）
            """)
        ])
        generate_module = generate_prompt | self.llm | (lambda x: x.content.strip())

        # RunnableBranch:条件判断
        # 核心：问答系统的流水线
        self.travel_qa_pipeline = (
            parse_module |
            # json: {"location": "故宫", "type": "景点查询"}
            (lambda x: {"location": x['location'], "type": x['type']}) |
            RunnableBranch(
                # json: {"location": "故宫", "type": "景点查询"}
                # 如果type里面有‘天气’的话，则执行data_acquisition
                (lambda x: '天气' in x['type'],data_acquisition),
                # (lambda x: '地点' in x['type'], data_acquisition),
                # json: {"location": "故宫", "type": "景点查询"}
                lambda x: {"location": x["location"],
                           "attraction": attraction_retrieve.invoke(x)}
                # json: {"location": "故宫", "attraction": "故宫：北京地标，明清皇宫，开放时间8:30-17:00"}
            ) | generate_module
        )
    # 处理用户的问题
    def process_user_question(self,user_question):
        # 封装用户的问题成为一个字典
        input_data = {"user_question":user_question}
        # 让解析、查询、生成答案的流水线开始工作
        response = self.travel_qa_pipeline.invoke(input_data)


        return response



if __name__ == '__main__':

    # 替换为实际API密钥
    OPENAI_API_KEY = os.getenv("DASHSCOPE_API_KEY")
    # https://www.tavily.com/
    SERPAPI_API_KEY = os.getenv("TAVILY_API_KEY")
    embed_path = r"C:\Users\aaa\PycharmProjects\day24\models\BAAI\bge-large-zh-v1___5"

    # 初始化系统
    travel_qa = TravelQASystem(OPENAI_API_KEY, SERPAPI_API_KEY, embed_path)
    # 初始化管道流水线
    travel_qa.setup_runnable_pipeline()

    # 根据提的问题，包含天气的内容，所以要搜索天气，并且包含景点的内容，所以要去景点知识库里搜索景点信息，llm要整合这些信息生成温馨小提示
    question = '今天故宫的天气怎么样'
    result = travel_qa.process_user_question(question)
    print(result)
