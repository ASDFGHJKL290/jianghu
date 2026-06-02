import requests
import json

# ===================== 你自己的信息 =====================
API_KEY = "ark-5593f660-9713-4201-aa46-c76a1ee799a0-207a0"
INPUT_IMAGE = "https://s41.ax1x.com/2026/04/20/pegQYuj.png"  # 必须公开可访问
# ======================================================

# ----------------- 【官方真实接口】-----------------
url = "https://ark.cn-beijing.volces.com/api/v3/tasks"

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

# ----------------- 【官方真实模型名 + 参数】-----------------
data = {
    "model": "Doubao-Seed3D-2.0",
    "input": {
        "image": INPUT_IMAGE
    }
}

# 发送
response = requests.post(url, json=data, headers=headers)

print("状态码：", response.status_code)
print("返回内容：", response.text)