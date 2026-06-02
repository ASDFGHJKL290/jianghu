from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.runnables import RunnableMap, RunnableBranch, RunnableLambda
from langchain_tavily import TavilySearch
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from dotenv import load_dotenv
import os

load_dotenv()

class TravelQASystem:
    def __init__(self, openai_api_key, tavily_api_key, embed_path, knowledge_file):
        self.llm = ChatOpenAI(
            api_key=openai_api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model="qwen-plus"
        )

        self.search = TavilySearch(tavily_api_key=tavily_api_key)
        self.embeddings = HuggingFaceEmbeddings(model_name=embed_path)

        self.knowledge_file = knowledge_file
        self.vector_store = self.load_knowledge_to_chroma()

    def load_knowledge_to_chroma(self):
        loader = TextLoader(self.knowledge_file, encoding="utf-8")
        docs = loader.load()

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=512,
            chunk_overlap=50,
            separators=["\n\n", "\n", "。", " "]
        )
        chunks = splitter.split_documents(docs)

        vector_store = Chroma.from_documents(
            documents=chunks,
            embedding=self.embeddings,
            persist_directory="./chroma_db"
        )
        return vector_store

    def setup_runnable_pipeline(self):
        parse_prompt = ChatPromptTemplate.from_messages([
            SystemMessage(content="你是旅游助手，需从用户问题中提取地点和查询类型，查询类型包括天气、景点介绍、行程规划"),
            ("user", "问题：{user_question} 请以JSON格式返回：{{\"location\": \"地点\", \"type\": \"查询类型\"}}")
        ])
        parse_module = parse_prompt | self.llm | JsonOutputParser()

        # 天气查询
        weather_query = RunnableLambda(
            lambda x: self.search.invoke(f"{x['location']}的天气怎么样")
        )

        # 景点检索
        attraction_retrieve = (lambda x: x['location']) | self.vector_store.as_retriever() | (
            lambda x: x[0].page_content if x else "暂无相关景点信息"
        )

        # 并行获取
        data_acquisition = RunnableMap({
            "weather": weather_query,
            "attraction": attraction_retrieve,
            "location": lambda x: x['location']
        })

        # 回答生成
        generate_prompt = ChatPromptTemplate.from_messages([
            SystemMessage(content="你是专业旅游顾问，结合景点信息和天气生成行程建议与注意事项"),
            ("user", "地点：{location}\n景点信息：{attraction}\n天气情况：{weather}\n请生成行程建议与注意事项")
        ])
        generate_module = generate_prompt | self.llm | (lambda x: x.content.strip())

        self.travel_qa_pipeline = (
            parse_module
            |
            RunnableBranch(
                (lambda x: '天气' in x['type'], data_acquisition),
                lambda x: {
                    "location": x["location"],
                    "attraction": attraction_retrieve.invoke(x),
                    "weather": "未查询天气"
                }
            )
            |
            generate_module
        )

    def process_user_question(self, user_question):
        input_data = {"user_question": user_question}
        response = self.travel_qa_pipeline.invoke(input_data)
        return response


if __name__ == '__main__':
    OPENAI_API_KEY = os.getenv("DASHSCOPE_API_KEY")
    TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

    embed_path = r'C:\Users\aaa\PycharmProjects\day24\models\BAAI\bge-large-zh-v1___5'
    knowledge_file = "全国景点知识库.md"

    travel_qa = TravelQASystem(OPENAI_API_KEY, TAVILY_API_KEY, embed_path, knowledge_file)
    travel_qa.setup_runnable_pipeline()

    question = ("今天全国的天气哪些好啊，适合去哪些景点玩啊")
    result = travel_qa.process_user_question(question)
    print(result)