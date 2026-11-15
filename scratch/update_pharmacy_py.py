import re

with open("HMS_backend/hospital/Views/pharmacy.py", "r", encoding="utf-8") as f:
    content = f.read()

pattern = r'(@api_view\(\["GET"\]\)\s*@permission_classes\(\[HasRoleAndDataPermission\]\)\s*def pharmacy_view_bills\(request\):.*?\n)(?=@api_view\(\[\'POST\'\]\)\s*@permission_classes\(\[HasRoleAndDataPermission\]\)\s*def pharmacy_expiry_report)'

match = re.search(pattern, content, re.DOTALL)
if not match:
    print("ERROR: Pattern not matched!")
    exit(1)

print(f"Matched pharmacy_view_bills: {len(match.group(1))} characters.")

replacement = '''@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def pharmacy_view_bills(request):

    # =========================================================
    # ✅ Get values from REQUEST
    # =========================================================
    employee_id    = request.data.get("auth-user-id")
    hospital_code  = request.data.get("auth-hospital-code")
    branch_code    = request.data.get("auth-branch-code")
    request_outlet = resolve_request_outlet(request, request.data)

    # =========================================================
    # ✅ Guard
    # =========================================================
    if not hospital_code or not branch_code or not request_outlet or not employee_id:
        return Response({
            "success": False,
            "message": "Missing required headers (hospital, branch, outlet, or employee)"
        }, status=400)

    # =========================================================
    # ✅ MongoDB Connections
    # =========================================================
    client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
    global_db = client["Global"]
    profile_collection = global_db["backend_diagnostics_profile"]

    hms_db = client["HMS"]
    billtype_collection      = hms_db["hospital_billtype"]
    pharmacy_item_collection = hms_db["hospital_pharmacyitem"]
    oppharmacy_collection    = hms_db["hospital_pharmacybilling"]
    patient_collection       = hms_db["hospital_patient"]
    admission_collection     = hms_db["hospital_admission"]
    insurance_collection     = hms_db["hospital_insuranceprovider"]

    # =========================================================
    # ✅ Employee Profile
    # =========================================================
    try:
        query_id = str(employee_id)
        search_query = {
            "employeeId": {
                "$in": [
                    query_id,
                    int(query_id) if query_id.isdigit() else query_id
                ]
            }
        }
    except Exception:
        search_query = {"employeeId": str(employee_id)}

    employee_profile = profile_collection.find_one(
        search_query,
        {
            "employeeId":   1,
            "employeeName": 1,
            "hms_outlets":  1
        }
    )

    if not employee_profile:
        return Response({
            "success": False,
            "message": "Employee not found"
        }, status=404)

    emp_outlets = employee_profile.get("hms_outlets", [])
    emp_name    = employee_profile.get("employeeName", employee_id)

    # =========================================================
    # ✅ Outlet Validation
    # =========================================================
    if isinstance(request_outlet, (list, tuple)):
        valid_outlets = [o for o in request_outlet if o in emp_outlets]
        if not valid_outlets:
            return Response({
                "success": False,
                "message": f"Outlet {request_outlet} not mapped to employee"
            }, status=403)
        matched_outlet = valid_outlets[0]
    else:
        if request_outlet not in emp_outlets:
            return Response({
                "success": False,
                "message": f"Outlet {request_outlet} not mapped to employee"
            }, status=403)
        matched_outlet = request_outlet

    # =========================================================
    # ✅ Get All Bill Types (Bulk 1 query)
    # =========================================================
    billtype_cursor = billtype_collection.find(
        {
            "hospital_code": hospital_code,
            "branch_code":   branch_code
        },
        {
            "bill_type": 1,
            "bill_name": 1,
            "_id": 0
        }
    )

    billtype_map       = {}
    allowed_bill_types = []

    for bt in billtype_cursor:
        bt_val = bt.get("bill_type")
        if bt_val is not None:
            try:
                bt_int = int(bt_val)
                allowed_bill_types.append(bt_int)
                billtype_map[bt_int] = bt.get("bill_name", "")
            except (ValueError, TypeError):
                pass

    # =========================================================
    # ✅ Query Parameters: Date, Search, Bill Type, Limit
    # =========================================================
    from_date_str = request.GET.get("from_date") or request.query_params.get("from_date")
    to_date_str   = request.GET.get("to_date")   or request.query_params.get("to_date")
    search_by     = (request.GET.get("search_by") or request.query_params.get("search_by") or "").strip()
    search_value  = (request.GET.get("search_value") or request.query_params.get("search_value") or "").strip()
    bill_type_param = request.GET.get("bill_type") or request.query_params.get("bill_type")
    limit_param   = request.GET.get("limit") or request.query_params.get("limit")

    try:
        limit = min(int(limit_param), 2000) if limit_param else 1000
    except (ValueError, TypeError):
        limit = 1000

    from_dt = None
    to_dt   = None
    if from_date_str:
        try:
            from_dt = datetime.strptime(from_date_str.strip(), "%Y-%m-%d")
        except Exception:
            pass

    if to_date_str:
        try:
            to_dt = datetime.strptime(to_date_str.strip(), "%Y-%m-%d").replace(hour=23, minute=59, second=59, microsecond=999999)
        except Exception:
            pass

    # =========================================================
    # ✅ Direct High-Speed MongoDB Bill Query
    # =========================================================
    bill_q = {
        "hospital_code": hospital_code,
        "branch_code":   branch_code,
        "billing_status": {"$in": ["Billed", "Paid", "Processing", "deleted"]}
    }

    if isinstance(matched_outlet, (list, tuple)):
        bill_q["outlet_code"] = {"$in": list(matched_outlet)}
    elif matched_outlet:
        bill_q["outlet_code"] = matched_outlet

    if bill_type_param and bill_type_param != "ALL":
        try:
            bill_q["bill_type"] = int(bill_type_param)
        except (ValueError, TypeError):
            if allowed_bill_types:
                bill_q["bill_type"] = {"$in": allowed_bill_types}
    elif allowed_bill_types:
        bill_q["bill_type"] = {"$in": allowed_bill_types}

    if from_dt and to_dt:
        bill_q["$or"] = [
            {"bill_date": {"$gte": from_dt, "$lte": to_dt}},
            {"bill_date": {"$gte": from_date_str.strip(), "$lte": to_date_str.strip() + "T23:59:59.999999"}}
        ]
    elif from_dt:
        bill_q["$or"] = [
            {"bill_date": {"$gte": from_dt}},
            {"bill_date": {"$gte": from_date_str.strip()}}
        ]
    elif to_dt:
        bill_q["$or"] = [
            {"bill_date": {"$lte": to_dt}},
            {"bill_date": {"$lte": to_date_str.strip() + "T23:59:59.999999"}}
        ]

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

    # Fetch bills directly via PyMongo
    bills = list(oppharmacy_collection.find(bill_q).sort("bill_date", -1).limit(limit))

    # =========================================================
    # ✅ Collect IDs for Instant In-Memory Bulk Joins
    # =========================================================
    uhids      = set()
    doctor_ids = set()
    emp_ids    = set()
    item_ids   = set()

    for b in bills:
        u = b.get("uhid")
        if u:
            uhids.add(str(u).strip())
        doc_id = b.get("doctor_id")
        if doc_id:
            doctor_ids.add(str(doc_id).strip())
        for fld in ["billed_id", "created_by", "cashier_id"]:
            val = b.get(fld)
            if val:
                emp_ids.add(str(val).strip())
        for it in (b.get("medicine_particulars") or []):
            if isinstance(it, dict) and it.get("item_id"):
                item_ids.add(it["item_id"])

    # =========================================================
    # ✅ Bulk Join 1: Patients & Insurance Codes (1 query)
    # =========================================================
    patient_map     = {}
    patient_ins_map = {}
    all_comp_codes  = set()

    if uhids:
        for p in patient_collection.find(
            {"uhid": {"$in": list(uhids)}},
            {"uhid": 1, "salutation": 1, "firstName": 1, "lastName": 1, "company_code": 1, "customer_type": 1, "_id": 0}
        ):
            sal = (p.get("salutation") or "").strip()
            fn  = (p.get("firstName") or "").strip()
            ln  = (p.get("lastName") or "").strip()
            if ln.lower() == fn.lower():
                ln = ""
            full_n = " ".join(f"{sal} {fn} {ln}".split())
            patient_map[p["uhid"]] = full_n
            cc = (p.get("company_code") or "").strip()
            if cc:
                patient_ins_map[p["uhid"]] = cc
                all_comp_codes.add(cc)
            elif str(p.get("customer_type") or "").upper() == "INSURANCE":
                patient_ins_map[p["uhid"]] = "INSURANCE"

    # =========================================================
    # ✅ Bulk Join 2: Admissions (1 query)
    # =========================================================
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

    # =========================================================
    # ✅ Bulk Join 3: Insurance Providers (1 query)
    # =========================================================
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

    # =========================================================
    # ✅ Bulk Join 4: Profiles (Doctors & Employees in 1 query)
    # =========================================================
    all_pids    = list(doctor_ids | emp_ids)
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
            ename   = prof.get("employeeName", "")
            if ename:
                profile_map[eid_str] = ename
                try:
                    profile_map[str(int(eid_str))] = ename
                except (ValueError, TypeError):
                    pass

    # =========================================================
    # ✅ Bulk Join 5: Pharmacy Items (1 query)
    # =========================================================
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
            except (ValueError, TypeError):
                pass

    # =========================================================
    # ✅ Helpers for serialization
    # =========================================================
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

    # =========================================================
    # ✅ Build Bills Data (Fast direct in-memory serialization)
    # =========================================================
    data = []

    for b in bills:
        serialized = {}
        for k, v in b.items():
            if k == "_id":
                serialized["_id"] = str(v)
            else:
                serialized[k] = serialize_val(v)

        u = b.get("uhid") or ""
        p_name = patient_map.get(u) or b.get("patientname") or ""
        serialized["patient_name"] = p_name
        serialized["patientname"]  = p_name

        # Doctor
        doc_id_val = str(b.get("doctor_id") or "").strip()
        serialized["doctor_name"] = profile_map.get(doc_id_val, "")

        # Bill type name
        bt_val = b.get("bill_type")
        serialized["bill_type_name"] = billtype_map.get(int(bt_val) if bt_val is not None else 0, "")

        # Billed / Employee name
        billed_id_val = str(b.get("billed_id") or "").strip()
        created_val   = str(b.get("created_by") or "").strip()
        cashier_val   = str(b.get("cashier_id") or "").strip()

        billed_display = (
            profile_map.get(billed_id_val) or
            profile_map.get(cashier_val) or
            profile_map.get(created_val) or
            billed_id_val or
            created_val
        )
        serialized["billed_id"]       = billed_id_val or None
        serialized["billed_name"]     = billed_display
        serialized["employee_name"]   = billed_display
        serialized["prepared_by"]     = billed_display
        serialized["created_by_name"] = profile_map.get(created_val, created_val)

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
        serialized["insurance_name"]    = final_ins
        serialized["insurance_company"] = final_ins

        if not serialized.get("inpatient_number") and (adm_doc.get("ipNumber") or adm_doc.get("inpatient_number")):
            serialized["inpatient_number"] = adm_doc.get("ipNumber") or adm_doc.get("inpatient_number")

        if not serialized.get("room_no") and adm_doc.get("room_details"):
            rooms = adm_doc.get("room_details") or []
            active_r = next((r for r in rooms if r.get("is_roomActive")), rooms[0] if rooms else None)
            if active_r:
                serialized["room_no"] = " | ".join(filter(None, [active_r.get("ward"), active_r.get("room_no") or active_r.get("room")]))

        # Line items
        updated_items = []
        for item in (b.get("medicine_particulars") or []):
            if not isinstance(item, dict):
                continue
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
        if to_num(serialized.get("total_amount", 0)) == 0.0 and items_total > 0:
            serialized["total_amount"] = round(items_total, 2)
        if to_num(serialized.get("net_amount", 0)) == 0.0 and items_total > 0:
            serialized["net_amount"] = round(items_total, 2)

        serialized["medicine_particulars"] = updated_items
        data.append(serialized)

    # =========================================================
    # ✅ Final Response
    # =========================================================
    return Response({
        "employee_id":   employee_id,
        "employee_name": emp_name,
        "data":          data,
    }, status=status.HTTP_200_OK)



'''

new_content = content[:match.start(1)] + replacement + content[match.end(1):]
with open("HMS_backend/hospital/Views/pharmacy.py", "w", encoding="utf-8") as f:
    f.write(new_content)

print("SUCCESS: pharmacy.py updated successfully!")

