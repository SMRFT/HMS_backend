import re

NEW_FUNC = '''@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def OPPharmacy_pending_bills(request):
    """
    Endpoint to retrieve pending, unpaid, and received outpatient (OP) pharmacy cash bills.
    Validates cashier counter assignment, verifies an active shift, dynamically filters
    by hospital/branch/outlet/payment_mode, and enriches raw bill records.
    """
    try:
        # Extract parsed request data if available; fallback to empty dict
        data = request.data if hasattr(request, "data") and isinstance(request.data, dict) else {}

        # Dynamically resolve employee ID from payload, headers, query params, or JWT
        employee_id = (
            data.get("auth-user-id")
            or request.headers.get("User-Id")
            or request.headers.get("user-id")
            or request.headers.get("auth-user-id")
            or request.GET.get("auth-user-id")
            or request.GET.get("user_id")
            or request.GET.get("employee_id")
            or extract_aud_employee_id(request)
        )

        # ✅ DYNAMIC AUTH CODES (Tenant & Branch Context - No Hardcoding)
        hospital_code = (
            data.get("auth-hospital-code")
            or request.headers.get("Hospital-Code")
            or request.headers.get("hospital-code")
            or request.headers.get("auth-hospital-code")
            or request.GET.get("auth-hospital-code")
            or request.GET.get("hospital_code")
        )
        branch_code = (
            data.get("auth-branch-code")
            or request.headers.get("Branch-Code")
            or request.headers.get("branch-code")
            or request.headers.get("auth-branch-code")
            or request.GET.get("auth-branch-code")
            or request.GET.get("branch_code")
        )
        outlet_code = (
            data.get("auth-outlet-code")
            or request.headers.get("Outlet-Code")
            or request.headers.get("outlet-code")
            or request.headers.get("auth-outlet-code")
            or request.GET.get("auth-outlet-code")
            or request.GET.get("outlet_code")
            or request.GET.get("outlet")
        )

        from .dbcollection import (
            hms_db,
            global_db,
            profile_collection,
            pharmacy_item_collection,
            pharmacy_stock_collection,
            pharmacy_billing_collection as oppharmacy_collection,
            cashcounter_collection,
            patient_collection,
            hms_billtype as billtype_collection
        )

        # Look up cashier permissions, assigned counter ID, and allowed bill types
        emp_perms = get_employee_cashcounter_permissions(
            employee_id or request,
            hospital_code=hospital_code,
            branch_code=branch_code,
            outlet_code=outlet_code
        )

        requested_counter = data.get("CashCounter") or request.GET.get("CashCounter")

        if emp_perms.get("success"):
            hospital_code             = hospital_code or emp_perms.get("hospital_code")
            branch_code               = branch_code or emp_perms.get("branch_code")
            cashcounter_details       = emp_perms["cashcounter_details"]
            allowed_bill_type_details = emp_perms["bill_type_details"]
            allowed_bill_types        = emp_perms["allowed_bill_types"]
            emp_cashcounter           = emp_perms["counter_id"]
            matched_outlet            = emp_perms["outlet"] or outlet_code
            emp_name                  = emp_perms.get("employee_name") or str(employee_id)
        else:
            # Fallback: Dynamically resolve cash counter from DB without hardcoding
            counter_filter = {"is_active": True}
            if hospital_code: counter_filter["hospital_code"] = hospital_code
            if branch_code: counter_filter["branch_code"] = branch_code

            if requested_counter:
                counter_filter["counter_id"] = str(requested_counter).strip()
            elif outlet_code and isinstance(outlet_code, str):
                counter_filter["outlet"] = outlet_code

            counter_doc = cashcounter_collection.find_one(counter_filter)
            if not counter_doc and (hospital_code or branch_code):
                counter_doc = cashcounter_collection.find_one({
                    "hospital_code": hospital_code,
                    "branch_code": branch_code,
                    "is_active": True
                })

            if counter_doc:
                emp_cashcounter     = counter_doc.get("counter_id", "")
                matched_outlet      = counter_doc.get("outlet") or outlet_code
                hospital_code       = hospital_code or counter_doc.get("hospital_code")
                branch_code         = branch_code or counter_doc.get("branch_code")
                cashcounter_details = {
                    "counter_id": emp_cashcounter,
                    "counter_name": counter_doc.get("counter_name", ""),
                    "outlet": matched_outlet
                }
                raw_bts = counter_doc.get("bill_type") or counter_doc.get("bill_types") or []
                allowed_bill_types = []
                allowed_bill_type_details = []
                if isinstance(raw_bts, list):
                    for bt in raw_bts:
                        if isinstance(bt, dict) and "bill_type" in bt:
                            allowed_bill_types.append(bt["bill_type"])
                            allowed_bill_type_details.append(bt)
                        elif str(bt).isdigit():
                            allowed_bill_types.append(int(bt))
                if allowed_bill_types and not allowed_bill_type_details:
                    bt_docs = list(billtype_collection.find({"bill_type": {"$in": allowed_bill_types}}, {"bill_type": 1, "bill_name": 1, "_id": 0}))
                    allowed_bill_type_details = [{"bill_type": b.get("bill_type"), "bill_name": b.get("bill_name", "")} for b in bt_docs]
            else:
                emp_cashcounter     = str(requested_counter or "").strip()
                matched_outlet      = outlet_code
                cashcounter_details = {"counter_id": emp_cashcounter, "counter_name": "", "outlet": matched_outlet}
                allowed_bill_types  = []
                allowed_bill_type_details = []

            emp_name = str(employee_id or "")

        # Check counter requested by frontend
        if requested_counter and emp_perms.get("success") and emp_perms.get("counter_id"):
            if str(requested_counter).strip().upper() != str(emp_perms["counter_id"]).strip().upper():
                return Response({
                    "status": "error",
                    "code": "COUNTER_ACCESS_DENIED",
                    "message": f"Access blocked: Cashier {emp_perms['employee_id']} is assigned to counter '{emp_perms['counter_id']}' ({emp_perms['counter_name']}) and cannot access counter '{requested_counter}'.",
                    "cashcounter": emp_perms.get("cashcounter_details"),
                    "allowed_bill_type_details": emp_perms.get("bill_type_details", []),
                    "data": []
                }, status=status.HTTP_403_FORBIDDEN)

        # =========================================================
        # ✅ VERIFY ACTIVE SHIFT IN DB (DYNAMIC LOOKUP)
        # =========================================================
        shift_col = hms_db["hospital_cashcountershiftdetails"]
        counter_id_check = (cashcounter_details.get("counter_id") if cashcounter_details else None) or emp_cashcounter or requested_counter

        active_shift = None
        if counter_id_check:
            sq = {
                "ShiftStatus": {"$regex": "^active$", "$options": "i"},
                "is_active": True,
                "CashCounter": counter_id_check
            }
            if hospital_code: sq["hospital_code"] = hospital_code
            if branch_code: sq["branch_code"] = branch_code
            active_shift = shift_col.find_one(sq)

        if not active_shift and employee_id:
            sq = {
                "CashierID": str(employee_id),
                "ShiftStatus": {"$regex": "^active$", "$options": "i"},
                "is_active": True
            }
            if hospital_code: sq["hospital_code"] = hospital_code
            if branch_code: sq["branch_code"] = branch_code
            active_shift = shift_col.find_one(sq)

        if not active_shift and (counter_id_check or employee_id):
            if counter_id_check:
                active_shift = shift_col.find_one({
                    "ShiftStatus": {"$regex": "^active$", "$options": "i"},
                    "is_active": True,
                    "CashCounter": counter_id_check
                })
            if not active_shift and employee_id:
                active_shift = shift_col.find_one({
                    "CashierID": str(employee_id),
                    "ShiftStatus": {"$regex": "^active$", "$options": "i"},
                    "is_active": True
                })

        if active_shift:
            hospital_code = hospital_code or active_shift.get("hospital_code")
            branch_code   = branch_code or active_shift.get("branch_code")
            if not emp_cashcounter:
                emp_cashcounter = active_shift.get("CashCounter")
                if cashcounter_details:
                    cashcounter_details["counter_id"] = emp_cashcounter
        else:
            return Response({
                "employee_id": employee_id,
                "employee_name": emp_name,
                "cashcounter": cashcounter_details,
                "allowed_bill_type_details": allowed_bill_type_details,
                "shift_active": False,
                "message": "Shift not started. Please start a shift to view bills.",
                "data": []
            }, status=status.HTTP_200_OK)

        # =========================================================
        # ✅ Query Pharmacy Bills via PyMongo (Dynamic & Robust)
        # =========================================================
        date_str = request.GET.get("date") or data.get("date")
        from_date_str = request.GET.get("from_date") or data.get("from_date")
        to_date_str = request.GET.get("to_date") or data.get("to_date")
        req_status = (request.GET.get("status") or (data.get("status") if isinstance(data, dict) else "") or request.GET.get("type") or "").strip().lower()

        from_dt = None
        to_dt = None
        if from_date_str and to_date_str:
            try:
                from_dt = datetime.strptime(from_date_str.strip()[:10], "%Y-%m-%d")
                to_dt = datetime.strptime(to_date_str.strip()[:10], "%Y-%m-%d").replace(hour=23, minute=59, second=59, microsecond=999999)
            except Exception:
                pass
        elif date_str:
            try:
                from_dt = datetime.strptime(date_str.strip()[:10], "%Y-%m-%d")
                to_dt = from_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
            except Exception:
                pass

        import pytz
        ist = pytz.timezone("Asia/Kolkata")
        now_ist = datetime.now(ist)
        today_date_ist = now_ist.date()

        today_start_local = datetime.combine(today_date_ist, datetime.min.time())
        today_end_local = datetime.combine(today_date_ist, datetime.max.time())
        today_start_ist = ist.localize(today_start_local)
        today_end_ist = ist.localize(today_end_local)
        today_start_utc = today_start_ist.astimezone(pytz.utc).replace(tzinfo=None)
        today_end_utc = today_end_ist.astimezone(pytz.utc).replace(tzinfo=None)
        today_str = today_date_ist.strftime("%Y-%m-%d")

        # Base MongoDB filter: exclude deleted records
        mongo_filter = {
            "is_deleted": {"$ne": True}
        }
        if hospital_code:
            mongo_filter["hospital_code"] = hospital_code
        if branch_code:
            mongo_filter["branch_code"] = branch_code

        # Dynamic Payment Mode filter
        req_pm = (
            request.GET.get("payment_mode")
            or request.GET.get("paymentMode")
            or request.GET.get("PaymentType")
            or request.GET.get("payment_method")
            or data.get("payment_mode")
            or ""
        ).strip()

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
            # Default for cash counter: cash-eligible bills (exclude Credit & Insurance)
            mongo_filter["payment_mode"] = {"$nin": ["Credit", "credit", "CREDIT", "Insurance", "insurance"]}

        # Dynamic Bill Type Filter
        req_bill_type = request.GET.get("bill_type") or request.GET.get("billType") or data.get("bill_type")
        if req_bill_type:
            bt_val = int(req_bill_type) if str(req_bill_type).isdigit() else str(req_bill_type).strip()
            mongo_filter["bill_type"] = {"$in": [bt_val, str(bt_val)]}
        elif allowed_bill_types:
            expanded_bts = []
            for bt in allowed_bill_types:
                expanded_bts.append(bt)
                if str(bt).isdigit():
                    expanded_bts.append(int(bt))
                expanded_bts.append(str(bt))
            mongo_filter["bill_type"] = {"$in": list(set(expanded_bts))}

        # Dynamic Outlet Code Filter
        req_outlet = (
            request.GET.get("outlet_code")
            or request.GET.get("outlet")
            or matched_outlet
            or outlet_code
            or ""
        )
        if isinstance(req_outlet, (list, tuple)):
            clean_outlets = [str(x).strip() for x in req_outlet if str(x).strip() and str(x).strip().upper() != "ALL"]
            if len(clean_outlets) == 1:
                mongo_filter["outlet_code"] = clean_outlets[0]
            elif clean_outlets:
                mongo_filter["outlet_code"] = {"$in": clean_outlets}
        elif req_outlet and str(req_outlet).strip().upper() not in ["ALL", ""]:
            mongo_filter["outlet_code"] = str(req_outlet).strip()

        # Dynamic Search Filter (matches bill_no, uhid, patient_name, inpatient_number, Bill_id)
        search_query = (request.GET.get("search") or request.GET.get("q") or "").strip()
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
            status_and_conditions.append({"$or": search_conditions})

        if from_dt and to_dt:
            mongo_filter["billing_status"] = {"$in": ["Billed", "Paid", "Processing", "Pending"]}
            date_ors = []
            for fld in ["paid_date", "paid_datetime", "bill_date", "created_date"]:
                date_ors.append({fld: {"$gte": from_dt, "$lte": to_dt}})
            status_and_conditions.append({"$or": date_ors})
        elif req_status == "pending":
            # 🎯 Pending Bills: Current date alone in Indian Time (unpaid)
            mongo_filter["billing_status"] = {"$in": ["Billed", "Processing", "Pending"]}
            date_ors = []
            for fld in ["bill_date", "created_date"]:
                date_ors.extend(make_date_conditions(fld, today_start_local, today_end_local, today_start_utc, today_end_utc, today_str))
            status_and_conditions.append({"$or": date_ors})
        elif req_status == "unpaid":
            # 🎯 Unpaid Bills: Prior dates before today (backlog/overdue unpaid bills)
            mongo_filter["billing_status"] = {"$in": ["Billed", "Processing", "Pending"]}
            status_and_conditions.append({"$or": [
                {"bill_date": {"$lt": today_start_local}},
                {"created_date": {"$lt": today_start_local}},
                {"bill_date": {"$lt": today_start_utc}},
                {"created_date": {"$lt": today_start_utc}},
                {"created_date": {"$lt": today_str}},
            ]})
        elif req_status in ["received", "paid"]:
            # 🎯 Received Bills: Current date paid cash bills
            mongo_filter["billing_status"] = "Paid"
            date_ors = []
            for fld in ["paid_date", "paid_datetime", "bill_date", "created_date"]:
                date_ors.extend(make_date_conditions(fld, today_start_local, today_end_local, today_start_utc, today_end_utc, today_str))
            status_and_conditions.append({"$or": date_ors})
        elif not search_query:
            # 🎯 Default: All unpaid cash bills + Paid cash bills from current date
            today_paid_ors = []
            for fld in ["paid_date", "paid_datetime", "bill_date", "created_date"]:
                today_paid_ors.extend(make_date_conditions(fld, today_start_local, today_end_local, today_start_utc, today_end_utc, today_str))
            status_and_conditions.append({"$or": [
                {"billing_status": {"$in": ["Billed", "Processing", "Pending"]}},
                {
                    "billing_status": "Paid",
                    "$or": today_paid_ors
                }
            ]})

        if status_and_conditions:
            if "$and" in mongo_filter:
                mongo_filter["$and"].extend(status_and_conditions)
            else:
                mongo_filter["$and"] = status_and_conditions

        limit_val = int(request.GET.get("limit") or 500)
        raw_bills = list(oppharmacy_collection.find(mongo_filter).sort("created_date", -1).limit(limit_val))

        if not raw_bills:
            return Response({
                "employee_id": employee_id,
                "employee_name": emp_name,
                "cashcounter": cashcounter_details,
                "allowed_bill_type_details": allowed_bill_type_details,
                "shift_active": True,
                "data": []
            }, status=status.HTTP_200_OK)

        # =========================================================
        # ✅ Patient Mapping (Batch fetch)
        # =========================================================
        uhids_to_fetch = set()
        for b in raw_bills:
            p_name = b.get("patient_name") or b.get("patientname") or b.get("patientName") or b.get("customer_name")
            if not p_name and b.get("uhid"):
                uhids_to_fetch.add(str(b.get("uhid")).strip())

        patient_map = {}
        if uhids_to_fetch:
            try:
                uhids_list = list(uhids_to_fetch)
                for i in range(0, len(uhids_list), 100):
                    chunk = uhids_list[i:i + 100]
                    p_cursor = patient_collection.find(
                        {"uhid": {"$in": chunk}},
                        {"uhid": 1, "salutation": 1, "firstName": 1, "lastName": 1, "_id": 0}
                    )
                    for p in p_cursor:
                        u = str(p.get("uhid") or "").strip()
                        name = f"{p.get('salutation') or ''} {p.get('firstName') or ''} {p.get('lastName') or ''}".strip()
                        if u:
                            patient_map[u] = name
            except Exception:
                pass

        # =========================================================
        # ✅ Doctor Mapping (Batch fetch)
        # =========================================================
        doctor_ids = []
        for b in raw_bills:
            d_id = b.get("doctor_id")
            if d_id:
                s_id = str(d_id).strip()
                doctor_ids.append(s_id)
                if s_id.isdigit():
                    doctor_ids.append(int(s_id))
        doctor_ids = list(set(doctor_ids))

        doctor_map = {}
        if doctor_ids:
            try:
                doctor_cursor = profile_collection.find(
                    {"employeeId": {"$in": doctor_ids}},
                    {"employeeId": 1, "employeeName": 1, "_id": 0}
                )
                for doc in doctor_cursor:
                    doc_name = doc.get("employeeName", "")
                    if doc_name and not doc_name.lower().startswith("dr"):
                        doc_name = f"Dr. {doc_name}"
                    doctor_map[str(doc.get("employeeId"))] = doc_name
            except Exception:
                pass

        # =========================================================
        # ✅ Bill Type Mapping
        # =========================================================
        bill_types = []
        for b in raw_bills:
            bt = b.get("bill_type")
            if bt is not None:
                bill_types.append(bt)
                if str(bt).isdigit():
                    bill_types.append(int(bt))
                bill_types.append(str(bt))
        bill_types = list(set(bill_types))

        billtype_map = {}
        if bill_types:
            try:
                bt_cursor = billtype_collection.find(
                    {"bill_type": {"$in": bill_types}},
                    {"bill_type": 1, "bill_name": 1, "_id": 0}
                )
                for doc in bt_cursor:
                    bt_val = doc.get("bill_type")
                    billtype_map[bt_val] = doc.get("bill_name", "")
                    if str(bt_val).isdigit():
                        billtype_map[int(bt_val)] = doc.get("bill_name", "")
            except Exception:
                pass

        # =========================================================
        # ✅ Item Names Resolution
        # =========================================================
        missing_item_ids = set()
        for b in raw_bills:
            for item in b.get("medicine_particulars", []):
                if isinstance(item, dict) and not item.get("item_name"):
                    iid = item.get("item_id")
                    if iid is not None:
                        try:
                            missing_item_ids.add(int(iid))
                        except (ValueError, TypeError):
                            missing_item_ids.add(str(iid))

        item_map = {}
        if missing_item_ids:
            try:
                chunk_list = list(missing_item_ids)
                for i in range(0, len(chunk_list), 100):
                    chunk = chunk_list[i:i + 100]
                    item_cursor = pharmacy_item_collection.find(
                        {"item_id": {"$in": chunk}},
                        {"item_id": 1, "item_name": 1, "_id": 0}
                    )
                    for doc in item_cursor:
                        item_map[doc["item_id"]] = doc.get("item_name", "")
            except Exception:
                pass

        # =========================================================
        # ✅ Final Response Serialization
        # =========================================================
        bills_result = []
        for bill in raw_bills:
            serialized = dict(bill)
            if "_id" in serialized:
                serialized["_id"] = str(serialized["_id"])
            for d_key in ["created_date", "lastmodified_date", "bill_date", "paid_date", "paid_datetime", "ward_request_date"]:
                val = serialized.get(d_key)
                if val and hasattr(val, "isoformat"):
                    serialized[d_key] = val.isoformat()

            # Bill totals decimal normalization
            for amt_key in ["total_amount", "net_amount", "round_off", "discount_amount", "overall_discount_amount", "overall_discount_value", "total_item_discount"]:
                if amt_key in serialized:
                    serialized[amt_key] = convert_decimal(serialized.get(amt_key, 0))

            b_status = str(bill.get("billing_status") or "").strip()
            is_unpaid_status = b_status in ["Billed", "Processing", "Pending"]
            is_paid_status = (b_status == "Paid")

            if is_paid_status:
                raw_bdate = bill.get("paid_date") or bill.get("paid_datetime") or bill.get("lastmodified_date") or bill.get("bill_date") or bill.get("created_date")
            else:
                raw_bdate = bill.get("bill_date") or bill.get("created_date")

            b_date_obj = None
            ist_date_str = "-"
            ist_time_str = "-"
            if raw_bdate:
                dt_obj = None
                if isinstance(raw_bdate, datetime):
                    dt_obj = pytz.utc.localize(raw_bdate) if raw_bdate.tzinfo is None else raw_bdate.astimezone(pytz.utc)
                elif isinstance(raw_bdate, date):
                    b_date_obj = raw_bdate
                    ist_date_str = f"{raw_bdate.day:02d}/{raw_bdate.month:02d}/{raw_bdate.year:04d}"
                    ist_time_str = "00:00"
                else:
                    s_val = str(raw_bdate).strip()
                    if s_val.endswith("Z"):
                        s_val = s_val[:-1] + "+00:00"
                    try:
                        dt_obj = datetime.fromisoformat(s_val)
                        if dt_obj.tzinfo is None:
                            dt_obj = pytz.utc.localize(dt_obj)
                        else:
                            dt_obj = dt_obj.astimezone(pytz.utc)
                    except Exception:
                        pass
                if dt_obj:
                    dt_ist = dt_obj.astimezone(ist)
                    b_date_obj = dt_ist.date()
                    ist_date_str = dt_ist.strftime("%d/%m/%Y")
                    ist_time_str = dt_ist.strftime("%I:%M:%S %p")

            is_today = bool(b_date_obj and b_date_obj == today_date_ist)

            serialized["ist_date"] = ist_date_str
            serialized["ist_time"] = ist_time_str
            serialized["display_date"] = ist_date_str
            serialized["display_time"] = ist_time_str
            serialized["is_current_date"] = is_today
            serialized["is_pending"] = bool(is_unpaid_status and is_today)
            serialized["is_unpaid"] = bool(is_unpaid_status and not is_today)
            serialized["is_received"] = bool(is_paid_status and is_today)

            uhid_str = str(bill.get("uhid") or "").strip()
            doc_id_str = str(bill.get("doctor_id") or "").strip()
            bt_raw = bill.get("bill_type")
            bt_key = int(bt_raw) if str(bt_raw).isdigit() else bt_raw

            p_name = (
                patient_map.get(uhid_str, "")
                or bill.get("patient_name")
                or bill.get("patientname")
                or bill.get("patientName")
                or bill.get("customer_name")
                or ""
            )
            serialized["patient_name"] = p_name
            serialized["patientname"]  = p_name
            serialized["uhid"]         = bill.get("uhid") or ""
            serialized["uhid_no"]      = bill.get("uhid") or ""
            # ✅ Preserve stored doctor name if profile lookup yields nothing
            serialized["doctor_name"]  = doctor_map.get(doc_id_str) or bill.get("doctor_name") or ""
            serialized["bill_type_name"] = billtype_map.get(bt_key, "")

            medicine_list = bill.get("medicine_particulars", [])
            updated_items = []
            for item in medicine_list:
                if not isinstance(item, dict):
                    continue
                it_dict = dict(item)
                iid_val = int(it_dict["item_id"]) if str(it_dict.get("item_id", "")).isdigit() else it_dict.get("item_id")

                it_dict["item_name"] = it_dict.get("item_name") or item_map.get(iid_val, "")

                # Normalize all item numeric fields using convert_decimal
                for f_num in ["price", "mrp", "calculated_price", "product_value", "taxable_value", "total", "discount_amount", "discount_value", "discount", "CGST_Percentage", "SGST_Percentage", "CGST_Amt", "SGST_Amt"]:
                    if f_num in it_dict:
                        it_dict[f_num] = convert_decimal(it_dict.get(f_num, 0))

                updated_items.append(it_dict)

            serialized["medicine_particulars"] = updated_items
            bills_result.append(serialized)

        # Apply final post-serialization filter according to requested tab/status
        req_status = (request.GET.get("status") or (data.get("status") if isinstance(data, dict) else "") or request.GET.get("type") or "").strip().lower()
        if req_status == "pending":
            bills_result = [b for b in bills_result if b.get("is_pending")]
        elif req_status == "unpaid":
            bills_result = [b for b in bills_result if b.get("is_unpaid")]
        elif req_status in ["received", "paid"]:
            bills_result = [b for b in bills_result if b.get("is_received")]

        return Response({
            "employee_id": employee_id,
            "employee_name": emp_name,
            "cashcounter": cashcounter_details,
            "allowed_bill_type_details": allowed_bill_type_details,
            "shift_active": True,
            "data": bills_result
        }, status=status.HTTP_200_OK)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({
            "status": "error",
            "message": "Failed to fetch OP Pharmacy pending bills",
            "details": str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
'''

target_file = 'HMS_backend/hospital/Views/cashcounter.py'
with open(target_file, 'r', encoding='utf-8') as f:
    code = f.read()

# Locate def OPPharmacy_pending_bills
pattern = r'(@api_view\(\["GET"\]\)[^\n]*\n@permission_classes\(\[HasRoleAndDataPermission\]\)[^\n]*\ndef OPPharmacy_pending_bills\(request\):[\s\S]*$)'

m = re.search(pattern, code)
if not m:
    print("Could not match pattern!")
else:
    updated_code = code[:m.start(1)] + NEW_FUNC + "\n"
    with open(target_file, 'w', encoding='utf-8') as f:
        f.write(updated_code)
    print("Successfully replaced OPPharmacy_pending_bills in cashcounter.py!")
