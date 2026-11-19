import os, sys, django
from dotenv import load_dotenv
load_dotenv('d:/SMRFT/Projects/HMS/HMS_backend/.env')
sys.path.insert(0, 'd:/SMRFT/Projects/HMS/HMS_backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
django.setup()

from pymongo import MongoClient
from datetime import datetime, timedelta

client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
db = client['HMS']

# Known advance bills mapping
KNOWN_ADVANCE_MAP = {
    "2627003028": {"ip": "S026/008347", "uhid": "S026/006856", "name": "PALANIAMMAL"},
    "2627003029": {"ip": "S026/008314", "uhid": "S025/008860", "name": "KAVITHA"},
    "2627003030": {"ip": "S026/008328", "uhid": "S026/006632", "name": "CHINNASAMY"},
    "2627003031": {"ip": "S026/008352", "uhid": "S024/009788", "name": "GOVINDAN P"},
    "2627003032": {"ip": "S026/008352", "uhid": "S024/009788", "name": "GOVINDAN P"},
    "2627003033": {"ip": "S026/008355", "uhid": "1718/000035", "name": "MANI E"},
    "2627003034": {"ip": "S026/008351", "uhid": "S026/006861", "name": "SELVARAJ M"},
    "2627003035": {"ip": "S026/008350", "uhid": "S026/006838", "name": "JAYASHREE V"},
    "2627003036": {"ip": "S026/008350", "uhid": "S026/006838", "name": "JAYASHREE V"},
    "2627003037": {"ip": "S026/008311", "uhid": "S026/001853", "name": "MANIARASU"},
}

# Test lookup for all 10 bills
for b, info in KNOWN_ADVANCE_MAP.items():
    print(f"Bill {b}: Name={info['name']}, UHID={info['uhid']}, IP={info['ip']}")
