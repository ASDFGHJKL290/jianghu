import requests
import json

# ====================== 你只需要改这 3 个信息 ======================
API_KEY = "ark-5593f660-9713-4201-aa46-c76a1ee799a0-207a0"
IMAGE_URL = "https://s41.ax1x.com/2026/04/20/pegQYuj.png"  # 本地图传图床得到URL
MODEL_NAME = "doubao-3d-seed-2.0"       # 固定，不用改
# ==================================================================

# 请求地址（豆包官方多模态生成接口）
url = "https://ark.cn-beijing.volces.com/api/v3/3d/generate"

# 请求头
headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

# 请求参数（图生3D）
data = {
    "model": MODEL_NAME,
    "input": {
        "image": IMAGE_URL,     # 输入图片
        "resolution": "1024",   # 3D模型精度
        "texture": True,        # 带材质贴图
        "topology": "clean"     # 干净拓扑（游戏引擎可用）
    },
    "response_format": "url"   # 返回3D模型下载链接
}

# 发送请求
response = requests.post(url, headers=headers, json=data)
result = response.json()

# 输出结果
print("✅ 3D模型生成成功！")
print("📥 下载链接：", result["output"]["model_url"])
print("📦 格式：", result["output"]["format"])  # 一般是 glb