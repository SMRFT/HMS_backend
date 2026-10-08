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

doctor_role_code = "SD-R-DOC"
sample_collector = "SD-R-SMC"

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
    Note:
    - hospital_pharmacyitem has NO outlet_code (master at hospital_code + branch_code level).
    - hospital_pharmacystock matches hospital_code, branch_code, outlet_code, and item_id.
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

    # 1. Fetch from hospital_pharmacyitem (hospital_code + branch_code only, NO outlet_code)
    items_map = {}
    for itm in pharmacy_item_collection.find(
        {
            "hospital_code": hospital_code,
            "branch_code": branch_code,
            "item_id": {"$in": query_ids}
        },
        {"item_id": 1, "item_name": 1, "is_consumable_items": 1, "_id": 0}
    ):
        raw_id = itm.get("item_id")
        entry = {
            "item_name": itm.get("item_name") or "",
            "is_consumable_items": bool(itm.get("is_consumable_items", False))
        }
        items_map[raw_id] = entry
        items_map[str(raw_id).strip()] = entry
        try:
            items_map[int(raw_id)] = entry
        except (ValueError, TypeError):
            pass

    # 2. Fetch from hospital_pharmacystock (hospital_code + branch_code + outlet_code + item_id)
    stock_by_item = {}
    stock_by_batch = {}
    stock_cursor = pharmacy_stock_collection.find(
        {
            "hospital_code": hospital_code,
            "branch_code": branch_code,
            "outlet_code": outlet_code,
            "item_id": {"$in": query_ids}
        },
        {
            "stock_id": 1,
            "item_id": 1,
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
            "_id": 0
        }
    ).sort("stock_id", -1)

    for stk in stock_cursor:
        raw_id = stk.get("item_id")
        keys = {raw_id, str(raw_id).strip()}
        try:
            keys.add(int(raw_id))
        except (ValueError, TypeError):
            pass

        for k in keys:
            stock_by_item.setdefault(k, []).append(stk)

        bn = stk.get("batch_number")
        if bn:
            bn_str = str(bn).strip()
            for k in keys:
                stock_by_batch.setdefault((k, bn_str), []).append(stk)

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
