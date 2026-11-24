import os, sys, datetime, pytz, re
from dotenv import load_dotenv
load_dotenv('HMS_backend/.env', override=True)
from pymongo import MongoClient

c = MongoClient(os.getenv('GLOBAL_DB_HOST'))
db = c['HMS']
oppharmacy_collection = db['hospital_pharmacybilling']
patient_collection = db['hospital_patient']
profile_collection = c['Global']['backend_diagnostics_profile']
billtype_collection = db['hospital_billtype']
pharmacy_item_collection = db['hospital_pharmacyitem']

ist = pytz.timezone("Asia/Kolkata")
now_ist = datetime.datetime.now(ist)
today_date_ist = now_ist.date()

today_start_local = datetime.datetime.combine(today_date_ist, datetime.time.min)
today_end_local = datetime.datetime.combine(today_date_ist, datetime.time.max)
today_start_ist = ist.localize(today_start_local)
today_end_ist = ist.localize(today_end_local)
today_start_utc = today_start_ist.astimezone(pytz.utc).replace(tzinfo=None)
today_end_utc = today_end_ist.astimezone(pytz.utc).replace(tzinfo=None)
today_str = today_date_ist.strftime("%Y-%m-%d")

def test_query(params):
    hospital_code = params.get("hospital_code", "SH001")
    branch_code = params.get("branch_code", "SHB001")
    outlet_code = params.get("outlet_code")
    req_status = (params.get("status") or "").strip().lower()
    req_pm = (params.get("payment_mode") or "").strip()
    search_query = (params.get("search") or "").strip()
    date_str = params.get("date")
    from_date_str = params.get("from_date")
    to_date_str = params.get("to_date")

    from_dt, to_dt = None, None
    if from_date_str and to_date_str:
        from_dt = datetime.datetime.strptime(from_date_str.strip()[:10], "%Y-%m-%d")
        to_dt = datetime.datetime.strptime(to_date_str.strip()[:10], "%Y-%m-%d").replace(hour=23, minute=59, second=59, microsecond=999999)
    elif date_str:
        from_dt = datetime.datetime.strptime(date_str.strip()[:10], "%Y-%m-%d")
        to_dt = from_dt.replace(hour=23, minute=59, second=59, microsecond=999999)

    mongo_filter = {"is_deleted": {"$ne": True}}
    if hospital_code: mongo_filter["hospital_code"] = hospital_code
    if branch_code: mongo_filter["branch_code"] = branch_code

    if req_pm and req_pm.lower() not in ["all", ""]:
        pm_regex = {"$regex": f"^{re.escape(req_pm)}$", "$options": "i"}
        mongo_filter["$or"] = [
            {"payment_mode": pm_regex},
            {"payment_details.method": pm_regex},
            {"payment_details.payment_mode": pm_regex},
        ]
    elif req_pm.lower() == "all":
        pass
    else:
        mongo_filter["payment_mode"] = {"$nin": ["Credit", "credit", "CREDIT", "Insurance", "insurance"]}

    if outlet_code and outlet_code.upper() != "ALL":
        mongo_filter["outlet_code"] = outlet_code

    search_conditions = []
    if search_query:
        s_regex = {"$regex": re.escape(search_query), "$options": "i"}
        search_conditions = [
            {"bill_no": s_regex},
            {"uhid": s_regex},
            {"patient_name": s_regex},
            {"inpatient_number": s_regex},
        ]
        if search_query.isdigit():
            search_conditions.append({"Bill_id": int(search_query)})

    def make_date_conditions(field_name, s_dt, e_dt, s_utc, e_utc, date_prefix):
        return [
            {field_name: {"$gte": s_dt, "$lte": e_dt}},
            {field_name: {"$gte": s_utc, "$lte": e_utc}},
            {field_name: {"$regex": f"^{re.escape(date_prefix)}"}},
        ]

    status_and_conditions = []
    if search_conditions:
        # If user explicitly searched, prioritize search match
        status_and_conditions.append({"$or": search_conditions})

    if from_dt and to_dt:
        mongo_filter["billing_status"] = {"$in": ["Billed", "Paid", "Processing", "Pending"]}
        date_ors = []
        for fld in ["paid_date", "paid_datetime", "bill_date", "created_date"]:
            date_ors.append({fld: {"$gte": from_dt, "$lte": to_dt}})
        status_and_conditions.append({"$or": date_ors})
    elif req_status == "pending":
        mongo_filter["billing_status"] = {"$in": ["Billed", "Processing", "Pending"]}
        date_ors = []
        for fld in ["bill_date", "created_date"]:
            date_ors.extend(make_date_conditions(fld, today_start_local, today_end_local, today_start_utc, today_end_utc, today_str))
        status_and_conditions.append({"$or": date_ors})
    elif req_status == "unpaid":
        mongo_filter["billing_status"] = {"$in": ["Billed", "Processing", "Pending"]}
        status_and_conditions.append({"$or": [
            {"bill_date": {"$lt": today_start_local}},
            {"created_date": {"$lt": today_start_local}},
            {"bill_date": {"$lt": today_start_utc}},
            {"created_date": {"$lt": today_start_utc}},
            {"created_date": {"$lt": today_str}},
        ]})
    elif req_status in ["received", "paid"]:
        mongo_filter["billing_status"] = "Paid"
        date_ors = []
        for fld in ["paid_date", "paid_datetime", "bill_date", "created_date"]:
            date_ors.extend(make_date_conditions(fld, today_start_local, today_end_local, today_start_utc, today_end_utc, today_str))
        status_and_conditions.append({"$or": date_ors})
    elif not search_query:
        # Default (when no search query): All unpaid bills + today's paid bills
        today_paid_ors = []
        for fld in ["paid_date", "paid_datetime", "bill_date", "created_date"]:
            today_paid_ors.extend(make_date_conditions(fld, today_start_local, today_end_local, today_start_utc, today_end_utc, today_str))
        status_and_conditions.append({"$or": [
            {"billing_status": {"$in": ["Billed", "Processing", "Pending"]}},
            {"billing_status": "Paid", "$or": today_paid_ors}
        ]})

    if status_and_conditions:
        if "$and" in mongo_filter:
            mongo_filter["$and"].extend(status_and_conditions)
        else:
            mongo_filter["$and"] = status_and_conditions

    count = oppharmacy_collection.count_documents(mongo_filter)
    docs = list(oppharmacy_collection.find(mongo_filter).sort("created_date", -1).limit(5))
    return count, docs

print("1. Default (unpaid + today paid):", test_query({})[0])
print("2. Pending today:", test_query({"status": "pending"})[0])
print("3. Unpaid backlog:", test_query({"status": "unpaid"})[0])
print("4. Received today:", test_query({"status": "received"})[0])
print("5. Date 2026-11-19 count:", test_query({"date": "2026-11-19"})[0])
c_search, docs = test_query({"search": "262702041404"})
print("6. Search '262702041404' count:", c_search)
if docs:
    print("   Found bill:", docs[0].get("bill_no"), "Patient:", docs[0].get("uhid"), "Status:", docs[0].get("billing_status"), "Net:", docs[0].get("net_amount"), "Doctor:", docs[0].get("doctor_name"))
c_uhid, docs_uhid = test_query({"search": "S022/007150"})
print("7. Search UHID 'S022/007150' count:", c_uhid)
if docs_uhid:
    print("   Found bill for UHID:", docs_uhid[0].get("bill_no"), "Net:", docs_uhid[0].get("net_amount"), "Doctor:", docs_uhid[0].get("doctor_name"))
