import os
base = 'C:/Users/aaa/PycharmProjects/day25/江湖百晓生_vue/'
for f in os.listdir(base):
    if f.endswith('.py'):
        content = open(base + f, encoding='utf-8').read()
        if 'search_knowledge' in content:
            print(f'Found in {f}')
            idx = content.find('search_knowledge')
            snippet = content[idx:idx+400]
            with open('C:/Users/aaa/PycharmProjects/day25/out_search.txt', 'w', encoding='utf-8', errors='replace') as out:
                out.write(snippet)
