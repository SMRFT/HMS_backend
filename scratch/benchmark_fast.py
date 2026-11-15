import sys, os, time, re
from datetime import datetime, date
from decimal import Decimal
from bson.decimal128 import Decimal128
from dotenv import load_dotenv
load_dotenv('HMS_backend/.env')
from pymongo import MongoClient

client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
global_db = client["Global"]
profile_collection = global_db["backend_diagnostics_profile"]
hms_db = client["HMS"]
billtype_collection       = hms_db["hospital_billtype"]
pharmacy_item_collection  = hms_db["hospital_pharmacyitem"]
oppharmacy_collection     = hms_db["hospital_pharmacybilling"]
patient_collection        = hms_db["hospital_patient"]
admission_collection      = hms_db["hospital_admission"]
insurance_collection      = hms_db["hospital_insuranceprovider"]

def to_num(val):
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, (Decimal, Decimal128)):
        return float(val)
    try:
        return float(str(val).strip())
    except (ValueError, TypeError):
        return 0.0

def serialize_val(val):
    if isinstance(val, (datetime, date)):
        return val.isoformat()
    if isinstance(val, (Decimal, Decimal128)):
        return float(val)
    if hasattr(val, '__str__') and type(val).__name__ == 'ObjectId':
        return str(val)
    return val

def fast_pharmacy_view_bills(
    hospital_code="SH001",
    branch_code="SHB001",
    matched_outlet="OLET002",
    employee_id="50886",
    from_date_str=None,
    to_date_str=None,
    search_by="",
    search_value="",
    bill_type_param=None,
    limit=1000
):
    t0 = time.time()
    # 1. Bill types
    billtype_cursor = billtype_collection.find(
        {"hospital_code": hospital_code, "branch_code": branch_code},
        {"bill_type": 1, "bill_name": 1, "_id": 0}
    )
    billtype_map = {}
    allowed_bill_types = []
    for bt in billtype_cursor:
        bt_val = bt.get("bill_type")
        if bt_val is not None:
            try:
                bt_int = int(bt_val)
                allowed_bill_types.append(bt_int)
                billtype_map[bt_int] = bt.get("bill_name", "")
            except:
                pass

    # 2. Date parsing
    from_dt = None
    to_dt = None
    if from_date_str:
        try:
            from_dt = datetime.strptime(from_date_str.strip(), "%Y-%m-%d")
        except:
            pass
    if to_date_str:
        try:
            to_dt = datetime.strptime(to_date_str.strip(), "%Y-%m-%d").replace(hour=23, minute=59, second=59)
        except:
            pass

    # 3. Query building
    bill_q = {
        "hospital_code": hospital_code,
        "branch_code": branch_code,
        "billing_status": {"$in": ["Billed", "Paid", "Processing", "deleted"]}
    }
    if isinstance(matched_outlet, (list, tuple)):
        bill_q["outlet_code"] = {"$in": list(matched_outlet)}
    elif matched_outlet:
        bill_q["outlet_code"] = matched_outlet

    if bill_type_param and bill_type_param != "ALL":
        try:
            bill_q["bill_type"] = int(bill_type_param)
        except:
            if allowed_bill_types:
                bill_q["bill_type"] = {"$in": allowed_bill_types}
    elif allowed_bill_types:
        bill_q["bill_type"] = {"$in": allowed_bill_types}

    if from_dt and to_dt:
        bill_q["bill_date"] = {"$gte": from_dt, "$lte": to_dt}
    elif from_dt:
        bill_q["bill_date"] = {"$gte": from_dt}
    elif to_dt:
        bill_q["bill_date"] = {"$lte": to_dt}

    if search_value:
        sv = re.escape(search_value)
        if search_by == "bill_no":
            bill_q["bill_no"] = {"$regex": sv, "$options": "i"}
        elif search_by == "uhid":
            bill_q["uhid"] = {"$regex": sv, "$options": "i"}
        elif search_by == "patient_name":
            p_uhids = [
                p["uhid"] for p in patient_collection.find(
                    {"$or": [
                        {"firstName": {"$regex": sv, "$options": "i"}},
                        {"lastName": {"$regex": sv, "$options": "i"}}
                    ]},
                    {"uhid": 1, "_id": 0}
                ).limit(300)
            ]
            if p_uhids:
                bill_q["$or"] = [
                    {"patientname": {"$regex": sv, "$options": "i"}},
                    {"uhid": {"$in": p_uhids}}
                ]
            else:
                bill_q["patientname"] = {"$regex": sv, "$options": "i"}
        else:
            bill_q["bill_no"] = {"$regex": sv, "$options": "i"}

    # 4. Fetch Bills in 1 Fast PyMongo call
    bills = list(oppharmacy_collection.find(bill_q).sort("bill_date", -1).limit(limit))
    t_fetch = time.time()

    # 5. Collect all IDs for bulk joins
    uhids = set()
    doctor_ids = set()
    emp_ids = set()
    item_ids = set()

    for b in bills:
        u = b.get("uhid")
        if u: uhids.add(str(u).strip())
        doc_id = b.get("doctor_id")
        if doc_id: doctor_ids.add(str(doc_id).strip())
        for f in ["billed_id", "created_by", "cashier_id"]:
            val = b.get(f)
            if val: emp_ids.add(str(val).strip())
        for it in (b.get("medicine_particulars") or []):
            if isinstance(it, dict) and it.get("item_id"):
                item_ids.add(it["item_id"])

    # 6. Bulk Patient Map & Insurance Codes
    patient_map = {}
    patient_ins_map = {}
    all_comp_codes = set()
    if uhids:
        for p in patient_collection.find(
            {"uhid": {"$in": list(uhids)}},
            {"uhid": 1, "salutation": 1, "firstName": 1, "lastName": 1, "company_code": 1, "customer_type": 1, "_id": 0}
        ):
            sal = (p.get("salutation") or "").strip()
            fn  = (p.get("firstName") or "").strip()
            ln  = (p.get("lastName") or "").strip()
            if ln.lower() == fn.lower(): ln = ""
            full_n = " ".join(f"{sal} {fn} {ln}".split())
            patient_map[p["uhid"]] = full_n
            cc = (p.get("company_code") or "").strip()
            if cc:
                patient_ins_map[p["uhid"]] = cc
                all_comp_codes.add(cc)
            elif str(p.get("customer_type") or "").upper() == "INSURANCE":
                patient_ins_map[p["uhid"]] = "INSURANCE"

    # 7. Bulk Admission Map
    admission_map = {}
    if uhids:
        for adm in admission_collection.find(
            {"uhid": {"$in": list(uhids)}},
            {"uhid": 1, "is_admitted": 1, "customer_type": 1, "company_code": 1, "insurance_company": 1, "room_details": 1, "ipNumber": 1, "inpatient_number": 1, "created_date": 1, "_id": 0}
        ).sort("created_date", -1):
            u = adm.get("uhid")
            if u not in admission_map or adm.get("is_admitted"):
                admission_map[u] = adm
            cc = (adm.get("company_code") or "").strip()
            if cc:
                all_comp_codes.add(cc)

    # 8. Bulk Insurance Providers
    insurance_name_map = {}
    if all_comp_codes:
        for ins in insurance_collection.find(
            {"company_code": {"$in": list(all_comp_codes)}},
            {"company_code": 1, "company_name": 1, "_id": 0}
        ):
            cc = str(ins.get("company_code") or "").strip()
            nm = (ins.get("company_name") or "").strip()
            if cc and nm:
                insurance_name_map[cc] = nm
                insurance_name_map[cc.upper()] = nm
                insurance_name_map[cc.lower()] = nm

    # 9. Bulk Employees & Doctors
    all_pids = list(doctor_ids | emp_ids)
    profile_map = {}
    if all_pids:
        search_pids = []
        for pid in all_pids:
            search_pids.append(pid)
            if pid.isdigit():
                search_pids.append(int(pid))
        for prof in profile_collection.find(
            {"employeeId": {"$in": search_pids}},
            {"employeeId": 1, "employeeName": 1, "_id": 0}
        ):
            eid_str = str(prof.get("employeeId"))
            ename = prof.get("employeeName", "")
            if ename:
                profile_map[eid_str] = ename
                try:
                    profile_map[str(int(eid_str))] = ename
                except:
                    pass

    # 10. Bulk Items
    item_map = {}
    if item_ids:
        search_iids = []
        for iid in item_ids:
            search_iids.append(iid)
            if str(iid).isdigit():
                search_iids.append(int(iid))
                search_iids.append(str(iid))
        for itm in pharmacy_item_collection.find(
            {"item_id": {"$in": search_iids}},
            {"item_id": 1, "item_name": 1, "is_consumable_items": 1, "hsn": 1, "hsn_code": 1, "CGST_Percentage": 1, "SGST_Percentage": 1, "mrp": 1, "Selling_Price": 1, "_id": 0}
        ):
            raw_id = itm.get("item_id")
            item_map[raw_id] = itm
            item_map[str(raw_id)] = itm
            try:
                item_map[int(raw_id)] = itm
            except:
                pass

    t_joins = time.time()

    # 11. Direct Dictionary Serialization
    data = []
    for b in bills:
        # Clone doc & convert MongoDB specific types
        s = {}
        for k, v in b.items():
            if k == "_id":
                s["_id"] = str(v)
            else:
                s[k] = serialize_val(v)

        u = b.get("uhid") or ""
        p_name = patient_map.get(u) or b.get("patientname") or ""
        s["patient_name"] = p_name
        s["patientname"]  = p_name

        # Doctor
        doc_id_val = str(b.get("doctor_id") or "").strip()
        s["doctor_name"] = profile_map.get(doc_id_val, "")

        # Bill type name
        bt_val = b.get("bill_type")
        s["bill_type_name"] = billtype_map.get(int(bt_val) if bt_val is not None else 0, "")

        # Billed / Employee name
        billed_id_val = str(b.get("billed_id") or "").strip()
        created_val   = str(b.get("created_by") or "").strip()
        cashier_val   = str(b.get("cashier_id") or "").strip()

        billed_display = profile_map.get(billed_id_val) or profile_map.get(cashier_val) or profile_map.get(created_val) or billed_id_val or created_val
        s["billed_name"]     = billed_display
        s["employee_name"]   = billed_display
        s["prepared_by"]     = billed_display
        s["created_by_name"] = profile_map.get(created_val, created_val)

        # Admission & Insurance
        adm_doc = admission_map.get(u) or {}
        adm_ins = adm_doc.get("insurance_company")
        if not adm_ins and adm_doc.get("company_code"):
            adm_ins = insurance_name_map.get(str(adm_doc.get("company_code")).strip(), "")
        if not adm_ins and str(adm_doc.get("customer_type") or "").upper() == "INSURANCE":
            adm_ins = "INSURANCE"

        pat_ins = ""
        pat_cc = patient_ins_map.get(u)
        if pat_cc:
            pat_ins = insurance_name_map.get(pat_cc, pat_cc if pat_cc == "INSURANCE" else "")

        final_ins = adm_ins or pat_ins or ""
        s["insurance_name"]    = final_ins
        s["insurance_company"] = final_ins

        if not s.get("inpatient_number") and (adm_doc.get("ipNumber") or adm_doc.get("inpatient_number")):
            s["inpatient_number"] = adm_doc.get("ipNumber") or adm_doc.get("inpatient_number")

        if not s.get("room_no") and adm_doc.get("room_details"):
            rooms = adm_doc.get("room_details") or []
            active_r = next((r for r in rooms if r.get("is_roomActive")), rooms[0] if rooms else None)
            if active_r:
                s["room_no"] = " | ".join(filter(None, [active_r.get("ward"), active_r.get("room_no") or active_r.get("room")]))

        # Line items
        updated_items = []
        for item in (b.get("medicine_particulars") or []):
            if not isinstance(item, dict): continue
            it = dict(item)
            item_id_val = it.get("item_id")
            master_item = item_map.get(item_id_val, {})

            raw_name = (it.get("item_name") or it.get("medicine_name") or it.get("name") or "").strip()
            if not raw_name:
                raw_name = (master_item.get("item_name") or "").strip()
            it["item_name"]     = raw_name
            it["medicine_name"] = raw_name

            if not it.get("hsn_code"):
                it["hsn_code"] = master_item.get("hsn_code") or master_item.get("hsn") or ""

            cgst_pct = to_num(it.get("CGST_Percentage", 0))
            sgst_pct = to_num(it.get("SGST_Percentage", 0))
            if cgst_pct == 0.0 and master_item.get("CGST_Percentage"):
                cgst_pct = to_num(master_item.get("CGST_Percentage"))
            if sgst_pct == 0.0 and master_item.get("SGST_Percentage"):
                sgst_pct = to_num(master_item.get("SGST_Percentage"))
            it["CGST_Percentage"] = cgst_pct
            it["SGST_Percentage"] = sgst_pct

            price_val = to_num(it.get("price", 0))
            if price_val == 0.0:
                price_val = to_num(it.get("mrp", 0)) or to_num(master_item.get("Selling_Price", 0)) or to_num(master_item.get("mrp", 0))

            qty_val  = to_num(it.get("qty", 0) or it.get("quantity", 0))
            calc_val = to_num(it.get("calculated_price", 0))
            if calc_val == 0.0 and price_val > 0 and qty_val > 0:
                calc_val = round(price_val * qty_val, 2)

            cgst_amt_val = to_num(it.get("CGST_Amt", 0))
            sgst_amt_val = to_num(it.get("SGST_Amt", 0))

            total_gst_pct = cgst_pct + sgst_pct
            product_val = round(calc_val / (1.0 + total_gst_pct / 100.0), 4) if total_gst_pct > 0 else calc_val
            disc_val = to_num(it.get("discount_value", it.get("discount_percent", it.get("discount", 0))))
            disc_amt = to_num(it.get("discount_amount", 0))
            if disc_amt == 0.0 and disc_val > 0:
                disc_amt = round(product_val * (disc_val / 100.0), 4)
            taxable_val = max(0.0, product_val - disc_amt)

            if cgst_amt_val == 0.0 and cgst_pct > 0 and taxable_val > 0:
                cgst_amt_val = round((taxable_val * cgst_pct) / 100.0, 2)
            if sgst_amt_val == 0.0 and sgst_pct > 0 and taxable_val > 0:
                sgst_amt_val = round((taxable_val * sgst_pct) / 100.0, 2)

            it["product_value"]    = product_val
            it["taxable_value"]    = taxable_val
            it["discount_amount"]  = disc_amt
            it["CGST_Amt"]         = cgst_amt_val
            it["SGST_Amt"]         = sgst_amt_val
            it["price"]            = price_val
            it["mrp"]              = to_num(it.get("mrp", 0)) or to_num(master_item.get("mrp", 0)) or price_val
            it["calculated_price"] = calc_val
            it["edit_history"]     = it.get("edit_history", [])
            updated_items.append(it)

        # Recalculate bill total if 0
        items_total = sum(to_num(it.get("calculated_price", 0)) for it in updated_items)
        if to_num(s.get("total_amount", 0)) == 0.0 and items_total > 0:
            s["total_amount"] = round(items_total, 2)
        if to_num(s.get("net_amount", 0)) == 0.0 and items_total > 0:
            s["net_amount"] = round(items_total, 2)

        s["medicine_particulars"] = updated_items
        data.append(s)

    t_end = time.time()
    print(f"Timing breakdown:")
    print(f"  - PyMongo Bill Query: {t_fetch - t0:.3f}s (Fetched {len(bills)} bills)")
    print(f"  - Bulk Joins (Patients, Adm, Ins, Emps, Items): {t_joins - t_fetch:.3f}s")
    print(f"  - In-memory serialization: {t_end - t_joins:.3f}s")
    print(f"  - Total Elapsed: {t_end - t0:.3f}s")
    return data

if __name__ == "__main__":
    res = fast_pharmacy_view_bills()
    print(f"Returned {len(res)} formatted bills. First bill keys: {list(res[0].keys()) if res else []}")
    if res:
        print("Sample bill_no:", res[0].get("bill_no"), "patient:", res[0].get("patient_name"), "doctor:", res[0].get("doctor_name"), "net:", res[0].get("net_amount"))

