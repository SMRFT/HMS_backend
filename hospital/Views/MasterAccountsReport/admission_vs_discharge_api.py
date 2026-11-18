"""
Master Accounts: Admission vs Discharge Report API
===================================================
Provides a comprehensive audit of inpatient admissions, bed occupancy,
length of stay, advance collections, and final discharge clearances.
Fully isolated from legacy accounting views.
"""

from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from pyauth.auth import HasRoleAndDataPermission
from datetime import datetime, timedelta
import re
from .core_ledger_engine import (
    get_db,
    parse_date,
    format_ist_datetime,
    format_ist_date,
    clean_num
)


def _ip_sort_key(ip_str):
    nums = re.findall(r'\d+', str(ip_str or ''))
    return [int(n) for n in nums] if nums else [str(ip_str or '')]


def _parse_dt(dt_val):
    if not dt_val:
        return None
    if isinstance(dt_val, datetime):
        return dt_val
    if isinstance(dt_val, str):
        try:
            return datetime.fromisoformat(dt_val.replace('Z', '+00:00'))
        except Exception:
            for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d', '%d/%m/%Y %H:%M:%S', '%d/%m/%Y']:
                try:
                    return datetime.strptime(dt_val[:19], fmt)
                except Exception:
                    continue
    return None


@api_view(["GET", "POST"])
@permission_classes([HasRoleAndDataPermission])
def admission_vs_discharge_api(request):
    """
    Dedicated Master Accounts Admission vs Discharge Report API.
    Endpoint: /master-accounts/admission-vs-discharge/
    """
    client = None
    try:
        data = request.data if request.method == "POST" else request.query_params

        from_str = data.get("from_date") or data.get("start_date") or ""
        to_str = data.get("to_date") or data.get("end_date") or ""
        status_filter = (data.get("status") or data.get("patient_status") or "all").strip().lower()
        company_filter = (data.get("company") or data.get("company_name") or data.get("category") or data.get("bill_type") or "all").strip()
        search_query = (data.get("search") or data.get("q") or "").strip().lower()
        sort_order = (data.get("sort_order") or "asc").strip().lower()

        f_d = parse_date(from_str) if from_str else None
        t_d = parse_date(to_str, is_end=True) if to_str else None

        f_dt_utc = datetime.combine(f_d, datetime.min.time()) - timedelta(hours=5, minutes=30) if f_d else None
        t_dt_utc = datetime.combine(t_d, datetime.max.time()) - timedelta(hours=5, minutes=30) if t_d else None

        client, db, g_db = get_db()

        # 1. Fetch Insurance Provider Map
        ins_docs = list(db["hospital_insuranceprovider"].find({}, {"company_code": 1, "company_name": 1}))
        ins_map = {}
        for p in ins_docs:
            c_code = str(p.get("company_code") or "").strip()
            c_name = str(p.get("company_name") or "").strip()
            if c_code:
                ins_map[c_code] = c_name

        # 2. Identify relevant discharge bills in range
        dis_bill_query = {"is_cancelled": {"$ne": True}}
        if f_dt_utc and t_dt_utc:
            dis_bill_query["bill_date"] = {"$gte": f_dt_utc, "$lte": t_dt_utc}
        
        dis_bills_list = list(db["hospital_dischargebilling"].find(dis_bill_query))
        discharge_bills_by_ip = {}
        for dbill in dis_bills_list:
            ip_n = str(dbill.get("ip_number") or dbill.get("ipNumber") or "").strip()
            if ip_n and ip_n not in discharge_bills_by_ip:
                discharge_bills_by_ip[ip_n] = dbill

        # 3. Build candidate admissions query
        adm_query = {"is_cancelled": {"$ne": True}}
        
        if f_dt_utc and t_dt_utc:
            dis_ips = list(discharge_bills_by_ip.keys())
            or_clauses = [
                {"admissionDateTime": {"$gte": f_dt_utc, "$lte": t_dt_utc}},
                {"created_date": {"$gte": f_dt_utc, "$lte": t_dt_utc}}
            ]
            if dis_ips:
                or_clauses.append({"ipNumber": {"$in": dis_ips}})
            if status_filter != "discharged":
                or_clauses.append({"is_discharged": False})
            adm_query["$or"] = or_clauses
        elif status_filter == "admitted":
            adm_query["is_discharged"] = False
        elif status_filter == "discharged":
            adm_query["is_discharged"] = True

        admissions = list(db["hospital_admission"].find(adm_query))

        # 4. Bulk lookup patient names
        uhids = list(set([str(a.get("uhid")).strip() for a in admissions if a.get("uhid")]))
        patient_map = {}
        if uhids:
            for p in db["hospital_patient"].find({"uhid": {"$in": uhids}}, {"uhid": 1, "name": 1, "firstName": 1, "lastName": 1, "gender": 1, "age": 1}):
                u = str(p.get("uhid") or "").strip()
                p_name = p.get("name") or f"{p.get('firstName') or ''} {p.get('lastName') or ''}".strip() or u
                patient_map[u] = {
                    "name": p_name,
                    "gender": p.get("gender") or "",
                    "age": p.get("age") or ""
                }

        # 5. Bulk lookup doctor names from Global backend_diagnostics_profile
        doc_ids = set()
        for a in admissions:
            ad = str(a.get("admittingDoctor") or "").strip()
            cd = str(a.get("consultingDoctor") or "").strip()
            if ad:
                doc_ids.add(ad)
            if cd:
                doc_ids.add(cd)

        doctor_map = {}
        if doc_ids and g_db is not None:
            try:
                for doc in g_db["backend_diagnostics_profile"].find(
                    {"employeeId": {"$in": list(doc_ids)}},
                    {"employeeId": 1, "employeeName": 1, "name": 1, "firstName": 1, "lastName": 1}
                ):
                    e_id = str(doc.get("employeeId") or "").strip()
                    d_name = doc.get("employeeName") or doc.get("name") or f"{doc.get('firstName') or ''} {doc.get('lastName') or ''}".strip()
                    if e_id and d_name:
                        doctor_map[e_id] = d_name
            except Exception:
                pass

        now = datetime.now()
        records = []
        distinct_companies = set()

        for adm in admissions:
            ip = str(adm.get("ipNumber") or adm.get("ip_number") or "").strip()
            if not ip:
                continue

            uhid = str(adm.get("uhid") or "").strip()
            pinfo = patient_map.get(uhid) or {}
            pat_name = pinfo.get("name") or str(adm.get("patient_name") or adm.get("patientname") or uhid or "-").strip()

            # Room extraction
            room_list = adm.get("room_details") or []
            active_room = next((r for r in room_list if r.get("is_roomActive")), None)
            if not active_room and room_list:
                active_room = room_list[-1]
            room_str = "-"
            if active_room:
                rno = str(active_room.get("roomNo") or "").strip()
                bno = str(active_room.get("bedNo") or "").strip()
                room_str = f"{rno} / {bno}" if (rno and bno) else (rno if rno else "-")

            # Dates
            adm_dt = _parse_dt(adm.get("admissionDateTime") or adm.get("created_date"))
            dis_dt = None
            is_discharged = bool(adm.get("is_discharged"))

            dbill = discharge_bills_by_ip.get(ip)
            if is_discharged:
                if dbill and dbill.get("bill_date"):
                    dis_dt = _parse_dt(dbill.get("bill_date"))
                elif active_room and active_room.get("endDateTime"):
                    dis_dt = _parse_dt(active_room.get("endDateTime"))
                elif adm.get("dischargeDateTime"):
                    dis_dt = _parse_dt(adm.get("dischargeDateTime"))
                else:
                    dis_dt = _parse_dt(adm.get("lastmodified_date"))

            # Filter by Date Range:
            # Matches if admitting date or discharge date falls within [f_d, t_d],
            # or if currently admitted during this window
            if f_d and t_d:
                matches_date = False
                if adm_dt:
                    adm_naive = adm_dt.replace(tzinfo=None) if hasattr(adm_dt, "tzinfo") and adm_dt.tzinfo else adm_dt
                    start_naive = datetime.combine(f_d, datetime.min.time())
                    end_naive = datetime.combine(t_d, datetime.max.time())
                    if start_naive <= adm_naive <= end_naive:
                        matches_date = True
                if not matches_date and dis_dt:
                    dis_naive = dis_dt.replace(tzinfo=None) if hasattr(dis_dt, "tzinfo") and dis_dt.tzinfo else dis_dt
                    start_naive = datetime.combine(f_d, datetime.min.time())
                    end_naive = datetime.combine(t_d, datetime.max.time())
                    if start_naive <= dis_naive <= end_naive:
                        matches_date = True
                if not matches_date:
                    continue

            # Status Filter
            if status_filter in ["admitted", "active"] and is_discharged:
                continue
            if status_filter == "discharged" and not is_discharged:
                continue

            # Length of Stay (days)
            no_of_days = 0
            if adm_dt:
                end_for_calc = dis_dt or now
                adm_naive = adm_dt.replace(tzinfo=None) if hasattr(adm_dt, "tzinfo") and adm_dt.tzinfo else adm_dt
                end_naive = end_for_calc.replace(tzinfo=None) if hasattr(end_for_calc, "tzinfo") and end_for_calc.tzinfo else end_for_calc
                diff = (end_naive - adm_naive).days
                no_of_days = max(1, diff) if is_discharged else max(0, diff)

            # Advance Collections
            adv_list = adm.get("advance_payments") or []
            total_advance = sum(
                clean_num(a.get("advance_amount") or a.get("ip_advance") or 0.0)
                for a in adv_list if a.get("is_advanceActive", True)
            )

            # Discharge Bill Financials
            gross_bill = 0.0
            net_paid = 0.0
            if dbill:
                gross_bill = clean_num(dbill.get("total_amount") or dbill.get("gross_amount") or 0.0)
                net_paid = clean_num(dbill.get("net_amount") or dbill.get("net_paid") or 0.0)

            # Company / Insurance Resolution
            raw_comp = adm.get("company_code") or adm.get("insurance_company") or adm.get("company_name") or adm.get("customer_type") or "Cash / Self"
            resolved_comp = ins_map.get(str(raw_comp).strip()) or adm.get("insurance_company") or adm.get("company_name") or str(raw_comp).strip()
            if not resolved_comp or str(resolved_comp).lower() in ["new", "cash", "self", "none", "nan"]:
                resolved_comp = "Cash / Self"
            
            distinct_companies.add(resolved_comp)

            # Company filter
            if company_filter and company_filter.lower() not in ["all", "all companies", "all types"]:
                cf = company_filter.strip().lower()
                rf = resolved_comp.strip().lower()
                if cf not in rf:
                    continue

            # Doctor Name Resolution
            c_doc = str(adm.get("consultingDoctor") or "").strip()
            a_doc = str(adm.get("admittingDoctor") or "").strip()
            doc_name = doctor_map.get(c_doc) or doctor_map.get(a_doc) or c_doc or a_doc or "Dr. Duty"

            # Search Query Filter
            if search_query:
                haystack = f"{ip} {uhid} {pat_name} {room_str} {resolved_comp} {doc_name}".lower()
                if search_query not in haystack:
                    continue

            records.append({
                "ip_number": ip,
                "room": room_str,
                "uhid": uhid,
                "patient_name": pat_name,
                "doctor_name": doc_name,
                "admitting_date": format_ist_datetime(adm_dt) if adm_dt else "-",
                "admitting_date_iso": adm_dt.isoformat() if adm_dt else "",
                "discharge_date": format_ist_datetime(dis_dt) if dis_dt else "Still Admitted",
                "discharge_date_iso": dis_dt.isoformat() if dis_dt else "",
                "is_discharged": is_discharged,
                "ward_status": "Discharged" if is_discharged else "Admitted",
                "no_of_days": no_of_days,
                "advance": round(total_advance, 2),
                "gross_bill": round(gross_bill, 2),
                "net_paid": round(net_paid, 2),
                "company_name": resolved_comp
            })

        # Sort strictly by IPNUMBER
        records.sort(key=lambda r: _ip_sort_key(r["ip_number"]), reverse=(sort_order == "desc"))

        # Assign 1-based sequential Sl-No
        for idx, rec in enumerate(records, 1):
            rec["sl_no"] = idx

        # Calculate summary KPIs
        total_inpatients = len(records)
        active_count = sum(1 for r in records if not r["is_discharged"])
        discharged_count = sum(1 for r in records if r["is_discharged"])
        total_adv = round(sum(r["advance"] for r in records), 2)
        total_gross = round(sum(r["gross_bill"] for r in records), 2)
        total_net = round(sum(r["net_paid"] for r in records), 2)
        avg_days = round(sum(r["no_of_days"] for r in records) / total_inpatients, 1) if total_inpatients > 0 else 0

        summary = {
            "total_inpatients": total_inpatients,
            "active_admissions": active_count,
            "discharged_count": discharged_count,
            "total_advance": total_adv,
            "total_gross": total_gross,
            "total_net_paid": total_net,
            "avg_length_of_stay": avg_days
        }

        return Response({
            "success": True,
            "report_title": "Admission vs Discharge Report",
            "date_range": {
                "from_date": f_d.isoformat() if f_d else "",
                "to_date": t_d.isoformat() if t_d else "",
                "start_date": f_d.isoformat() if f_d else "",
                "end_date": t_d.isoformat() if t_d else ""
            },
            "count": len(records),
            "summary": summary,
            "companies": sorted(list(distinct_companies)),
            "data": records
        }, status=status.HTTP_200_OK)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if client:
            client.close()
