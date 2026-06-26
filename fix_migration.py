import re
with open('hospital/migrations/0014_auto_20260603_1514.py', 'r') as f:
    content = f.read()

# We only want to remove DeleteModel blocks.
new_content = re.sub(r'\s*migrations\.DeleteModel\(\s*name=\'[^\']+\',\s*\),', '', content)
# And the broken one we left earlier
new_content = re.sub(r'\s*migrations\.DeleteModel\(\s*\),', '', new_content)

with open('hospital/migrations/0014_auto_20260603_1514.py', 'w') as f:
    f.write(new_content)
