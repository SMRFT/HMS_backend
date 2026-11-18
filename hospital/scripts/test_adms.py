import sys
sys.path.append('d:/SMRFT/Projects/HMS/HMS_backend')
import os
from dotenv import load_dotenv
load_dotenv('d:/SMRFT/Projects/HMS/HMS_backend/.env')
from pymongo import MongoClient

client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
db = client['HMS']

for ip in ['S026/008352', 'S026/008355']:
    adm = db.hospital_admission.find_one({'ipNumber': ip})
    if adm:
        print(f"IP: {ip}, UHID: {adm.get('uhid')}, Name: {adm.get('patient_name')}, Advs: {adm.get('advance_payments')}")
    else:
        print(f"IP {ip} not found")

