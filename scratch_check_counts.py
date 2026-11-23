import os, django, time
from datetime import datetime, timedelta
os.chdir('D:/SMRFT/Projects/HMS/HMS_backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings-test')
django.setup()
from hospital.Views.MasterAccountsReport.core_ledger_engine import get_db, parse_date

client, db, g_db = get_db()
f_d = parse_date('2026-11-19')
t_d = parse_date('2026-11-20', is_end=True)
f_dt_utc = f_d - timedelta(hours=5, minutes=30)
t_dt_utc = t_d - timedelta(hours=5, minutes=30)

ccc_q = {"created_date": {"$gte": f_dt_utc, "$lte": t_dt_utc}}
ccc_records = list(db["hospital_cashcountercollection"].find(ccc_q, {"bill_no": 1, "Bill_id": 1, "bill_number": 1}))

all_bill_nums = set()
all_bill_ids = set()
for r in ccc_records:
    b_no = str(r.get("bill_no") or r.get("bill_number") or "").strip()
    if b_no:
        all_bill_nums.add(b_no)
        if "/" in b_no:
            all_bill_nums.add(b_no.replace("/", ""))
    bid = r.get("Bill_id")
    if bid is not None and str(bid).strip():
        try: all_bill_ids.add(int(bid))
        except: pass
        all_bill_ids.add(str(bid).strip())

bill_num_list = list(all_bill_nums)
bill_id_list = list(all_bill_ids)

print('Total ccc records:', len(ccc_records))
print('Total bill_num_list:', len(bill_num_list))
print('Total bill_id_list:', len(bill_id_list))
print('Sample bill_nums:', bill_num_list[:5])
print('Sample bill_ids:', bill_id_list[:5])
client.close()
