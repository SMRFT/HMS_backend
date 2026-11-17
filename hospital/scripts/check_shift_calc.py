import sys
sys.path.append('d:/SMRFT/Projects/HMS/HMS_backend')
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
django.setup()
from pymongo import MongoClient
import os
from datetime import datetime, date

client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
db = client['HMS']

from hospital.Views.cashcounter import calculate_shift_collection

shifts_003 = [
    '2627/01/000006', '2627/01/000007', '2627/01/000008',
    '2627/01/000009', '2627/01/000010', '2627/01/000011', '2627/01/000012'
]

print("=== CALCULATE SHIFT COLLECTION FOR EACH SHIFT ===")
tot_calc_cash = 0
tot_calc_credit = 0
for s in shifts_003:
    res = calculate_shift_collection(s)
    c = res.get('total_collection', 0)
    cr = res.get('total_credit', 0)
    tot_calc_cash += c
    tot_calc_credit += cr
    print(f"Shift {s}: Cash={c:.2f}, Credit={cr:.2f}, Total={(c+cr):.2f}, IPAdvance={res.get('ip_advance', 0)}")

print(f"Total across 7 shifts: Cash={tot_calc_cash:.2f}, Credit={tot_calc_credit:.2f}, Grand Total={(tot_calc_cash+tot_calc_credit):.2f}")

