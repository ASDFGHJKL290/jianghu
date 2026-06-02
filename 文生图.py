import requests
import os
from datetime import datetime

# ========== 填你的API Key ==========
API_KEY = "sk-b98abef1344a46a7aa27d7d20972415c"
prompt = "一只可爱的橘猫在草地上睡觉，自然光，高清细节，写实摄影，8k"
# ==================================

url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text2image/image-synthesis"
headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}
data = {
    "model": "wanxiang-v1",
    "prompt": prompt,
    "size": "1024*1024",
    "n": 1
}

try:
    print("🎨 万相生成中...")
    res = requests.post(url, headers=headers, json=data, timeout=60, verify=True)
    res_json = res.json()
    if res.status_code == 200 and res_json.get("code") == "200":
        img_url = res_json["output"]["images"][0]["url"]
        img_data = requests.get(img_url).content
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        save_path = os.path.join(desktop, f"wanxiang_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
        with open(save_path, "wb") as f:
            f.write(img_data)
        print(f"✅ 保存到桌面：{save_path}")
    else:
        print(f"❌ 错误：{res_json}")
except Exception as e:
    print(f"❌ 网络异常：{str(e)}")