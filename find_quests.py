import os
base = 'C:/Users/aaa/PycharmProjects/day25/江湖百晓生_vue/'
for f in os.listdir(base):
    if f.endswith('.py'):
        path = base + f
        content = open(path, encoding='utf-8').read()
        if 'check_quests' in content or 'qid' in content:
            print(f'=== {f} ===')
            idx = content.find('check_quests')
            if idx >= 0:
                snippet = content[idx:idx+300]
                with open('C:/Users/aaa/PycharmProjects/day25/check_quests_result.txt', 'w', encoding='utf-8', errors='replace') as out:
                    out.write(snippet)
                print('check_quests found in', f)
