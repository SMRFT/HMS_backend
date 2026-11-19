import os, sys, django
from dotenv import load_dotenv
load_dotenv('d:/SMRFT/Projects/HMS/HMS_backend/.env')
sys.path.insert(0, 'd:/SMRFT/Projects/HMS/HMS_backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
django.setup()

from pymongo import MongoClient

client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
db = client['HMS']

known_adv_map = {
    "2627003028": {"ip": "S026/008347", "uhid": "S026/006856", "name": "PALANIAMMAL"},
    "2627003029": {"ip": "S026/008314", "uhid": "S025/008860", "name": "KAVITHA"},
    "2627003030": {"ip": "S026/008328", "uhid": "S026/006632", "name": "CHINNASAMY"},
    "2627003034": {"ip": "S026/008351", "uhid": "S026/006861", "name": "SELVARAJ M"},
    "2627003035": {"ip": "S026/008350", "uhid": "S026/006838", "name": "JAYASHREE V"},
    "2627003036": {"ip": "S026/008350", "uhid": "S026/006838", "name": "JAYASHREE V"},
    "2627003037": {"ip": "S026/008311", "uhid": "S026/001853", "name": "MANIARASU"},
}

for b_no, info in known_adv_map.items():
    adm = db['hospital_admission'].find_one({'ipNumber': info['ip']})
    pat = db['hospital_patient'].find_one({'uhid': info['uhid']})
    p_name = f"{pat.get('firstName', '')} {pat.get('lastName', '')}".strip() if pat else "N/A"
    print(f"Bill {b_no}: IP={info['ip']} (adm_found={adm is not None}), UHID={info['uhid']} Name in DB={p_name}, Target={info['name']}")
