from pymongo import MongoClient
import os

# Create Mongo client (single place)
mongo_url = os.getenv("GLOBAL_DB_HOST")
client = MongoClient(mongo_url)

# Databases

global_db = client["Global"]
hms_db = client["HMS"]
Diagnostics_db=client["Diagnostics"]
ER_db = client["ER_Billing"]

# Collections

profile_collection                = global_db["backend_diagnostics_profile"]
department_collection             = global_db["backend_diagnostics_Departments"]
user_collection                   = global_db["backend_diagnostics_user"]
company_secretary_collection      = hms_db["hospital_licencemasterdetails"]  
MHC_Package                       = hms_db["hospital_MHC_Package"] 
MHC_Source                        = hms_db["hospital_MHC_Source"]
HMS_Symptoms_list                 = hms_db["hospital_Symptoms_list"]
medicine_package                  = hms_db["hospital_pharmacyitem"]
shanmuga360_collection            = hms_db["hospital_Shanmuga360_MedicineList"]
Diagnostics_test_details          = Diagnostics_db["core_testdetails"]
doctor_list                       = ER_db["doctors_list"]
hms_billtype                      = hms_db["hospital_billtype"]
hospital_investigationprice       = hms_db["hospital_investigationprice"]
pharmacy_item_collection          = hms_db["hospital_pharmacyitem"]
pharmacy_stock_collection         = hms_db["hospital_pharmacystock"]
pharmacy_billing_collection       = hms_db["hospital_pharmacybilling"]
admission_collection              = hms_db["hospital_admission"]
patient_collection                = hms_db["hospital_patient"]
hospital_insuranceprovider        = hms_db["hospital_insuranceprovider"]
insurance_provider_collection     = hms_db["hospital_insuranceprovider"]

import re

doctor_role_code = "SD-R-DOC"
sample_collector = "SD-R-SMC"

def clean_patient_name(name):
    """
    Cleans and deduplicates patient name.
    Handles duplicate tokens (e.g. 'RANI RANI' -> 'RANI', 'B B JOHN B B JOHN' -> 'B B JOHN').
    """
    if not name or name == "—":
        return ""
    words = str(name).strip().split()
    if not words:
        return ""
    if len(words) >= 2 and len(words) % 2 == 0:
        half = len(words) // 2
        if [w.lower() for w in words[:half]] == [w.lower() for w in words[half:]]:
            words = words[:half]
    clean_words = []
    for idx, w in enumerate(words):
        if idx > 0 and len(w) > 1 and w.lower() == words[idx - 1].lower():
            continue
        clean_words.append(w)
    return " ".join(clean_words).strip()


def get_patient_details_by_uhid(uhid=None, ip_number=None):
    """
    Looks up patient details from hospital_patient, falling back to hospital_admission.
    Returns dict: {'patient_name': ..., 'uhid': ..., 'inpatient_number': ..., 'age': ..., 'gender': ...}
    """
    res = {
        "patient_name": "",
        "uhid": str(uhid).strip() if uhid else "",
        "inpatient_number": str(ip_number).strip() if ip_number else "",
        "age": "",
        "gender": "",
        "mobilePhone": "",
    }
    if not uhid and not ip_number:
        return res

    pat = None
    if uhid:
        u_str = str(uhid).strip()
        pat = patient_collection.find_one({"uhid": u_str})
        if not pat:
            pat = patient_collection.find_one({"uhid": {"$regex": f"^{re.escape(u_str)}$", "$options": "i"}})

    if not pat and ip_number:
        ip_str = str(ip_number).strip()
        adm = admission_collection.find_one({"$or": [{"inpatient_number": ip_str}, {"ip_number": ip_str}]})
        if adm:
            if adm.get("uhid") and not res["uhid"]:
                res["uhid"] = str(adm.get("uhid")).strip()
            if adm.get("inpatient_number"):
                res["inpatient_number"] = str(adm.get("inpatient_number")).strip()
            p_det = adm.get("patient_details") or {}
            if isinstance(p_det, dict) and (p_det.get("firstName") or p_det.get("patient_name")):
                fn = (p_det.get("firstName") or "").strip()
                ln = (p_det.get("lastName") or "").strip()
                sal = (p_det.get("salutation") or "").strip()
                raw_name = f"{sal} {fn} {ln}".strip() or p_det.get("patient_name") or ""
                res["patient_name"] = clean_patient_name(raw_name)
                res["age"] = p_det.get("age") or ""
                res["gender"] = p_det.get("gender") or ""
                return res
            if adm.get("patient_name"):
                res["patient_name"] = clean_patient_name(adm.get("patient_name"))
                return res

    if pat:
        if pat.get("uhid"):
            res["uhid"] = str(pat.get("uhid")).strip()
        sal = (pat.get("salutation") or "").strip()
        fn = (pat.get("firstName") or "").strip()
        ln = (pat.get("lastName") or "").strip()
        if fn and ln:
            if (
                fn.lower() == ln.lower()
                or fn.lower().endswith(ln.lower())
                or fn.lower().replace(" ", "") == ln.lower().replace(" ", "")
            ):
                ln = ""
            elif ln.lower().startswith(fn.lower()):
                fn = ""
        full_name = f"{sal} {fn} {ln}".strip()
        if not full_name:
            full_name = (pat.get("patient_name") or pat.get("name") or "").strip()
        res["patient_name"] = clean_patient_name(full_name)
        res["age"] = pat.get("age") or ""
        res["gender"] = pat.get("gender") or ""
        res["mobilePhone"] = pat.get("mobilePhone") or ""
        return res

    return res


def get_patient_name_by_uhid(uhid=None, ip_number=None):
    """
    Convenience function returning just the formatted patient name string.
    """
    details = get_patient_details_by_uhid(uhid, ip_number)
    return details.get("patient_name") or ""


def get_insurance_provider_by_patient(uhid=None, company_code=None, patient_obj=None):
    """
    Common reusable function:
    Finds and returns insurance provider details (company_name, company_code)
    using the Patient model / hospital_insuranceprovider collection.

    Can be called with:
      - uhid: Looks up Patient model for company_code and customer_type
      - company_code: Directly looks up hospital_insuranceprovider
      - patient_obj: A Patient model instance or dict with company_code / customer_type

    Returns dict:
      {
        "is_insurance": bool,
        "company_code": str,
        "company_name": str,
      }
    """
    res = {
        "is_insurance": False,
        "company_code": "",
        "company_name": "",
    }

    c_code = str(company_code).strip() if company_code else ""
    cust_type = ""

    # 1. If patient_obj passed
    if patient_obj:
        if isinstance(patient_obj, dict):
            c_code = c_code or str(patient_obj.get("company_code") or "").strip()
            cust_type = str(patient_obj.get("customer_type") or "").strip()
        else:
            c_code = c_code or str(getattr(patient_obj, "company_code", "") or "").strip()
            cust_type = str(getattr(patient_obj, "customer_type", "") or "").strip()

    # 2. If uhid passed and we need to check Patient model
    if uhid and (not c_code or not cust_type):
        u_str = str(uhid).strip()
        try:
            from ..models import Patient
            p = Patient.objects.filter(uhid=u_str).first()
            if p:
                cust_type = cust_type or str(p.customer_type or "").strip()
                c_code = c_code or str(p.company_code or "").strip()
        except Exception:
            pass

        if not c_code or not cust_type:
            # Fallback to patient_collection in mongo
            p_doc = patient_collection.find_one({"uhid": u_str})
            if not p_doc:
                p_doc = patient_collection.find_one({"uhid": {"$regex": f"^{re.escape(u_str)}$", "$options": "i"}})
            if p_doc:
                cust_type = cust_type or str(p_doc.get("customer_type") or "").strip()
                c_code = c_code or str(p_doc.get("company_code") or "").strip()

    is_ins = cust_type.lower() == "insurance" or bool(c_code)
    res["is_insurance"] = is_ins
    res["company_code"] = c_code

    # 3. Lookup company_name from hospital_insuranceprovider
    if c_code:
        ins_doc = hospital_insuranceprovider.find_one({
            "company_code": {"$regex": f"^{re.escape(c_code)}$", "$options": "i"}
        })
        if not ins_doc:
            ins_doc = hospital_insuranceprovider.find_one({"company_code": c_code})

        if ins_doc:
            res["company_name"] = str(ins_doc.get("company_name") or "").strip()

    return res


def get_insurance_company_name(uhid=None, company_code=None, patient_obj=None):
    """
    Common helper returning just the insurance company_name string.
    Whenever needed across any view, call get_insurance_company_name(uhid=...) or get_insurance_company_name(company_code=...).
    """
    details = get_insurance_provider_by_patient(uhid=uhid, company_code=company_code, patient_obj=patient_obj)
    return details.get("company_name") or ""


def get_employee_name_by_id(employee_id):
    if not employee_id:
        return "Unknown"
    emp_str = str(employee_id).strip()
    emp = profile_collection.find_one({"employeeId": emp_str})
    if not emp and emp_str.isdigit():
        num_val = int(emp_str)
        emp = profile_collection.find_one({
            "$or": [
                {"employeeId": num_val},
                {"employeeId": str(num_val)},
                {"employeeId": f"{num_val:04d}"},
                {"employeeId": f"{num_val:05d}"},
                {"employeeId": f"{num_val:06d}"}
            ]
        })
    if emp and "employeeName" in emp:
        return emp["employeeName"]
    return "Unknown"


def _clean_doctor_name_tokens(name):
    if not name:
        return []
    s = re.sub(r'(?i)\b(dr|doctor|prof|mr|mrs|ms|mbbs|md|orth|ortho|dnb|cardio|mrcs|eng|phd|mdrd)\b', ' ', str(name))
    s = re.sub(r'[^a-zA-Z0-9\s]', ' ', s)
    return [t.lower() for t in s.split() if len(t) > 2]


def resolve_doctor_id(doctor_input):
    """
    Ensures doctor_id stored in hospital_pharmacybilling is ALWAYS an ID, never a name.
    If doctor_input is an employeeId or numeric ID, returns it.
    If doctor_input is a name string, compares against backend_diagnostics_profile
    (profile_collection) to find the doctor's employeeId.
    """
    if not doctor_input:
        return ""
    val_str = str(doctor_input).strip()
    if not val_str:
        return ""

    # 1. Direct match on employeeId in profile_collection
    emp = profile_collection.find_one({"employeeId": val_str})
    if emp and "employeeId" in emp:
        return str(emp["employeeId"]).strip()

    # 2. Check if numeric ID (handles int, padded strings)
    if val_str.isdigit():
        num_val = int(val_str)
        emp = profile_collection.find_one({
            "$or": [
                {"employeeId": num_val},
                {"employeeId": str(num_val)},
                {"employeeId": f"{num_val:04d}"},
                {"employeeId": f"{num_val:05d}"},
                {"employeeId": f"{num_val:06d}"}
            ]
        })
        if emp and "employeeId" in emp:
            return str(emp["employeeId"]).strip()
        return val_str

    # 3. If input is a doctor name string, compare against profile_collection
    emp = profile_collection.find_one({
        "employeeName": {"$regex": f"^{re.escape(val_str)}$", "$options": "i"}
    })
    if emp and "employeeId" in emp:
        return str(emp["employeeId"]).strip()

    tokens = _clean_doctor_name_tokens(val_str)
    if not tokens:
        return ""

    # Query doctors in profile_collection
    query = {
        "$or": [
            {"designation": "DESIG094"},
            {"primaryRole": doctor_role_code},
            {"additionalRoles": doctor_role_code},
            {"employeeName": {"$regex": r"^\s*Dr", "$options": "i"}}
        ]
    }
    candidate_docs = list(profile_collection.find(query, {"employeeId": 1, "employeeName": 1, "designation": 1, "_id": 0}))
    if not candidate_docs:
        candidate_docs = list(profile_collection.find({}, {"employeeId": 1, "employeeName": 1, "designation": 1, "_id": 0}))

    best_match = None
    best_score = 0
    for p in candidate_docs:
        p_name = p.get("employeeName") or ""
        p_tokens = _clean_doctor_name_tokens(p_name)
        score = 0
        for t in tokens:
            for pt in p_tokens:
                if t == pt:
                    score += 3
                elif t in pt or pt in t:
                    score += 1
        if p.get("designation") in ["DESIG094", "DESIG083"] or str(p_name).strip().lower().startswith("dr"):
            score += 1

        if score > best_score:
            best_score = score
            best_match = p

    if best_match and best_score >= 3:
        return str(best_match.get("employeeId")).strip()

    return ""


def get_doctor_name_by_id(doctor_id):
    """
    Compares doctor_id to backend_diagnostics_profile (profile_collection) to get the doctor's name.
    If doctor_id is a valid employeeId, returns the formatted doctor's name from profile.
    If doctor_id is a name from legacy data, resolves it to profile name or clean doctor name.
    """
    if not doctor_id:
        return ""
    doc_str = str(doctor_id).strip()
    if not doc_str:
        return ""

    # 1. Lookup in profile_collection by ID
    name = get_employee_name_by_id(doc_str)
    if name and name != "Unknown":
        if not name.lower().startswith("dr"):
            return f"Dr. {name}"
        return name

    # 2. If doc_str is not an ID but a name, resolve doctor ID and compare to profile
    resolved_id = resolve_doctor_id(doc_str)
    if resolved_id and resolved_id != doc_str:
        resolved_name = get_employee_name_by_id(resolved_id)
        if resolved_name and resolved_name != "Unknown":
            if not resolved_name.lower().startswith("dr"):
                return f"Dr. {resolved_name}"
            return resolved_name

    # 3. Fallback clean format
    if doc_str.lower().startswith("dr"):
        return doc_str
    if doc_str.isdigit():
        return f"Dr. ({doc_str})"
    return f"Dr. {doc_str}"



from bson.decimal128 import Decimal128

def _safe_float(val):
    if isinstance(val, Decimal128):
        return float(val.to_decimal())
    if val is None:
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def get_pharmacy_items_with_stock(hospital_code, branch_code, outlet_code, item_ids):
    """
    Common optimized function to match item IDs into hospital_pharmacyitem and hospital_pharmacystock.
    Supports both master item_id AND stock_id/id from hospital_pharmacystock.
    """
    if not item_ids:
        return {"items": {}, "stock_by_item": {}, "stock_by_batch": {}}

    query_ids = []
    for x in item_ids:
        query_ids.append(x)
        try:
            query_ids.append(int(x))
        except (ValueError, TypeError):
            pass
        try:
            query_ids.append(str(x))
        except (ValueError, TypeError):
            pass
    query_ids = list(set(query_ids))

    items_map = {}

    # 1. Fetch from hospital_pharmacyitem
    item_filter = {"item_id": {"$in": query_ids}}
    if hospital_code and branch_code:
        item_filter["hospital_code"] = hospital_code
        item_filter["branch_code"] = branch_code

    for itm in pharmacy_item_collection.find(
        item_filter,
        {"item_id": 1, "item_name": 1, "is_consumable_items": 1, "_id": 0}
    ):
        raw_id = itm.get("item_id")
        entry = {
            "item_name": itm.get("item_name") or "",
            "is_consumable_items": bool(itm.get("is_consumable_items", False)),
            "item_id": raw_id
        }
        items_map[raw_id] = entry
        items_map[str(raw_id).strip()] = entry
        try:
            items_map[int(raw_id)] = entry
        except (ValueError, TypeError):
            pass

    # 1b. Fallback across all branches if any query_ids missing
    missing_ids = [qid for qid in query_ids if qid not in items_map]
    if missing_ids and hospital_code and branch_code:
        for itm in pharmacy_item_collection.find(
            {"item_id": {"$in": missing_ids}},
            {"item_id": 1, "item_name": 1, "is_consumable_items": 1, "_id": 0}
        ):
            raw_id = itm.get("item_id")
            entry = {
                "item_name": itm.get("item_name") or "",
                "is_consumable_items": bool(itm.get("is_consumable_items", False)),
                "item_id": raw_id
            }
            items_map[raw_id] = entry
            items_map[str(raw_id).strip()] = entry
            try:
                items_map[int(raw_id)] = entry
            except (ValueError, TypeError):
                pass

    # 1c. Check if any missing IDs are actually stock_id or id in hospital_pharmacystock
    still_missing_ids = [qid for qid in query_ids if qid not in items_map]
    stock_id_to_item_id = {}
    stock_doc_names = {}
    if still_missing_ids:
        for stk in pharmacy_stock_collection.find(
            {
                "$or": [
                    {"stock_id": {"$in": still_missing_ids}},
                    {"id": {"$in": still_missing_ids}}
                ]
            },
            {"stock_id": 1, "id": 1, "item_id": 1, "item_name": 1, "_id": 0}
        ):
            sid = stk.get("stock_id") or stk.get("id")
            iid = stk.get("item_id")
            s_name = stk.get("item_name")
            if sid is not None:
                keys = [sid, str(sid).strip()]
                try:
                    keys.append(int(sid))
                except (ValueError, TypeError):
                    pass
                for k in keys:
                    if iid is not None:
                        stock_id_to_item_id[k] = iid
                    if s_name:
                        stock_doc_names[k] = s_name

        resolved_item_ids = list(set(stock_id_to_item_id.values()))
        if resolved_item_ids:
            # Query pharmacy_item_collection for master item info
            for itm in pharmacy_item_collection.find(
                {"item_id": {"$in": resolved_item_ids}},
                {"item_id": 1, "item_name": 1, "is_consumable_items": 1, "_id": 0}
            ):
                raw_id = itm.get("item_id")
                entry = {
                    "item_name": itm.get("item_name") or "",
                    "is_consumable_items": bool(itm.get("is_consumable_items", False)),
                    "item_id": raw_id
                }
                items_map[raw_id] = entry
                items_map[str(raw_id).strip()] = entry
                try:
                    items_map[int(raw_id)] = entry
                except (ValueError, TypeError):
                    pass

                # Also map every stock_id that points to this item_id
                for sid, mapped_iid in stock_id_to_item_id.items():
                    if str(mapped_iid) == str(raw_id):
                        items_map[sid] = entry

        # Fallback: if any stock_id still not in items_map, use stock_doc_names
        for sid, s_name in stock_doc_names.items():
            if sid not in items_map and s_name:
                items_map[sid] = {
                    "item_name": s_name,
                    "is_consumable_items": False,
                    "item_id": stock_id_to_item_id.get(sid, sid)
                }

    # 2. Fetch from hospital_pharmacystock
    stock_by_item = {}
    stock_by_batch = {}

    all_stock_item_ids = list(set(query_ids + list(stock_id_to_item_id.values())))
    stock_query = {
        "$or": [
            {"item_id": {"$in": all_stock_item_ids}},
            {"stock_id": {"$in": query_ids}},
            {"id": {"$in": query_ids}}
        ]
    }
    if hospital_code and branch_code:
        stock_query["hospital_code"] = hospital_code
        stock_query["branch_code"] = branch_code
    if outlet_code:
        stock_query["outlet_code"] = outlet_code

    stock_fields = {
        "stock_id": 1,
        "id": 1,
        "item_id": 1,
        "item_name": 1,
        "batch_number": 1,
        "mrp": 1,
        "Selling_Price": 1,
        "total_stock": 1,
        "sold_quantity": 1,
        "transferred_out_quantity": 1,
        "grn_return_quantity": 1,
        "CGST_Percentage": 1,
        "SGST_Percentage": 1,
        "CGST_Amt": 1,
        "SGST_Amt": 1,
        "outlet_code": 1,
        "_id": 0
    }

    stock_cursor = list(pharmacy_stock_collection.find(stock_query, stock_fields).sort("stock_id", -1))

    # If no stock found with outlet_code filter, fallback to any outlet for pricing/metadata
    if not stock_cursor and outlet_code:
        fallback_query = dict(stock_query)
        fallback_query.pop("outlet_code", None)
        stock_cursor = list(pharmacy_stock_collection.find(fallback_query, stock_fields).sort("stock_id", -1))

    for stk in stock_cursor:
        raw_id = stk.get("item_id")
        stock_id = stk.get("stock_id")
        alt_id = stk.get("id")

        keys = set()
        for raw_val in [raw_id, stock_id, alt_id]:
            if raw_val is not None:
                keys.add(raw_val)
                keys.add(str(raw_val).strip())
                try:
                    keys.add(int(raw_val))
                except (ValueError, TypeError):
                    pass

        # Also add any query_id that mapped to this item_id
        for sid, mapped_iid in stock_id_to_item_id.items():
            if str(mapped_iid) == str(raw_id):
                keys.add(sid)
                keys.add(str(sid).strip())
                try:
                    keys.add(int(sid))
                except (ValueError, TypeError):
                    pass

        for k in keys:
            stock_by_item.setdefault(k, []).append(stk)

        bn = stk.get("batch_number")
        if bn:
            bn_str = str(bn).strip()
            for k in keys:
                stock_by_batch.setdefault((k, bn_str), []).append(stk)

        # Make sure items_map also has item_name if available from stock
        s_name = stk.get("item_name")
        if s_name:
            for k in keys:
                if k not in items_map or not items_map[k].get("item_name"):
                    items_map[k] = {
                        "item_name": s_name,
                        "is_consumable_items": False,
                        "item_id": raw_id or k
                    }

    return {
        "items": items_map,
        "stock_by_item": stock_by_item,
        "stock_by_batch": stock_by_batch
    }


def resolve_medicine_stock_details(item_dict, items_stock_data):
    """
    Given a raw medicine item dict and the precomputed items_stock_data
    from get_pharmacy_items_with_stock, returns matched item metadata and stock info.
    """
    item_id = item_dict.get("item_id")
    try:
        item_id_int = int(item_id) if item_id is not None else None
    except (ValueError, TypeError):
        item_id_int = None

    req_batch = item_dict.get("batch_number")

    items_map = items_stock_data.get("items", {})
    stock_by_item = items_stock_data.get("stock_by_item", {})
    stock_by_batch = items_stock_data.get("stock_by_batch", {})

    item_meta = (
        items_map.get(item_id)
        or (items_map.get(item_id_int) if item_id_int is not None else None)
        or (items_map.get(str(item_id).strip()) if item_id is not None else None)
        or {}
    )

    item_name = item_meta.get("item_name") or item_dict.get("item_name") or item_dict.get("medicine_name") or ""
    is_consumable = item_meta.get("is_consumable_items", False) or bool(item_dict.get("is_consumable_items", False))

    matched_stocks = []
    if req_batch:
        req_batch_str = str(req_batch).strip()
        matched_stocks = (
            stock_by_batch.get((item_id, req_batch_str))
            or (stock_by_batch.get((item_id_int, req_batch_str)) if item_id_int is not None else None)
            or (stock_by_batch.get((str(item_id).strip(), req_batch_str)) if item_id is not None else None)
            or []
        )
    if not matched_stocks:
        matched_stocks = (
            stock_by_item.get(item_id)
            or (stock_by_item.get(item_id_int) if item_id_int is not None else None)
            or (stock_by_item.get(str(item_id).strip()) if item_id is not None else None)
            or []
        )

    latest_stock = matched_stocks[0] if matched_stocks else None
    if latest_stock and not req_batch:
        req_batch = latest_stock.get("batch_number")

    total_stock = sum(_safe_float(s.get("total_stock")) for s in matched_stocks)
    sold = sum(_safe_float(s.get("sold_quantity")) for s in matched_stocks)
    transferred = sum(_safe_float(s.get("transferred_out_quantity")) for s in matched_stocks)
    grn_return = sum(_safe_float(s.get("grn_return_quantity")) for s in matched_stocks)
    available_stock = total_stock - sold - transferred - grn_return

    if latest_stock:
        if not item_name and latest_stock.get("item_name"):
            item_name = latest_stock.get("item_name")
        mrp = _safe_float(latest_stock.get("mrp"))
        selling_price = _safe_float(latest_stock.get("Selling_Price"))
        cgst_per = _safe_float(latest_stock.get("CGST_Percentage"))
        sgst_per = _safe_float(latest_stock.get("SGST_Percentage"))
        cgst_amt = _safe_float(latest_stock.get("CGST_Amt"))
        sgst_amt = _safe_float(latest_stock.get("SGST_Amt"))
    else:
        mrp = selling_price = cgst_per = sgst_per = cgst_amt = sgst_amt = 0.0

    return {
        "item_name": item_name,
        "batch_number": req_batch,
        "mrp": mrp,
        "Selling_Price": selling_price,
        "available_stock": available_stock,
        "CGST_Percentage": cgst_per,
        "SGST_Percentage": sgst_per,
        "CGST_Amt": cgst_amt,
        "SGST_Amt": sgst_amt,
        "is_consumable_items": is_consumable
    }
