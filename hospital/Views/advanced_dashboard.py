from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone
from django.utils.timezone import make_aware, is_aware
from datetime import datetime, timedelta
import calendar
from pymongo import MongoClient
import os
import pytz

# Setup Mongo Client
MONGO_URI = os.getenv("GLOBAL_DB_HOST") or "mongodb://localhost:27017/HMS"
client = MongoClient(MONGO_URI)
mongo_db = client["HMS"]
global_db = client["Global"]
profile_collection = global_db["backend_diagnostics_profile"]

SD_REGEX = {"ipNumber": {"$regex": "^SD", "$options": "i"}}
NON_SD_REGEX = {"ipNumber": {"$not": {"$regex": "^SD", "$options": "i"}}}


def _is_sd_ip(doc):
    return str((doc or {}).get("ipNumber") or "").strip().upper().startswith("SD")


def _resolve_active_room(doc):
    shifts = doc.get("roomShitingDetails") or []
    if isinstance(shifts, list):
        for s in reversed(shifts):
            if isinstance(s, dict) and s.get("is_roomActive"):
                return (
                    str(s.get("newRoomNo") or s.get("roomNo") or "").strip(),
                    str(s.get("newBedNo") or s.get("bedNo") or "").strip(),
                    str(s.get("newRoomCategory") or s.get("roomCategory") or s.get("room_category") or "").strip(),
                )
    rd = doc.get("room_details") or []
    if isinstance(rd, list):
        for r in reversed(rd):
            if isinstance(r, dict) and r.get("is_roomActive"):
                return (
                    str(r.get("roomNo") or "").strip(),
                    str(r.get("bedNo") or "").strip(),
                    str(r.get("room_category") or r.get("roomCategory") or "").strip(),
                )
        if rd and isinstance(rd[-1], dict):
            last_r = rd[-1]
            return (
                str(last_r.get("roomNo") or "").strip(),
                str(last_r.get("bedNo") or "").strip(),
                str(last_r.get("room_category") or last_r.get("roomCategory") or "").strip(),
            )
    return (
        str(doc.get("roomNo") or "").strip(),
        str(doc.get("bedNo") or "").strip(),
        str(doc.get("room_category") or doc.get("roomCategory") or "").strip(),
    )


def _classify_occupancy_room(room_no):
    rn = str(room_no or "").strip().upper()
    if rn == "CHEMO" or "CHEMO" in rn:
        return "chemo", "Chemo"
    if rn in ("DIALYSIS", "DLS") or "DIALYSIS" in rn:
        return "dialysis", "Dialysis"
    if rn == "DAYCARE" or "DAYCARE" in rn:
        return "daycare", "Daycare"
    return "normal_room", "Normal Room"


def ensure_aware(dt):
    """Ensures a datetime object is timezone-aware (UTC)."""
    if dt is None:
        return None
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not is_aware(dt):
        return make_aware(dt, pytz.UTC)
    return dt.astimezone(pytz.UTC)


def safe_sum_agg(collection, match_stage, field_expr):
    """Safely aggregates a sum using MongoDB $convert to handle Decimal128/string/null."""
    pipeline = [
        {"$match": match_stage},
        {
            "$group": {
                "_id": None,
                "total": {
                    "$sum": {
                        "$convert": {
                            "input": field_expr,
                            "to": "double",
                            "onError": 0.0,
                            "onNull": 0.0
                        }
                    }
                }
            }
        }
    ]
    res = list(collection.aggregate(pipeline))
    return float(res[0]["total"]) if res else 0.0


def resolve_date_range(request, tz):
    now = timezone.now().astimezone(tz)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)

    period = (request.GET.get("period") or "").strip().lower()
    from_str = (request.GET.get("from_date") or "").strip()
    to_str = (request.GET.get("to_date") or "").strip()

    if period == "yesterday":
        s = today_start - timedelta(days=1)
        e = today_end - timedelta(days=1)
        return s, e, "yesterday"
    elif period == "week":
        s = today_start - timedelta(days=6)
        e = today_end
        return s, e, "week"
    elif period == "month":
        s = today_start.replace(day=1)
        e = today_end
        return s, e, "month"
    elif from_str and to_str:
        try:
            f_dt = datetime.strptime(from_str, "%Y-%m-%d")
            t_dt = datetime.strptime(to_str, "%Y-%m-%d")
            s = tz.localize(f_dt.replace(hour=0, minute=0, second=0, microsecond=0))
            e = tz.localize(t_dt.replace(hour=23, minute=59, second=59, microsecond=999999))
            return s, e, (period or "custom")
        except ValueError:
            pass

    return today_start, today_end, (period or "today")


@api_view(["GET"])
def advanced_dashboard_stats(request):
    try:
        tz = pytz.timezone("Asia/Kolkata")
        now = timezone.now().astimezone(tz)

        include_lifetime = (
            str(request.GET.get("include_lifetime") or "false").strip().lower() in ("true", "1", "yes")
        )

        # Resolve date filter range (defaults to Today)
        range_start_ist, range_end_ist, resolved_period = resolve_date_range(request, tz)
        range_start_utc = range_start_ist.astimezone(pytz.UTC)
        range_end_utc = range_end_ist.astimezone(pytz.UTC)
        range_start_str = range_start_ist.strftime("%Y-%m-%d")
        range_end_str = range_end_ist.strftime("%Y-%m-%d")

        # Resolve month/year for trend charts
        month = request.GET.get("month")
        year = request.GET.get("year")
        if month and year:
            month = int(month)
            year = int(year)
        else:
            month = range_end_ist.month
            year = range_end_ist.year

        # 1. Operational Volume KPIs (Separating Normal IP vs Day Care IP 'SD' & Active Room Categories)
        active_occupancy_docs = list(mongo_db["hospital_admission"].find(
            {
                "is_admitted": True,
                "is_discharged": {"$ne": True},
                "is_cancelled": {"$ne": True}
            },
            {
                "ipNumber": 1,
                "uhid": 1,
                "admissionDateTime": 1,
                "admittingDoctor": 1,
                "consultingDoctor": 1,
                "room_details": 1,
                "roomShitingDetails": 1,
                "roomNo": 1,
                "bedNo": 1,
                "room_category": 1,
                "roomCategory": 1,
                "ward_status": 1,
                "customer_type": 1,
                "customerType": 1,
                "_id": 0
            }
        ))
        current_daycare_ip = sum(1 for a in active_occupancy_docs if _is_sd_ip(a))
        current_normal_ip = len(active_occupancy_docs) - current_daycare_ip
        current_ip = len(active_occupancy_docs)

        # Build current occupancy breakdown: Normal Room vs Chemo vs Dialysis vs Daycare
        active_uhids = list({str(a.get("uhid") or "").strip() for a in active_occupancy_docs if a.get("uhid")})
        active_patient_map = {}
        if active_uhids:
            for pt in mongo_db["hospital_patient"].find(
                {"uhid": {"$in": active_uhids}},
                {"uhid": 1, "salutation": 1, "firstName": 1, "middleName": 1, "lastName": 1, "mobilePhone": 1, "_id": 0}
            ):
                u = str(pt.get("uhid") or "").strip()
                if u:
                    full_name = " ".join(
                        str(pt.get(k) or "").strip()
                        for k in ("salutation", "firstName", "middleName", "lastName")
                        if str(pt.get(k) or "").strip()
                    )
                    active_patient_map[u] = {
                        "name": full_name or u,
                        "mobile": str(pt.get("mobilePhone") or "").strip()
                    }

        occ_doc_ids = list({
            str(a.get("consultingDoctor") or a.get("admittingDoctor") or "").strip()
            for a in active_occupancy_docs
            if (a.get("consultingDoctor") or a.get("admittingDoctor"))
        })
        occ_doc_name_map = {}
        if occ_doc_ids:
            for dprof in profile_collection.find(
                {"employeeId": {"$in": occ_doc_ids}},
                {"employeeId": 1, "employeeName": 1, "_id": 0}
            ):
                eid = str(dprof.get("employeeId") or "").strip()
                ename = str(dprof.get("employeeName") or "").strip()
                if eid and ename:
                    occ_doc_name_map[eid] = ename

        occ_counts = {"normal_room": 0, "chemo": 0, "dialysis": 0, "daycare": 0}
        occ_patients = []
        for a in active_occupancy_docs:
            ip_num = str(a.get("ipNumber") or "").strip()
            uhid_val = str(a.get("uhid") or "").strip()
            room_no, bed_no, room_cat = _resolve_active_room(a)
            cat_key, cat_label = _classify_occupancy_room(room_no)
            occ_counts[cat_key] += 1

            raw_doc = str(a.get("consultingDoctor") or a.get("admittingDoctor") or "").strip()
            doc_name = occ_doc_name_map.get(raw_doc, raw_doc)
            pt_info = active_patient_map.get(uhid_val, {})

            adm_dt = ensure_aware(a.get("admissionDateTime"))
            adm_ist_str = adm_dt.astimezone(tz).strftime("%d-%m-%Y %I:%M %p") if adm_dt else ""
            adm_sort_ts = adm_dt.timestamp() if adm_dt else 0

            occ_patients.append({
                "ipNumber": ip_num,
                "uhid": uhid_val,
                "patientName": pt_info.get("name") or uhid_val,
                "mobile": pt_info.get("mobile") or "",
                "doctor": doc_name or "-",
                "roomNo": room_no or "-",
                "bedNo": bed_no or "-",
                "roomCategory": room_cat or "-",
                "category": cat_key,
                "categoryLabel": cat_label,
                "isDayCareIp": _is_sd_ip(a),
                "admissionDateTime": adm_ist_str,
                "wardStatus": str(a.get("ward_status") or "").strip() or "Admitted",
                "customerType": str(a.get("customerType") or a.get("customer_type") or "General").strip(),
                "_sort_ts": adm_sort_ts
            })

        occ_patients.sort(key=lambda x: x["_sort_ts"], reverse=True)
        for row in occ_patients:
            row.pop("_sort_ts", None)

        occupancy_breakdown = {
            "total": len(occ_patients),
            "counts": occ_counts,
            "patients": occ_patients
        }

        # Period Admissions (All non-cancelled admissions including same-day discharges)
        period_adm_docs = list(mongo_db["hospital_admission"].find(
            {
                "admissionDateTime": {"$gte": range_start_utc, "$lte": range_end_utc},
                "is_cancelled": {"$ne": True}
            },
            {"ipNumber": 1, "_id": 0}
        ))
        period_daycare_ip = sum(1 for a in period_adm_docs if _is_sd_ip(a))
        period_normal_ip = len(period_adm_docs) - period_daycare_ip
        period_ip = len(period_adm_docs)

        period_op = mongo_db["hospital_billing"].count_documents({
            "billed_date": {"$gte": range_start_utc, "$lte": range_end_utc},
            "is_active": {"$ne": False},
            "payment_status": {"$ne": "Cancelled"}
        })

        def _get_billed_discharge_ips(w_start_utc=None, w_end_utc=None, w_start_str=None, w_end_str=None):
            q = {
                "status": {"$in": ["Billed", "Paid"]},
                "is_cancelled": {"$ne": True}
            }
            if w_start_utc is not None and w_end_utc is not None:
                q["$or"] = [
                    {"bill_date": {"$gte": w_start_utc, "$lte": w_end_utc}},
                    {"bill_date": {"$gte": w_start_str, "$lte": f"{w_end_str}\uffff"}}
                ]
            cursor = mongo_db["hospital_dischargebilling"].find(q, {"ip_number": 1, "ipNumber": 1, "_id": 0})
            return {
                str(d.get("ip_number") or d.get("ipNumber") or "").strip().upper()
                for d in cursor
                if (d.get("ip_number") or d.get("ipNumber"))
            }

        period_dis_ips = _get_billed_discharge_ips(
            range_start_utc, range_end_utc, range_start_str, range_end_str
        )
        period_daycare_discharge = sum(1 for ip in period_dis_ips if ip.startswith("SD"))
        period_normal_discharge = len(period_dis_ips) - period_daycare_discharge
        period_discharge = len(period_dis_ips)

        # 2. Selected Period Revenue Aggregations (All 4 Streams)
        period_op_income = safe_sum_agg(
            mongo_db["hospital_billing"],
            {"payment_status": "Paid", "billed_date": {"$gte": range_start_utc, "$lte": range_end_utc}},
            "$total_fees"
        )

        period_discharge_income = safe_sum_agg(
            mongo_db["hospital_dischargebilling"],
            {
                "status": "Billed",
                "$or": [
                    {"bill_date": {"$gte": range_start_utc, "$lte": range_end_utc}},
                    {"bill_date": {"$gte": range_start_str, "$lte": range_end_str}}
                ]
            },
            "$net_amount"
        )

        period_advance_income = 0.0
        adv_docs = list(mongo_db["hospital_admission"].find(
            {"advance_payments.date": {"$gte": range_start_str, "$lte": range_end_str}},
            {"advance_payments": 1}
        ))
        for doc in adv_docs:
            for adv in doc.get("advance_payments", []):
                adv_date = str(adv.get("date") or "")[:10]
                if (
                    range_start_str <= adv_date <= range_end_str
                    and adv.get("is_advanceActive", True)
                    and adv.get("status") == "Paid"
                ):
                    try:
                        period_advance_income += float(adv.get("advance_amount") or 0)
                    except (ValueError, TypeError):
                        pass

        period_ip_income = period_discharge_income + period_advance_income

        period_pharm_income = safe_sum_agg(
            mongo_db["hospital_pharmacybilling"],
            {"billing_status": "Paid", "bill_date": {"$gte": range_start_utc, "$lte": range_end_utc}},
            "$net_amount"
        )

        period_inv_income = safe_sum_agg(
            mongo_db["hospital_investbilling"],
            {
                "is_active": True,
                "paymentStatus": {"$in": ["Paid", "Completed"]},
                "investBillDate": {"$gte": range_start_utc, "$lte": range_end_utc}
            },
            {"$ifNull": ["$finalPrice", "$total"]}
        )

        period_total_revenue = (
            period_op_income +
            period_ip_income +
            period_pharm_income +
            period_inv_income
        )

        # 3. Optional Lifetime Revenue & Counts (ONLY computed when include_lifetime=true)
        lifetime_data = None
        total_op = 0
        total_ip_lifetime = 0
        total_normal_ip_lifetime = 0
        total_daycare_ip_lifetime = 0
        total_discharge_lifetime = 0
        total_normal_discharge_lifetime = 0
        total_daycare_discharge_lifetime = 0
        total_income_lifetime = 0.0

        if include_lifetime:
            total_op = mongo_db["hospital_patient"].count_documents({})
            total_daycare_ip_lifetime = mongo_db["hospital_admission"].count_documents({
                "is_cancelled": {"$ne": True},
                **SD_REGEX
            })
            total_normal_ip_lifetime = mongo_db["hospital_admission"].count_documents({
                "is_cancelled": {"$ne": True},
                **NON_SD_REGEX
            })
            total_ip_lifetime = total_normal_ip_lifetime + total_daycare_ip_lifetime

            lifetime_dis_ips = _get_billed_discharge_ips()
            total_daycare_discharge_lifetime = sum(1 for ip in lifetime_dis_ips if ip.startswith("SD"))
            total_normal_discharge_lifetime = len(lifetime_dis_ips) - total_daycare_discharge_lifetime
            total_discharge_lifetime = len(lifetime_dis_ips)

            op_income_lifetime = safe_sum_agg(
                mongo_db["hospital_billing"],
                {"payment_status": "Paid"},
                "$total_fees"
            )
            ip_income_lifetime = safe_sum_agg(
                mongo_db["hospital_dischargebilling"],
                {"status": "Billed"},
                "$net_amount"
            )
            pharm_income_lifetime = safe_sum_agg(
                mongo_db["hospital_pharmacybilling"],
                {"billing_status": "Paid"},
                "$net_amount"
            )
            inv_income_lifetime = safe_sum_agg(
                mongo_db["hospital_investbilling"],
                {"is_active": True, "paymentStatus": {"$in": ["Paid", "Completed"]}},
                {"$ifNull": ["$finalPrice", "$total"]}
            )

            total_income_lifetime = (
                op_income_lifetime +
                ip_income_lifetime +
                pharm_income_lifetime +
                inv_income_lifetime
            )

            lifetime_data = {
                "total": round(total_income_lifetime, 2),
                "op": round(op_income_lifetime, 2),
                "ip": round(ip_income_lifetime, 2),
                "pharmacy": round(pharm_income_lifetime, 2),
                "investigation": round(inv_income_lifetime, 2),
                "total_op_count": total_op,
                "total_ip_count": total_ip_lifetime,
                "total_normal_ip_count": total_normal_ip_lifetime,
                "total_daycare_ip_count": total_daycare_ip_lifetime,
                "total_discharge_count": total_discharge_lifetime,
                "total_normal_discharge_count": total_normal_discharge_lifetime,
                "total_daycare_discharge_count": total_daycare_discharge_lifetime
            }

        revenue_breakdown = {
            "lifetime_enabled": include_lifetime,
            "lifetime": lifetime_data,
            "today": {
                "total": round(period_total_revenue, 2),
                "op": round(period_op_income, 2),
                "ip": round(period_ip_income, 2),
                "ip_discharge": round(period_discharge_income, 2),
                "ip_advance": round(period_advance_income, 2),
                "pharmacy": round(period_pharm_income, 2),
                "investigation": round(period_inv_income, 2)
            }
        }

        kpis = {
            "total_op": total_op,
            "total_ip": total_ip_lifetime,
            "total_normal_ip": total_normal_ip_lifetime,
            "total_daycare_ip": total_daycare_ip_lifetime,
            "total_discharge": total_discharge_lifetime,
            "current_ip": current_ip,
            "current_normal_ip": current_normal_ip,
            "current_daycare_ip": current_daycare_ip,
            "current_normal_room": occ_counts["normal_room"],
            "current_chemo": occ_counts["chemo"],
            "current_dialysis": occ_counts["dialysis"],
            "current_daycare_room": occ_counts["daycare"],
            "total_income": round(total_income_lifetime, 2),
            "today_revenue": round(period_total_revenue, 2),
            "today_ip": period_ip,
            "today_normal_ip": period_normal_ip,
            "today_daycare_ip": period_daycare_ip,
            "today_op": period_op,
            "today_discharge": period_discharge,
            "today_normal_discharge": period_normal_discharge,
            "today_daycare_discharge": period_daycare_discharge
        }

        # 4. Monthly Stats & Trends (Normal IP vs Day Care IP 'SD' separated)
        num_days = calendar.monthrange(year, month)[1]
        monthly_op_ip = []
        monthly_income_expense = []

        month_start = now.replace(year=year, month=month, day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(pytz.UTC)
        month_end = now.replace(year=year, month=month, day=num_days, hour=23, minute=59, second=59, microsecond=999999).astimezone(pytz.UTC)

        admissions = list(mongo_db["hospital_admission"].find({
            "is_cancelled": {"$ne": True},
            "admissionDateTime": {"$gte": month_start, "$lte": month_end}
        }))

        billings = list(mongo_db["hospital_billing"].find({
            "payment_status": "Paid",
            "billed_date": {"$gte": month_start, "$lte": month_end}
        }))

        pharm_billings = list(mongo_db["hospital_pharmacybilling"].find({
            "billing_status": "Paid",
            "bill_date": {"$gte": month_start, "$lte": month_end}
        }))

        inv_billings = list(mongo_db["hospital_investbilling"].find({
            "is_active": True,
            "paymentStatus": {"$in": ["Paid", "Completed"]},
            "investBillDate": {"$gte": month_start, "$lte": month_end}
        }))

        discharge_billings = list(mongo_db["hospital_dischargebilling"].find({
            "status": "Billed",
            "$or": [
                {"bill_date": {"$gte": month_start, "$lte": month_end}},
                {"bill_date": {"$gte": month_start.strftime("%Y-%m-%d"), "$lte": month_end.strftime("%Y-%m-%d")}}
            ]
        }))

        grns = list(mongo_db["hospital_grn"].find({
            "status": "Approved",
            "date": {"$gte": month_start, "$lte": month_end}
        }))

        for day in range(1, num_days + 1):
            d_start_local = now.replace(year=year, month=month, day=day, hour=0, minute=0, second=0, microsecond=0)
            d_end_local = d_start_local.replace(hour=23, minute=59, second=59, microsecond=999999)

            d_start = d_start_local.astimezone(pytz.UTC)
            d_end = d_end_local.astimezone(pytz.UTC)
            d_str = d_start_local.strftime("%Y-%m-%d")

            day_admissions = [a for a in admissions if a.get("admissionDateTime") and d_start <= ensure_aware(a.get("admissionDateTime")) <= d_end]
            day_billings = [b for b in billings if b.get("billed_date") and d_start <= ensure_aware(b.get("billed_date")) <= d_end]

            d_daycare = sum(1 for a in day_admissions if _is_sd_ip(a))
            d_normal = len(day_admissions) - d_daycare

            monthly_op_ip.append({
                "day": day,
                "OP": len(day_billings),
                "Normal IP": d_normal,
                "Day Care IP": d_daycare,
                "IP": len(day_admissions)
            })

            d_income = sum([float(str(b.get("total_fees") or 0)) for b in day_billings])

            d_discharges = []
            for db in discharge_billings:
                bdt = db.get("bill_date")
                if isinstance(bdt, str) and bdt[:10] == d_str:
                    d_discharges.append(db)
                elif isinstance(bdt, datetime) and d_start <= ensure_aware(bdt) <= d_end:
                    d_discharges.append(db)
            d_income += sum([float(str(db.get("net_amount") or 0)) for db in d_discharges])

            d_pharm = [pb for pb in pharm_billings if pb.get("bill_date") and d_start <= ensure_aware(pb.get("bill_date")) <= d_end]
            d_income += sum([float(str(pb.get("net_amount") or 0)) for pb in d_pharm])

            d_inv = [ib for ib in inv_billings if ib.get("investBillDate") and d_start <= ensure_aware(ib.get("investBillDate")) <= d_end]
            for ib in d_inv:
                try:
                    d_income += float(str(ib.get("finalPrice") or ib.get("total") or 0))
                except (ValueError, TypeError):
                    pass

            d_grns = [g for g in grns if g.get("date") and d_start <= ensure_aware(g.get("date")) <= d_end]
            d_expense = sum([float(str(g.get("net_invoice_amount") or 0)) for g in d_grns])

            monthly_income_expense.append({"day": day, "Income": round(d_income, 2), "Expense": round(d_expense, 2)})

        # 5. Income Payment Method Mix for Selected Date Range
        p_billings = list(mongo_db["hospital_billing"].find({
            "payment_status": "Paid",
            "billed_date": {"$gte": range_start_utc, "$lte": range_end_utc}
        }))
        p_pharm = list(mongo_db["hospital_pharmacybilling"].find({
            "billing_status": "Paid",
            "bill_date": {"$gte": range_start_utc, "$lte": range_end_utc}
        }))
        p_inv = list(mongo_db["hospital_investbilling"].find({
            "is_active": True,
            "paymentStatus": {"$in": ["Paid", "Completed"]},
            "investBillDate": {"$gte": range_start_utc, "$lte": range_end_utc}
        }))

        methods = {}
        for b in p_billings:
            m = b.get("payment_method") or "Cash"
            methods[m] = methods.get(m, 0) + float(str(b.get("total_fees") or 0))
        for pb in p_pharm:
            m = pb.get("payment_mode") or "Cash"
            methods[m] = methods.get(m, 0) + float(str(pb.get("net_amount") or 0))
        for ib in p_inv:
            m = ib.get("paymentMethod") or "Cash"
            try:
                methods[m] = methods.get(m, 0) + float(str(ib.get("finalPrice") or ib.get("total") or 0))
            except (ValueError, TypeError):
                pass
        todays_income_method = [{"method": k, "amount": round(v, 2)} for k, v in methods.items() if v > 0]

        # 6. Doctor Stats (Top 10 Monthly)
        doc_stats = {}
        for a in admissions:
            d = str(a.get("consultingDoctor") or a.get("admittingDoctor") or "").strip()
            if not d: continue
            if d not in doc_stats: doc_stats[d] = {"OP": 0, "IP": 0, "Amount": 0.0}
            doc_stats[d]["IP"] += 1

        for b in billings:
            d = str(b.get("doctor_id") or "").strip()
            if not d: continue
            if d not in doc_stats: doc_stats[d] = {"OP": 0, "IP": 0, "Amount": 0.0}
            doc_stats[d]["OP"] += 1
            doc_stats[d]["Amount"] += float(str(b.get("consulting_fee") or b.get("total_fees") or 0))

        doctor_ids = list(doc_stats.keys())
        doctor_name_map = {}
        if doctor_ids:
            doctor_cursor = profile_collection.find(
                {"employeeId": {"$in": doctor_ids}},
                {"employeeId": 1, "employeeName": 1}
            )
            doctor_name_map = {str(d["employeeId"]): d.get("employeeName", "") for d in doctor_cursor}

        doctor_wise = [
            {"name": doctor_name_map.get(k) or k, "OP": v["OP"], "IP": v["IP"], "Amount": round(v["Amount"], 2)}
            for k, v in doc_stats.items()
        ]
        doctor_wise = sorted(doctor_wise, key=lambda x: x["Amount"], reverse=True)[:10]

        # 7. Bed Occupancy (Separating Normal IP vs Day Care SD vs Vacant)
        total_beds_res = list(mongo_db["hospital_room"].aggregate([{"$group": {"_id": None, "total": {"$sum": "$capacity"}}}]))
        total_beds = total_beds_res[0]["total"] if total_beds_res else 0

        bed_occupancy = [
            {"name": "Normal IP", "value": current_normal_ip},
            {"name": "Day Care (SD)", "value": current_daycare_ip},
            {"name": "Vacant", "value": max(0, total_beds - current_ip)}
        ]

        return Response({
            "period": resolved_period,
            "from_date": range_start_str,
            "to_date": range_end_str,
            "include_lifetime": include_lifetime,
            "kpis": kpis,
            "revenue_breakdown": revenue_breakdown,
            "monthly_op_ip": monthly_op_ip,
            "monthly_income_expense": monthly_income_expense,
            "todays_income_method": todays_income_method,
            "doctor_wise": doctor_wise,
            "bed_occupancy": bed_occupancy,
            "occupancy_breakdown": occupancy_breakdown
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Advanced Dashboard Error: {str(e)}")
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
