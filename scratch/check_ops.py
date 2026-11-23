import os
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv('D:/Parthi/HMS/HMS_backend/.env')
client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
admin_db = client['admin']

try:
    ops = admin_db.command('currentOp')
    running = [
        o for o in ops.get('inprog', [])
        if o.get('op') in ['query', 'command', 'aggregate'] and not o.get('ns', '').startswith('admin.')
    ]
    print(f'Currently running ops ({len(running)}):')
    for o in running:
        print(f"opid: {o.get('opid')}, secs: {o.get('secs_running')}, ns: {o.get('ns')}, query: {o.get('command')}")
except Exception as e:
    print('currentOp error:', e)
