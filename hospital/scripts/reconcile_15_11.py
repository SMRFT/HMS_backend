import sys
sys.path.append('d:/SMRFT/Projects/HMS/HMS_backend')
import os
from dotenv import load_dotenv
load_dotenv('d:/SMRFT/Projects/HMS/HMS_backend/.env')

from pymongo import MongoClient
from datetime import datetime, time
import pytz

ist = pytz.timezone('Asia/Kolkata')
db_host = os.getenv("GLOBAL_DB_HOST", "mongodb://localhost:27017")
client = MongoClient(db_host)
db = client['HMS']

col = db.hospital_cashcountershiftdetails

# 15/11/2026 IST range
# 2026-11-15 00:00:00 IST to 23:59:59 IST
start_ist = ist.localize(datetime(2026, 11, 15, 0, 0, 0))
end_ist = ist.localize(datetime(2026, 11, 15, 23, 59, 59, 999999))
start_utc = start_ist.astimezone(pytz.utc).replace(tzinfo=None)
end_utc = end_ist.astimezone(pytz.utc).replace(tzinfo=None)

print(f"Querying shifts between UTC {start_utc} and {end_utc} (or date=2026-11-15)")

shifts = list(col.find({
    '$or': [
        {'date': datetime(2026, 11, 15, 0, 0)},
        {'StartingTime': {'$gte': start_utc, '$lte': end_utc}}
    ]
}).sort('shiftno', 1))

print(f"\nFound {len(shifts)} shifts for 15/11/2026:")
outlets = {}
for s in shifts:
    outlet = s.get('outlet_code')
    outlets.setdefault(outlet, []).append(s)
    st = s.get('StartingTime')
    et = s.get('closingTime')
    st_str = ist.normalize(pytz.utc.localize(st).astimezone(ist)).strftime('%I:%M %p') if st else 'N/A'
    et_str = ist.normalize(pytz.utc.localize(et).astimezone(ist)).strftime('%I:%M %p') if et else 'N/A'
    cash = float(str(s.get('collected_Amount', 0)))
    credit = float(str(s.get('CreditAmount', 0)))
    ret = float(str(s.get('SalesReturnAmount', 0)))
    close = float(str(s.get('ClosingBalance', 0)))
    print(f"Shift: {s.get('shiftno')}, Outlet: {outlet}, Cashier: {s.get('CashierID')}, Times: {st_str} - {et_str} | Cash: {cash:.2f}, Credit: {credit:.2f}, Ret: {ret:.2f}, Closing: {close:.2f}")

print("\n=== TOTALS BY OUTLET ===")
grand_cash = 0
grand_credit = 0
for outlet, s_list in outlets.items():
    tot_cash = sum(float(str(s.get('collected_Amount', 0))) for s in s_list)
    tot_credit = sum(float(str(s.get('CreditAmount', 0))) for s in s_list)
    tot_ret = sum(float(str(s.get('SalesReturnAmount', 0))) for s in s_list)
    grand_cash += tot_cash
    grand_credit += tot_credit
    print(f"Outlet: {outlet} ({len(s_list)} shifts) -> Cash: {tot_cash:.2f}, Credit/Bank: {tot_credit:.2f}, Ret: {tot_ret:.2f}, Total: {(tot_cash + tot_credit):.2f}")

print(f"\nGRAND TOTAL ACROSS ALL OUTLETS -> Cash: {grand_cash:.2f}, Credit/Bank: {grand_credit:.2f}, All: {(grand_cash + grand_credit):.2f}")


