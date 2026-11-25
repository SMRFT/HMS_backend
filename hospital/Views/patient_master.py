import json
import os
import re
from datetime import datetime, time
import pytz
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from pyauth.auth import HasRoleAndDataPermission
from hospital.models import Patient, Billing, Refund
from .dbcollection import hms_db, patient_collection
from pymongo import MongoClient


def _get_diagnostics_profile_map(emp_ids):
    """
    Fetches employeeId -> employeeName mapping from Global.backend_diagnostics_profile
    """
    if not emp_ids:
        return {}
    emp_map = {}
    try:
        mongo_host = os.getenv("GLOBAL_DB_HOST", "mongodb://localhost:27017")
        if mongo_host:
            client = MongoClient(mongo_host)
            global_db = client["Global"]
            diag_col = global_db["backend_diagnostics_profile"]
            clean_ids = [str(e).strip() for e in emp_ids if str(e).strip()]
            for doc in diag_col.find({"$or": [{"employeeId": {"$in": clean_ids}}, {"employeeName": {"$in": clean_ids}}]}, {"employeeId": 1, "employeeName": 1}):
                eid = doc.get("employeeId")
                ename = doc.get("employeeName")
                if eid and ename:
                    emp_map[str(eid).strip()] = str(ename).strip()
                if ename:
                    emp_map[str(ename).strip()] = str(ename).strip()
    except Exception as e:
        print(f"Error fetching diagnostics profile map: {e}")
    return emp_map


def _safe_float(val, default=0.0):
    if val is None:
        return default
    try:
        return float(str(val))
    except Exception:
        return default


@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def patient_master_list(request):
    """
    Returns paginated patient records from hospital_patient with visit counts & latest visit details.
    Supports filters: search (UHID, Name, Mobile, City), from_date, to_date, gender, page, limit.
    """
    try:
        search_query = (request.query_params.get("search") or request.GET.get("search") or "").strip()
        from_date_str = (request.query_params.get("from_date") or request.GET.get("from_date") or "").strip()
        to_date_str = (request.query_params.get("to_date") or request.GET.get("to_date") or "").strip()
        gender_filter = (request.query_params.get("gender") or request.GET.get("gender") or "").strip()

        try:
            page = max(1, int(request.query_params.get("page") or request.GET.get("page") or 1))
        except (ValueError, TypeError):
            page = 1

        try:
            limit = min(200, max(5, int(request.query_params.get("limit") or request.GET.get("limit") or 25)))
        except (ValueError, TypeError):
            limit = 25

        query = {}

        # 1. Date Range filter (registration_date or created_date)
        if from_date_str and to_date_str:
            try:
                ist = pytz.timezone("Asia/Kolkata")
                start_dt = ist.localize(datetime.strptime(from_date_str, "%Y-%m-%d"))
                end_dt = ist.localize(datetime.strptime(to_date_str, "%Y-%m-%d") + timezone.timedelta(days=1))
                query["created_date"] = {"$gte": start_dt.astimezone(pytz.UTC), "$lt": end_dt.astimezone(pytz.UTC)}
            except Exception:
                pass

        # 2. Gender filter
        if gender_filter and gender_filter.upper() != "ALL":
            query["gender"] = {"$regex": f"^{re.escape(gender_filter)}", "$options": "i"}

        # 3. Global search
        if search_query:
            clean_search = search_query.strip()
            # If user searches digits (e.g. mobile or UHID suffix)
            q_clauses = [
                {"uhid": {"$regex": re.escape(clean_search), "$options": "i"}},
                {"firstName": {"$regex": re.escape(clean_search), "$options": "i"}},
                {"lastName": {"$regex": re.escape(clean_search), "$options": "i"}},
                {"name": {"$regex": re.escape(clean_search), "$options": "i"}},
                {"mobilePhone": {"$regex": re.escape(clean_search), "$options": "i"}},
                {"city": {"$regex": re.escape(clean_search), "$options": "i"}},
                {"permanent_address": {"$regex": re.escape(clean_search), "$options": "i"}},
            ]
            if query:
                query = {"$and": [query, {"$or": q_clauses}]}
            else:
                query = {"$or": q_clauses}

        total_count = patient_collection.count_documents(query)
        skip = (page - 1) * limit

        # Fetch patients sorted by created_date descending
        patient_cursor = patient_collection.find(query).sort([("created_date", -1), ("_id", -1)]).skip(skip).limit(limit)
        patients = list(patient_cursor)

        # Batch lookup visit statistics from hospital_billing
        uhids = [p.get("uhid") for p in patients if p.get("uhid")]
        visit_stats_map = {}
        if uhids:
            try:
                pipeline = [
                    {"$match": {"uhid": {"$in": uhids}}},
                    {"$sort": {"billed_date": -1}},
                    {
                        "$group": {
                            "_id": "$uhid",
                            "total_visits": {"$sum": 1},
                            "latest_visit_date": {"$first": "$billed_date"},
                            "latest_doctor": {"$first": "$doctorName"},
                            "latest_doctor_id": {"$first": "$doctor_id"},
                            "latest_bill_no": {"$first": "$bill_number"}
                        }
                    }
                ]
                stats_res = list(hms_db["hospital_billing"].aggregate(pipeline))
                for s in stats_res:
                    visit_stats_map[s["_id"]] = s
            except Exception as e:
                print(f"Error fetching visit stats for patients: {e}")

        # Format patients for response
        formatted_patients = []
        for p in patients:
            p_uhid = p.get("uhid", "")
            stats_entry = visit_stats_map.get(p_uhid, {})

            # Format full name with salutation
            sal = (p.get("salutation") or "").strip()
            fname = (p.get("firstName") or p.get("name") or "").strip()
            lname = (p.get("lastName") or "").strip()
            full_name = f"{sal} {fname} {lname}".strip() or fname or "Unnamed Patient"

            # Format registration date (IST)
            c_date = p.get("created_date") or p.get("registration_date")
            reg_date_str = ""
            if c_date:
                if hasattr(c_date, "astimezone"):
                    try:
                        c_date_ist = c_date.astimezone(pytz.timezone("Asia/Kolkata"))
                        reg_date_str = c_date_ist.strftime("%d-%m-%Y %I:%M %p")
                    except Exception:
                        reg_date_str = str(c_date)[:16]
                elif isinstance(c_date, str):
                    reg_date_str = c_date[:16]

            # Format latest visit date (IST)
            lv_date = stats_entry.get("latest_visit_date")
            latest_visit_str = ""
            if lv_date:
                if hasattr(lv_date, "astimezone"):
                    try:
                        lv_date_ist = lv_date.astimezone(pytz.timezone("Asia/Kolkata"))
                        latest_visit_str = lv_date_ist.strftime("%d-%m-%Y %I:%M %p")
                    except Exception:
                        latest_visit_str = str(lv_date)[:16]
                elif isinstance(lv_date, str):
                    latest_visit_str = lv_date[:16]

            # Guardian format
            g_type = p.get("guardian_type") or ("W/o" if str(p.get("gender") or "").upper().startswith("F") and p.get("spouse_name") else "S/o")
            g_name = (p.get("guardian_name") or p.get("spouse_name") or "").strip()
            guardian_display = f"{g_type} {g_name}" if g_name else "-"

            formatted_patients.append({
                "id": str(p.get("_id")),
                "uhid": p_uhid,
                "salutation": sal,
                "firstName": fname,
                "lastName": lname,
                "name": full_name,
                "age": p.get("age"),
                "gender": p.get("gender") or "",
                "dob": p.get("dob") or "",
                "mobilePhone": p.get("mobilePhone") or "",
                "email": p.get("email") or "",
                "permanent_address": p.get("permanent_address") or "",
                "area": p.get("area") or "",
                "city": p.get("city") or "",
                "district": p.get("district") or "",
                "state": p.get("state") or "Tamil Nadu",
                "zipcode": p.get("zipcode") or "",
                "blood_group": p.get("blood_group") or "",
                "guardian_type": g_type,
                "guardian_name": g_name,
                "guardian_display": guardian_display,
                "emergency_contact": p.get("emergency_contact") or "",
                "occupation": p.get("occupation") or "",
                "marital_status": p.get("marital_status") or "",
                "customer_type": p.get("customer_type") or "GENERAL",
                "company_name": p.get("company_name") or "",
                "referredBy": p.get("referredBy") or "",
                "registered_date": reg_date_str,
                "total_visits": stats_entry.get("total_visits", 0),
                "latest_visit_date": latest_visit_str,
                "latest_doctor": stats_entry.get("latest_doctor") or "",
                "latest_bill_no": stats_entry.get("latest_bill_no") or "",
            })

        return Response({
            "success": True,
            "total_count": total_count,
            "page": page,
            "limit": limit,
            "total_pages": max(1, (total_count + limit - 1) // limit),
            "data": formatted_patients
        }, status=status.HTTP_200_OK)

    except Exception as e:
        import traceback
        print(f"Error in patient_master_list: {e}")
        print(traceback.format_exc())
        return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["PUT"])
@permission_classes([HasRoleAndDataPermission])
def patient_master_update(request, uhid):
    """
    Updates patient demographics in hospital_patient and relational Patient model.
    """
    try:
        clean_uhid = str(uhid or "").strip()
        if not clean_uhid:
            return Response({"success": False, "error": "UHID is required"}, status=status.HTTP_400_BAD_REQUEST)

        doc = patient_collection.find_one({"uhid": clean_uhid})
        if not doc:
            return Response({"success": False, "error": f"Patient with UHID '{clean_uhid}' not found"}, status=status.HTTP_404_NOT_FOUND)

        data = request.data or {}
        user_id = data.get("auth-user-id") or request.headers.get("auth-user-id") or "system"

        # Fields allowed to update
        updatable_fields = [
            "salutation", "firstName", "lastName", "age", "gender", "dob",
            "mobilePhone", "email", "permanent_address", "area", "city",
            "district", "state", "zipcode", "blood_group", "guardian_type",
            "guardian_name", "spouse_name", "emergency_contact", "occupation",
            "marital_status", "customer_type", "company_name", "referredBy",
            "referred_doctor_phone"
        ]

        update_dict = {}
        for f in updatable_fields:
            if f in data:
                val = data.get(f)
                if f == "age" and val is not None and str(val).strip():
                    try:
                        f_val = float(val)
                        update_dict["age"] = int(f_val) if f_val.is_integer() else f_val
                    except (ValueError, TypeError):
                        update_dict["age"] = val
                else:
                    update_dict[f] = val

        # Handle full name sync
        fn = update_dict.get("firstName") or doc.get("firstName", "")
        ln = update_dict.get("lastName") or doc.get("lastName", "")
        sal = update_dict.get("salutation") or doc.get("salutation", "")
        update_dict["name"] = f"{fn} {ln}".strip() if (fn or ln) else doc.get("name", "")

        # Customer type and company name backward compatibility
        if "customerType" in data and "customer_type" not in update_dict:
            update_dict["customer_type"] = data["customerType"]
        if "customer_type" in update_dict:
            update_dict["customerType"] = update_dict["customer_type"]
        if "company_name" in update_dict:
            update_dict["companyName"] = update_dict["company_name"]

        # If customer_type is not insurance or corporate, clear company_code and company_name
        effective_cust_type = str(update_dict.get("customer_type") or doc.get("customer_type") or doc.get("customerType") or "").strip().lower()
        if effective_cust_type and effective_cust_type not in ["insurance", "corporate"]:
            update_dict["company_code"] = ""
            update_dict["company_name"] = ""
            update_dict["companyName"] = ""

        # Backward compatibility between guardian_name and spouse_name
        if "guardian_name" in update_dict and not update_dict.get("spouse_name"):
            update_dict["spouse_name"] = update_dict["guardian_name"]
        elif "spouse_name" in update_dict and not update_dict.get("guardian_name"):
            update_dict["guardian_name"] = update_dict["spouse_name"]

        update_dict["lastmodified_by"] = user_id
        update_dict["lastmodified_date"] = timezone.now()

        # 1. Update in MongoDB
        patient_collection.update_one({"uhid": clean_uhid}, {"$set": update_dict})

        # 2. Update relational Patient model if exists
        try:
            rel_patient = Patient.objects.filter(uhid=clean_uhid).first()
            if rel_patient:
                for k, v in update_dict.items():
                    if hasattr(rel_patient, k):
                        setattr(rel_patient, k, v)
                rel_patient.save()
        except Exception as rel_err:
            print(f"Notice: Relational patient sync warning: {rel_err}")

        # Also update patient_name, customer_type, company_name in hospital_billing so bill listings stay in sync
        try:
            new_patient_name = f"{sal} {fn} {ln}".strip() if (fn or ln) else fn
            bill_update_fields = {}
            if new_patient_name:
                bill_update_fields["patient_name"] = new_patient_name
            if sal:
                bill_update_fields["salutation"] = sal
            if "gender" in update_dict:
                bill_update_fields["gender"] = update_dict["gender"]
            if "mobilePhone" in update_dict:
                bill_update_fields["mobile_phone"] = update_dict["mobilePhone"]
            if "customer_type" in update_dict:
                bill_update_fields["customer_type"] = update_dict["customer_type"]
                bill_update_fields["customerType"] = update_dict["customer_type"]
            if "company_name" in update_dict:
                bill_update_fields["company_name"] = update_dict["company_name"]
                bill_update_fields["companyName"] = update_dict["company_name"]

            if bill_update_fields:
                hms_db["hospital_billing"].update_many(
                    {"uhid": clean_uhid},
                    {"$set": bill_update_fields}
                )
        except Exception as bill_sync_err:
            print(f"Notice: Billing patient name sync warning: {bill_sync_err}")

        return Response({
            "success": True,
            "message": "Patient updated successfully",
            "uhid": clean_uhid
        }, status=status.HTTP_200_OK)

    except Exception as e:
        import traceback
        print(f"Error in patient_master_update: {e}")
        print(traceback.format_exc())
        return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def patient_op_visits(request, uhid):
    """
    Returns all OP consultation and registration visit records for a patient by UHID.
    Includes bill number, date/time in IST, doctor, department, fees breakdown, payment details, and refunds.
    """
    try:
        clean_uhid = str(uhid or "").strip()
        if not clean_uhid:
            return Response({"success": False, "error": "UHID is required"}, status=status.HTTP_400_BAD_REQUEST)

        # 1. Fetch patient master record for context
        patient_doc = patient_collection.find_one({"uhid": clean_uhid})
        if not patient_doc:
            patient_doc = {}

        # 2. Fetch all bills for this UHID sorted by billed_date descending
        bills_cursor = hms_db["hospital_billing"].find({"uhid": clean_uhid}).sort("billed_date", -1)
        bills = list(bills_cursor)

        # Collect employee / doctor IDs for name resolution
        doctor_ids = set()
        bill_numbers = []
        for b in bills:
            did = b.get("doctor_id") or b.get("doctorId") or b.get("doctor")
            if did:
                doctor_ids.add(str(did).strip())
            b_num = b.get("bill_number") or b.get("bill_no")
            if b_num:
                bill_numbers.append(str(b_num).strip())

        doc_name_map = _get_diagnostics_profile_map(doctor_ids)

        # Batch fetch refunds
        refund_map = {}
        if bill_numbers:
            try:
                for r in Refund.objects.filter(bill_no__in=bill_numbers):
                    amt = r.refund_amount
                    if hasattr(amt, "to_decimal"):
                        amt = amt.to_decimal()
                    ref_dt_str = ""
                    if r.refund_date:
                        ref_dt = r.refund_date
                        if timezone.is_naive(ref_dt):
                            ref_dt = timezone.make_aware(ref_dt)
                        ref_dt_str = timezone.localtime(ref_dt).strftime("%d-%m-%Y %I:%M %p")

                    refund_map.setdefault(r.bill_no, []).append({
                        "id": r.id,
                        "refund_amount": _safe_float(amt),
                        "refund_reason": r.refund_reason or "",
                        "refund_date": ref_dt_str,
                        "refunded_by": r.refunded_by or ""
                    })
            except Exception as ref_err:
                print(f"Error fetching refunds for patient visits: {ref_err}")

        # Format visits
        visits_data = []
        kolkata_tz = pytz.timezone("Asia/Kolkata")

        for idx, b in enumerate(bills):
            raw_b_num = b.get("bill_number") or b.get("bill_no") or f"BILL-{idx+1}"
            clean_b_num = str(raw_b_num).replace("/", "")

            # Format Billed Date & Time in IST
            b_date = b.get("billed_date") or b.get("created_date")
            b_date_str = ""
            b_time_str = ""
            if b_date:
                if isinstance(b_date, str):
                    try:
                        dt_obj = datetime.fromisoformat(b_date.replace("Z", "+00:00"))
                        if dt_obj.tzinfo is None:
                            dt_obj = pytz.UTC.localize(dt_obj)
                        dt_ist = dt_obj.astimezone(kolkata_tz)
                        b_date_str = dt_ist.strftime("%d-%m-%Y")
                        b_time_str = dt_ist.strftime("%I:%M %p")
                    except Exception:
                        b_date_str = b_date[:10]
                        b_time_str = b_date[11:16] if len(b_date) > 16 else ""
                elif hasattr(b_date, "astimezone"):
                    try:
                        if b_date.tzinfo is None:
                            b_date = pytz.UTC.localize(b_date)
                        b_date_ist = b_date.astimezone(kolkata_tz)
                        b_date_str = b_date_ist.strftime("%d-%m-%Y")
                        b_time_str = b_date_ist.strftime("%I:%M %p")
                    except Exception:
                        b_date_str = str(b_date)[:10]
                        b_time_str = str(b_date)[11:16]

            # Resolve Doctor Name
            raw_did = str(b.get("doctor_id") or b.get("doctorId") or "").strip()
            resolved_doc = doc_name_map.get(raw_did) or b.get("doctorName") or b.get("doctor") or raw_did or "N/A"

            # Payment details
            pay_method = str(b.get("payment_method") or b.get("paymentMethod") or "Cash").strip()
            pay_status = str(b.get("payment_status") or b.get("paymentStatus") or "Paid").strip()

            tot_fees = _safe_float(b.get("total_fees") or b.get("totalAmount") or b.get("total_amount") or 0)
            reg_fee = _safe_float(b.get("registration_fee") or 0)
            cons_fee = _safe_float(b.get("consulting_fee") or (tot_fees - reg_fee))

            # Refund details
            refunds = refund_map.get(raw_b_num, []) or refund_map.get(clean_b_num, [])
            total_refunded = sum(r["refund_amount"] for r in refunds)
            if total_refunded >= tot_fees and tot_fees > 0:
                pay_status = "Refunded"

            # Visit Type (New vs Review)
            p_created = patient_doc.get("created_date")
            visit_type = "Review"
            if p_created and b_date:
                try:
                    if hasattr(p_created, "date") and hasattr(b_date, "date"):
                        visit_type = "New" if p_created.date() == b_date.date() else "Review"
                except Exception:
                    visit_type = "Review"

            visits_data.append({
                "id": str(b.get("_id") or b.get("id")),
                "billNumber": clean_b_num,
                "rawBillNumber": raw_b_num,
                "uhid": clean_uhid,
                "patientName": b.get("patient_name") or patient_doc.get("name") or "Patient",
                "salutation": b.get("salutation") or patient_doc.get("salutation") or "",
                "gender": b.get("gender") or patient_doc.get("gender") or "",
                "age": patient_doc.get("age") or b.get("age") or "",
                "mobilePhone": patient_doc.get("mobilePhone") or b.get("mobile_phone") or "",
                "permanentAddress": patient_doc.get("permanent_address") or "",
                "area": patient_doc.get("area") or "",
                "city": patient_doc.get("city") or "",
                "district": patient_doc.get("district") or "",
                "state": patient_doc.get("state") or "",
                "zipcode": patient_doc.get("zipcode") or "",
                "guardianName": patient_doc.get("guardian_name") or patient_doc.get("spouse_name") or "",
                "guardianType": patient_doc.get("guardian_type") or "S/o",
                "date": b_date_str,
                "time": b_time_str,
                "dateTime": f"{b_date_str} {b_time_str}".strip(),
                "doctorId": raw_did,
                "doctorName": resolved_doc,
                "department": b.get("department_name") or b.get("department") or "",
                "tokenNumber": b.get("token_number") or "",
                "visitType": visit_type,
                "registrationFee": reg_fee,
                "consultingFee": cons_fee,
                "billAmount": tot_fees,
                "totalFees": tot_fees,
                "paymentMethod": pay_method,
                "paymentStatus": pay_status,
                "company_name": b.get("company_name") or patient_doc.get("company_name") or "",
                "customerType": b.get("customer_type") or patient_doc.get("customer_type") or "GENERAL",
                "preparedBy": b.get("created_by") or "Staff",
                "refunds": refunds,
                "totalRefunded": total_refunded,
            })

        return Response({
            "success": True,
            "uhid": clean_uhid,
            "patient": {
                "uhid": clean_uhid,
                "name": f"{(patient_doc.get('salutation') or '').strip()} {(patient_doc.get('firstName') or '').strip()} {(patient_doc.get('lastName') or '').strip()}".strip() or patient_doc.get("name") or "Patient",
                "age": patient_doc.get("age"),
                "gender": patient_doc.get("gender"),
                "mobilePhone": patient_doc.get("mobilePhone"),
                "city": patient_doc.get("city"),
                "registered_date": str(patient_doc.get("created_date") or "")[:10]
            },
            "total_visits": len(visits_data),
            "data": visits_data
        }, status=status.HTTP_200_OK)

    except Exception as e:
        import traceback
        print(f"Error in patient_op_visits: {e}")
        print(traceback.format_exc())
        return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["PUT", "POST"])
@permission_classes([HasRoleAndDataPermission])
def patient_bill_update(request, bill_number):
    """
    Update OP Registration / Consultation bill details.
    Allows changing the consulting Doctor (doctor_id, doctorName, department),
    fees (consulting_fee, total_fees), and records audit history.
    """
    try:
        clean_b_num = str(bill_number or "").strip()
        if not clean_b_num:
            return Response({"success": False, "error": "Bill number is required"}, status=status.HTTP_400_BAD_REQUEST)

        data = request.data
        if not data:
            return Response({"success": False, "error": "No update payload provided"}, status=status.HTTP_400_BAD_REQUEST)

        # Support variations with or without slash
        raw_variants = [clean_b_num]
        if "/" in clean_b_num:
            raw_variants.append(clean_b_num.replace("/", ""))
        elif len(clean_b_num) == 10 and clean_b_num[:4].isdigit():
            raw_variants.append(f"{clean_b_num[:4]}/{clean_b_num[4:]}")

        match_query = {
            "$or": [
                {"bill_number": {"$in": raw_variants}},
                {"bill_no": {"$in": raw_variants}}
            ]
        }

        bill_doc = hms_db["hospital_billing"].find_one(match_query)
        if not bill_doc:
            return Response({"success": False, "error": f"Bill '{clean_b_num}' not found"}, status=status.HTTP_404_NOT_FOUND)

        update_set = {}
        old_doctor_id = str(bill_doc.get("doctor_id") or bill_doc.get("doctorId") or "").strip()
        old_doctor_name = str(bill_doc.get("doctorName") or bill_doc.get("doctor") or "").strip()

        # 1. Update Doctor
        new_doctor_id = str(data.get("doctor_id") or data.get("doctorId") or "").strip()
        new_doctor_name = str(data.get("doctor_name") or data.get("doctorName") or "").strip()
        new_department = str(data.get("department") or data.get("department_name") or "").strip()

        # If doctor_name not passed, try to resolve from employee diagnostics map
        if new_doctor_id and not new_doctor_name:
            doc_map = _get_diagnostics_profile_map([new_doctor_id])
            new_doctor_name = doc_map.get(new_doctor_id, new_doctor_id)

        if new_doctor_id:
            update_set["doctor_id"] = new_doctor_id
            update_set["doctorId"] = new_doctor_id
            if new_doctor_name:
                update_set["doctorName"] = new_doctor_name
                update_set["doctor"] = new_doctor_name
            if new_department:
                update_set["department"] = new_department
                update_set["department_name"] = new_department

        # 2. Update Fees if provided
        if "consulting_fee" in data or "consultingFee" in data:
            c_fee = _safe_float(data.get("consulting_fee") if "consulting_fee" in data else data.get("consultingFee"))
            update_set["consulting_fee"] = c_fee
            reg_fee = _safe_float(bill_doc.get("registration_fee") or 0)
            update_set["total_fees"] = reg_fee + c_fee
            update_set["totalAmount"] = reg_fee + c_fee

        if "total_fees" in data or "totalFees" in data:
            t_fee = _safe_float(data.get("total_fees") if "total_fees" in data else data.get("totalFees"))
            update_set["total_fees"] = t_fee
            update_set["totalAmount"] = t_fee

        # Audit information
        user_id = str(getattr(request.user, "username", "") or getattr(request.user, "id", "") or "Staff")
        now_utc = datetime.utcnow()
        update_set["lastmodified_date"] = now_utc
        update_set["lastmodified_by"] = user_id

        # Prepare audit history entry
        reason = str(data.get("reason") or data.get("remarks") or "Doctor updated via Patients Master").strip()
        history_entry = {
            "action": "doctor_change",
            "from_doctor_id": old_doctor_id,
            "from_doctor_name": old_doctor_name,
            "to_doctor_id": new_doctor_id or old_doctor_id,
            "to_doctor_name": new_doctor_name or old_doctor_name,
            "changed_at": now_utc,
            "changed_by": user_id,
            "reason": reason
        }

        # Perform MongoDB update
        hms_db["hospital_billing"].update_one(
            match_query,
            {
                "$set": update_set,
                "$push": {"doctor_change_history": history_entry}
            }
        )

        return Response({
            "success": True,
            "message": "Bill and Doctor details updated successfully",
            "bill_number": bill_doc.get("bill_number") or clean_b_num,
            "doctor_id": new_doctor_id or old_doctor_id,
            "doctorName": new_doctor_name or old_doctor_name,
            "department": new_department or bill_doc.get("department", "")
        }, status=status.HTTP_200_OK)

    except Exception as e:
        import traceback
        print(f"Error in patient_bill_update: {e}")
        print(traceback.format_exc())
        return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
