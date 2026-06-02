import re

path = r"C:\Users\aaa\PycharmProjects\day25\江湖百晓生_vue\static\index.html"
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# 把 /static/xxx.png 改回 /static/image/xxx.png (只处理图片)
# 先找到所有 /static/ 开头的图片引用
pattern = r'"/static/([^"]+\.png)"'
replacement = r'"/static/image/\1"'
new_content = re.sub(pattern, replacement, content)

with open(path, 'w', encoding='utf-8') as f:
    f.write(new_content)

# 验证
count = len(re.findall(r'/static/image/[^"]+\.png', new_content))
print(f"✅ 已修复，共 {count} 处图片路径指向 /static/image/")
