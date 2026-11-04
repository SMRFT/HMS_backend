from pymongo import MongoClient
import os
from dotenv import load_dotenv
load_dotenv(override=True)

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
designation_collection            = global_db["backend_diagnostics_Designation"]
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
cashcounter_collection            = hms_db["hospital_cashcounter"]
cashcounter_shift_collection      = hms_db["hospital_cashcountershiftdetails"]
hospital_room                     = hms_db["hospital_room"]
hospital_tumour_board_collection  = hms_db["hospital_tumourBoard"]
hospital_tumour_template_collection = hms_db["hospital_tumourTemplate"]

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
    if not emp:
        emp = profile_collection.find_one({
            "$or": [
                {"employeeId": emp_str.upper()},
                {"employeeId": emp_str.lower()},
                {"userId": emp_str}
            ]
        })
    if emp and "employeeName" in emp:
        return emp["employeeName"]
    if emp and "name" in emp:
        return emp["name"]
    return "Unknown"


def resolve_created_by_name(created_by):
    """
    Resolves the display name for `created_by`:
    - If empty or None -> returns ""
    - If it contains numbers (e.g. employeeId '60002', '1042') -> looks up employeeName via get_employee_name_by_id
    - If lookup finds a valid name (not 'Unknown') -> returns that employeeName
    - If it has only alphabets (e.g. 'admin', 'Sister Mary') or fallback -> returns created_by as it is
    """
    if not created_by:
        return ""
    val_str = str(created_by).strip()
    if not val_str:
        return ""
    if any(c.isdigit() for c in val_str):
        try:
            emp_name = get_employee_name_by_id(val_str)
            if emp_name and emp_name.strip().lower() != "unknown":
                return emp_name
        except Exception:
            pass
    return val_str


def get_room_details(room_input, hospital_code=None, branch_code=None):
    """
    Looks up room details from hospital_room collection.
    Matches room_number against room_input (e.g. '304 | 2', 'Room 304', '103', 'SR-304').
    Returns dict: {
        'room_category': ...,
        'block': ...,
        'nursing_station': ...,
        'room_number': ...,
        'description': ...,
        'room_status': ...
    }
    """
    res = {
        "room_category": "",
        "block": "",
        "nursing_station": "",
        "room_number": "",
        "description": "",
        "room_status": ""
    }
    if not room_input:
        return res

    s = str(room_input).strip()
    s_clean = re.sub(r'(?i)^room\s*', '', s).strip()
    parts = re.split(r'\||/|\bbed\b', s_clean, flags=re.I)
    candidate = parts[0].strip()

    base_filter = {}
    if hospital_code:
        base_filter["hospital_code"] = hospital_code
    if branch_code:
        base_filter["branch_code"] = branch_code

    # Priority 1: Exact match on candidate or original string
    doc = hospital_room.find_one({**base_filter, "room_number": candidate})
    if not doc and candidate.isdigit():
        doc = hospital_room.find_one({**base_filter, "room_number": int(candidate)})
    if not doc:
        doc = hospital_room.find_one({**base_filter, "room_number": s})

    # Priority 2: Case-insensitive match
    if not doc:
        doc = hospital_room.find_one({**base_filter, "room_number": {"$regex": f"^{re.escape(candidate)}$", "$options": "i"}})

    # Priority 3: Suffix / prefix regex match (e.g., candidate '304' matches 'SR-304', or '103' matches '103')
    if not doc:
        num_match = re.search(r'\d+', candidate)
        if num_match:
            num = num_match.group(0)
            doc = hospital_room.find_one({**base_filter, "room_number": {"$regex": f"(^|[-_a-zA-Z]){num}$", "$options": "i"}})
            if not doc:
                doc = hospital_room.find_one({**base_filter, "room_number": {"$regex": num, "$options": "i"}})

    # Fallback without hospital_code / branch_code if not found
    if not doc and base_filter:
        doc = hospital_room.find_one({"room_number": candidate})
        if not doc and candidate.isdigit():
            doc = hospital_room.find_one({"room_number": int(candidate)})
        if not doc:
            doc = hospital_room.find_one({"room_number": {"$regex": f"^{re.escape(candidate)}$", "$options": "i"}})
        if not doc:
            num_match = re.search(r'\d+', candidate)
            if num_match:
                num = num_match.group(0)
                doc = hospital_room.find_one({"room_number": {"$regex": f"(^|[-_a-zA-Z]){num}$", "$options": "i"}})
                if not doc:
                    doc = hospital_room.find_one({"room_number": {"$regex": num, "$options": "i"}})

    if doc:
        res["room_category"] = str(doc.get("room_category") or "").strip()
        res["block"] = str(doc.get("block") or "").strip()
        res["nursing_station"] = str(doc.get("nursing_station") or "").strip()
        res["room_number"] = str(doc.get("room_number") or candidate).strip()
        res["description"] = str(doc.get("description") or "").strip()
        res["room_status"] = str(doc.get("room_status") or "").strip()
    else:
        res["room_number"] = candidate

    return res


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


# ==============================================================================
# Cash Counter & Bill Type Permission Engine (aud -> profile -> cashcounter)
# ==============================================================================

def extract_aud_employee_id(request_or_payload):
    """
    Extracts employee ID (aud) from user_payload dictionary, request headers/META,
    or directly from a string/int.
    """
    if not request_or_payload:
        return ""

    if isinstance(request_or_payload, (str, int)):
        return str(request_or_payload).strip()

    if isinstance(request_or_payload, dict):
        for key in ("aud", "employeeId", "employee_id", "auth-user-id", "user_id"):
            if key in request_or_payload and request_or_payload[key]:
                return str(request_or_payload[key]).strip()

    req = request_or_payload
    emp_id = None
    if hasattr(req, "data") and isinstance(req.data, dict):
        emp_id = (
            req.data.get("auth-user-id")
            or req.data.get("user_id")
            or req.data.get("employeeId")
            or req.data.get("aud")
        )

    if not emp_id and hasattr(req, "META"):
        emp_id = (
            req.META.get("HTTP_AUTH_USER_ID")
            or req.META.get("HTTP_USER_ID")
            or req.META.get("HTTP_EMPLOYEEID")
        )

    if not emp_id and hasattr(req, "headers"):
        emp_id = req.headers.get("auth-user-id") or req.headers.get("user-id")

    if not emp_id and hasattr(req, "META"):
        auth_header = req.META.get("HTTP_AUTHORIZATION", "")
        if auth_header:
            try:
                import jwt
                token = auth_header.replace("Bearer ", "").strip()
                payload = jwt.decode(token, options={"verify_signature": False})
                emp_id = payload.get("aud") or payload.get("user_id") or payload.get("employeeId")
            except Exception:
                pass

    return str(emp_id).strip() if emp_id else ""


def get_employee_cashcounter_permissions(employee_id_or_request, hospital_code=None, branch_code=None, outlet_code=None):
    """
    1. Compares employeeId (from aud/user_payload) into backend_diagnostics_profile.
    2. Takes hms_outlets and cashcounter from the matching profile.
    3. Compares cashcounter into hospital_cashcounter collection matching counter code and outlet.
    4. Returns the matched counter, permitted bill types, and allowed outlets.
       Only the matched counter's bill types and outlets are permitted for this aud.
    """
    emp_id = extract_aud_employee_id(employee_id_or_request)
    if not outlet_code and hasattr(employee_id_or_request, "headers"):
        outlet_code = employee_id_or_request.headers.get("Outlet-Code") or getattr(employee_id_or_request, "data", {}).get("auth-outlet-code") if hasattr(employee_id_or_request, "data") and isinstance(employee_id_or_request.data, dict) else None
    if not emp_id:
        return {
            "success": False,
            "message": "No valid employee ID (aud) provided",
            "employee_id": "",
            "counter_id": None,
            "counter_name": "",
            "outlet": None,
            "hms_outlets": [],
            "allowed_outlets": [],
            "allowed_bill_types": [],
            "allowed_bill_names": [],
            "bill_type_details": []
        }

    # 1. Compare aud into backend_diagnostics_profile
    try:
        search_query = {"employeeId": {"$in": [emp_id, int(emp_id) if emp_id.isdigit() else emp_id]}}
    except Exception:
        search_query = {"employeeId": str(emp_id)}

    profile = profile_collection.find_one(search_query)
    if not profile:
        return {
            "success": False,
            "message": f"Profile not found for employee {emp_id}",
            "employee_id": emp_id,
            "counter_id": None,
            "counter_name": "",
            "outlet": None,
            "hms_outlets": [],
            "allowed_outlets": [],
            "allowed_bill_types": [],
            "allowed_bill_names": [],
            "bill_type_details": []
        }

    emp_cashcounter = profile.get("cashcounter")
    hms_outlets = profile.get("hms_outlets") or []
    if not isinstance(hms_outlets, list):
        hms_outlets = [hms_outlets]

    if not emp_cashcounter:
        return {
            "success": False,
            "message": f"No cashcounter assigned to employee {emp_id}",
            "employee_id": emp_id,
            "employee_name": profile.get("employeeName", ""),
            "counter_id": None,
            "counter_name": "",
            "outlet": None,
            "hms_outlets": hms_outlets,
            "allowed_outlets": hms_outlets,
            "allowed_bill_types": [],
            "allowed_bill_names": [],
            "bill_type_details": []
        }

    # 2. Compare cashcounter into hospital_cashcounter matching counter code and outlet
    cashcounter_doc = None

    # Priority 1: Match employee's assigned counter AND the active outlet
    if outlet_code:
        cc_outlet_query = {
            "counter_id": emp_cashcounter,
            "outlet": outlet_code,
            "is_active": True
        }
        if hospital_code:
            cc_outlet_query["hospital_code"] = hospital_code
        if branch_code:
            cc_outlet_query["branch_code"] = branch_code
        cashcounter_doc = cashcounter_collection.find_one(cc_outlet_query)
        if not cashcounter_doc:
            cashcounter_doc = cashcounter_collection.find_one({
                "counter_id": emp_cashcounter,
                "outlet": outlet_code,
                "is_active": True
            })

    # Priority 2: If user switched outlet and employee has permission for this outlet, match outlet's counter
    if not cashcounter_doc and outlet_code and (outlet_code in hms_outlets or not hms_outlets):
        switched_query = {
            "outlet": outlet_code,
            "is_active": True
        }
        if hospital_code:
            switched_query["hospital_code"] = hospital_code
        if branch_code:
            switched_query["branch_code"] = branch_code
        cashcounter_doc = cashcounter_collection.find_one(switched_query)
        if not cashcounter_doc:
            cashcounter_doc = cashcounter_collection.find_one({
                "outlet": outlet_code,
                "is_active": True
            })

    # Priority 3: Default to employee's assigned cashcounter
    if not cashcounter_doc:
        cc_query = {
            "counter_id": emp_cashcounter,
            "is_active": True
        }
        if hospital_code:
            cc_query["hospital_code"] = hospital_code
        if branch_code:
            cc_query["branch_code"] = branch_code
        cashcounter_doc = cashcounter_collection.find_one(cc_query)
        if not cashcounter_doc and (hospital_code or branch_code):
            cashcounter_doc = cashcounter_collection.find_one({
                "counter_id": emp_cashcounter,
                "is_active": True
            })

    if not cashcounter_doc:
        return {
            "success": False,
            "message": f"Assigned cashcounter '{emp_cashcounter}' not found or inactive in hospital_cashcounter",
            "employee_id": emp_id,
            "employee_name": profile.get("employeeName", ""),
            "counter_id": emp_cashcounter,
            "counter_name": "",
            "outlet": None,
            "hms_outlets": hms_outlets,
            "allowed_outlets": hms_outlets,
            "allowed_bill_types": [],
            "allowed_bill_names": [],
            "bill_type_details": []
        }

    counter_id = cashcounter_doc.get("counter_id")
    counter_name = cashcounter_doc.get("counter_name", "")
    counter_outlet = cashcounter_doc.get("outlet")
    bill_type_details = cashcounter_doc.get("bill_type") or []

    allowed_bill_types = []
    allowed_bill_names = []
    for bt in bill_type_details:
        b_id = bt.get("bill_type")
        if b_id is not None:
            try:
                allowed_bill_types.append(int(b_id))
            except (ValueError, TypeError):
                allowed_bill_types.append(b_id)
        b_name = bt.get("bill_name")
        if b_name:
            allowed_bill_names.append(str(b_name).strip().upper())

    allowed_outlets = []
    if counter_outlet:
        allowed_outlets.append(counter_outlet)
    for out in hms_outlets:
        if out and out not in allowed_outlets:
            allowed_outlets.append(out)

    return {
        "success": True,
        "employee_id": emp_id,
        "employee_name": profile.get("employeeName", ""),
        "counter_id": counter_id,
        "counter_name": counter_name,
        "outlet": counter_outlet,
        "hms_outlets": hms_outlets,
        "allowed_outlets": allowed_outlets,
        "allowed_bill_types": allowed_bill_types,
        "allowed_bill_names": allowed_bill_names,
        "bill_type_details": bill_type_details,
        "cashcounter_details": {
            "counter_id": counter_id,
            "counter_name": counter_name,
            "outlet": counter_outlet
        }
    }


def validate_employee_cashcounter_access(
    employee_id_or_request,
    requested_counter=None,
    requested_outlet=None,
    requested_bill_type=None,
    hospital_code=None,
    branch_code=None
):
    """
    Validates whether the employee (aud) is permitted to access the requested
    counter, outlet, or bill_type.
    If the employee is assigned to CC0002, requests for CC0001 or bill types not
    in CC0002 will be blocked with an informative error message.

    Returns: (is_allowed: bool, message: str, perms: dict)
    """
    perms = get_employee_cashcounter_permissions(
        employee_id_or_request,
        hospital_code=hospital_code,
        branch_code=branch_code
    )
    if not perms.get("success"):
        return False, perms.get("message", "Permission check failed"), perms

    emp_id = perms["employee_id"]
    assigned_counter = perms["counter_id"]

    # 1. Counter Check
    if requested_counter:
        req_c = str(requested_counter).strip()
        if req_c.upper() != str(assigned_counter).strip().upper():
            return (
                False,
                f"Access blocked: Cashier {emp_id} is assigned to counter '{assigned_counter}' ({perms['counter_name']}) and cannot access counter '{requested_counter}'.",
                perms
            )

    # 2. Outlet Check
    if requested_outlet:
        req_o = str(requested_outlet).strip().upper()
        allowed_upper = [str(o).strip().upper() for o in perms["allowed_outlets"]]
        if req_o not in allowed_upper:
            return (
                False,
                f"Access blocked: Cashier {emp_id} is not permitted for outlet '{requested_outlet}'. Allowed outlets: {perms['allowed_outlets']}.",
                perms
            )

    # 3. Bill Type Check
    if requested_bill_type is not None:
        try:
            req_bt_int = int(requested_bill_type)
        except (ValueError, TypeError):
            req_bt_int = None
        req_bt_str = str(requested_bill_type).strip().upper()

        int_match = req_bt_int is not None and req_bt_int in perms["allowed_bill_types"]
        name_match = req_bt_str in perms["allowed_bill_names"]

        if not (int_match or name_match):
            return (
                False,
                f"Access blocked: Bill type '{requested_bill_type}' is not allowed for counter '{assigned_counter}'. Allowed bill types: {perms['allowed_bill_types']}.",
                perms
            )

    return True, "Access granted", perms


def filter_bills_by_employee_counter(
    employee_id_or_request,
    bills_list,
    bill_type_key="bill_type",
    hospital_code=None,
    branch_code=None
):
    """
    Filters a list of bill dictionaries to strictly include only bills whose
    bill_type belongs to the employee's assigned cash counter in hospital_cashcounter.
    """
    perms = get_employee_cashcounter_permissions(
        employee_id_or_request,
        hospital_code=hospital_code,
        branch_code=branch_code
    )
    if not perms.get("success") or not perms.get("allowed_bill_types"):
        return []

    allowed_types = set(perms["allowed_bill_types"])
    allowed_names = set(perms["allowed_bill_names"])

    filtered = []
    for bill in bills_list:
        bt_val = bill.get(bill_type_key)
        if bt_val is None:
            bt_val = bill.get("type") or bill.get("bill_name")
        try:
            bt_int = int(bt_val)
        except (ValueError, TypeError):
            bt_int = None
        bt_str = str(bt_val).strip().upper() if bt_val else ""

        if (bt_int is not None and bt_int in allowed_types) or (bt_str in allowed_names):
            filtered.append(bill)

    return filtered


def enforce_cashcounter_permission(
    employee_id_or_request,
    requested_counter=None,
    requested_outlet=None,
    requested_bill_type=None,
    hospital_code=None,
    branch_code=None
):
    """
    Helper for view functions.
    If access is denied, returns a DRF Response with status HTTP_403_FORBIDDEN.
    If access is granted, returns None.
    """
    from rest_framework.response import Response
    from rest_framework import status

    allowed, message, perms = validate_employee_cashcounter_access(
        employee_id_or_request,
        requested_counter=requested_counter,
        requested_outlet=requested_outlet,
        requested_bill_type=requested_bill_type,
        hospital_code=hospital_code,
        branch_code=branch_code
    )

    if not allowed:
        return Response(
            {
                "status": "error",
                "code": "COUNTER_ACCESS_DENIED",
                "message": message,
                "assigned_counter": perms.get("counter_id"),
                "allowed_bill_types": perms.get("allowed_bill_types", []),
                "allowed_outlets": perms.get("allowed_outlets", [])
            },
            status=status.HTTP_403_FORBIDDEN
        )

    return None
