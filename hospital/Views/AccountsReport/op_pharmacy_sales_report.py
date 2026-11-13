import os
import re
import json
from datetime import datetime, date
from pymongo import MongoClient

from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status

from pyauth.auth import HasRoleAndDataPermission


def to_float(val, default=0.0):
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    if hasattr(val, "to_decimal"):
        try:
            return float(val.to_decimal())
        except Exception:
            return default
    try:
        clean = re.sub(r"[^0-9.\-]", "", str(val))
        return float(clean) if clean else default
    except Exception:
        return default


def parse_date(date_val):
    if not date_val:
        return None
    if isinstance(date_val, datetime):
        return date_val
    if hasattr(date_val, "year") and hasattr(date_val, "month") and hasattr(date_val, "day"):
        return datetime(date_val.year, date_val.month, date_val.day)

    s = str(date_val).strip()
    if not s:
        return None

    for fmt in (
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%d/%m/%Y",
        "%d-%m-%Y",
    ):
        try:
            return datetime.strptime(s[: len(fmt)], fmt)
        except Exception:
            pass

    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def format_date_str(dt):
    if not dt:
        return ""
    if isinstance(dt, datetime):
        return dt.strftime("%Y-%m-%d")
    parsed = parse_date(dt)
    return parsed.strftime("%Y-%m-%d") if parsed else str(dt)[:10]


def get_op_pharmacy_sales_report_data(from_date_param=None, to_date_param=None, outlet_code_filter=None, tax_rate_filter=None, search_query=None):
    """
    Computes OP Pharmacy Sales GST Register (GSTR-1 Format) data:
      1. B2B Invoices (Invoice No = Bill No, Customer Name, GSTIN No, Net Value, Taxable, CGST, SGST)
      2. HSN Wise Summary (Medicine HSN breakdown, quantities, tax rates, tax values)
      3. Document Summary (Serial number range from/to, total count, cancelled, net issued)
    """
    now = timezone.now()
    if not from_date_param:
        dt_from = datetime(now.year, now.month, 1, 0, 0, 0)
    else:
        p_from = parse_date(from_date_param)
        dt_from = datetime(p_from.year, p_from.month, p_from.day, 0, 0, 0) if p_from else datetime(now.year, now.month, 1)

    if not to_date_param:
        dt_to = datetime(now.year, now.month, now.day, 23, 59, 59, 999999)
    else:
        p_to = parse_date(to_date_param)
        dt_to = datetime(p_to.year, p_to.month, p_to.day, 23, 59, 59, 999999) if p_to else datetime(now.year, now.month, now.day, 23, 59, 59)

    client = MongoClient(os.getenv("GLOBAL_DB_HOST"), serverSelectionTimeoutMS=5000)
    hms_db = client["HMS"]

    # ── 1. QUERY BILLS ──────────────────────────────────────────────────────
    base_query = {
        "$or": [
            {"bill_date": {"$gte": dt_from, "$lte": dt_to}},
            {"created_date": {"$gte": dt_from, "$lte": dt_to}},
            {"bill_date": {"$gte": dt_from.strftime("%Y-%m-%d"), "$lte": dt_to.strftime("%Y-%m-%d")}},
            {"created_date": {"$gte": dt_from.strftime("%Y-%m-%d"), "$lte": dt_to.strftime("%Y-%m-%d")}},
        ]
    }

    # Filter by OP Pharmacy outlet
    if outlet_code_filter and str(outlet_code_filter).lower() != "all":
        base_query["outlet_code"] = outlet_code_filter
    else:
        base_query["$and"] = [
            {
                "$or": [
                    {"outlet_code": "OLET002"},
                    {"outlet_code": {"$exists": False}},
                    {"outlet_code": None},
                    {"inpatient_number": {"$in": [None, "", "OP"]}},
                ]
            }
        ]

    raw_bills = list(hms_db["hospital_pharmacybilling"].find(base_query).sort("bill_date", -1))

    if not raw_bills and not from_date_param and not to_date_param:
        fallback_q = {
            "$or": [
                {"outlet_code": "OLET002"},
                {"inpatient_number": {"$in": [None, "", "OP"]}}
            ]
        }
        raw_bills = list(hms_db["hospital_pharmacybilling"].find(fallback_q).sort("bill_date", -1).limit(500))

    # ── 2. PRE-CACHE PATIENTS & ITEMS ───────────────────────────────────────
    uhids = set()
    item_ids = set()
    for b in raw_bills:
        uhid = b.get("uhid")
        if uhid:
            uhids.add(str(uhid).strip())
        for m in (b.get("medicine_particulars") or []):
            if isinstance(m, dict) and m.get("item_id"):
                try:
                    item_ids.add(int(m["item_id"]))
                except (ValueError, TypeError):
                    pass

    patient_map = {}
    if uhids:
        for p in hms_db["hospital_patient"].find(
            {"uhid": {"$in": list(uhids)}},
            {"uhid": 1, "firstName": 1, "lastName": 1, "patient_name": 1, "name": 1, "gstin": 1, "gst_number": 1}
        ):
            u = str(p.get("uhid") or "").strip()
            fn = (p.get("firstName") or "").strip()
            ln = (p.get("lastName") or "").strip()
            full_name = f"{fn} {ln}".strip() or p.get("patient_name") or p.get("name") or ""
            gstin = (p.get("gstin") or p.get("gst_number") or "").strip()
            patient_map[u] = {
                "name": full_name,
                "gstin": gstin if gstin else "-"
            }

    stock_rate_map = {}
    if item_ids:
        for s in hms_db["hospital_pharmacystock"].find(
            {"item_id": {"$in": list(item_ids)}},
            {"item_id": 1, "batch_number": 1, "CGST_Percentage": 1, "SGST_Percentage": 1}
        ):
            k = (str(s.get("item_id")), str(s.get("batch_number") or ""))
            if k not in stock_rate_map:
                stock_rate_map[k] = (
                    to_float(s.get("CGST_Percentage")),
                    to_float(s.get("SGST_Percentage"))
                )

    item_meta_map = {}
    if item_ids:
        for i in hms_db["hospital_pharmacyitem"].find(
            {"item_id": {"$in": list(item_ids)}},
            {"item_id": 1, "item_name": 1, "hsn": 1, "hsn_code": 1, "category": 1}
        ):
            iid = i.get("item_id")
            item_meta_map[iid] = {
                "name": i.get("item_name") or f"Item #{iid}",
                "hsn": (i.get("hsn") or i.get("hsn_code") or "").strip() or "30049099"
            }

    # ── 3. PROCESS DATA ─────────────────────────────────────────────────────
    b2b_list = []
    hsn_map = {}
    docs_summary = {
        "particulars": "Invoices for outward supplies (OP Pharmacy Sales)",
        "min_no": None,
        "max_no": None,
        "total_count": 0,
        "cancelled": 0,
    }

    min_bill_num = None
    max_bill_num = None

    total_invoices_count = 0
    total_sales_value = 0.0
    total_taxable_value = 0.0
    total_cgst_value = 0.0
    total_sgst_value = 0.0
    total_igst_value = 0.0

    sq = (search_query or "").strip().lower()

    for b in raw_bills:
        b_date_raw = b.get("bill_date") or b.get("created_date")
        parsed_dt = parse_date(b_date_raw)
        if parsed_dt:
            if parsed_dt < dt_from or parsed_dt > dt_to:
                continue

        bill_no = str(b.get("bill_no") or b.get("Bill_id") or "").strip()
        if not bill_no:
            continue

        docs_summary["total_count"] += 1
        if not min_bill_num or bill_no < min_bill_num:
            min_bill_num = bill_no
        if not max_bill_num or bill_no > max_bill_num:
            max_bill_num = bill_no

        b_status = str(b.get("billing_status") or "").lower()
        is_cancelled = bool(b.get("is_deleted")) or b_status in ("cancelled", "rejected")
        if is_cancelled:
            docs_summary["cancelled"] += 1
            continue

        uhid = str(b.get("uhid") or "").strip()
        pat_info = patient_map.get(uhid, {})
        customer_name = pat_info.get("name") or (b.get("patientname") or b.get("patient_name") or "OP Walk-in Customer").strip()
        gstin = pat_info.get("gstin") or "-"

        invoice_date = format_date_str(parsed_dt or b_date_raw)
        invoice_value = to_float(b.get("net_amount") or b.get("total_amount") or 0.0)

        if sq:
            combined_text = f"{bill_no} {customer_name} {gstin} {uhid}".lower()
            if sq not in combined_text:
                continue

        total_invoices_count += 1
        total_sales_value += invoice_value

        meds = b.get("medicine_particulars") or []
        if isinstance(meds, str):
            try:
                meds = json.loads(meds)
            except Exception:
                meds = []

        rate_buckets = {}
        if isinstance(meds, list) and meds:
            for itm in meds:
                if not isinstance(itm, dict):
                    continue
                if itm.get("is_deleted"):
                    continue

                iid = itm.get("item_id")
                batch = str(itm.get("batch_number") or "").strip()
                qty = to_float(itm.get("qty") or itm.get("quantity") or 1.0)
                price = to_float(itm.get("calculated_price") or (to_float(itm.get("price") or 0.0) * qty))
                if price <= 0:
                    continue

                cgst_pct = to_float(itm.get("CGST_Percentage") or itm.get("cgst_rate"))
                sgst_pct = to_float(itm.get("SGST_Percentage") or itm.get("sgst_rate"))
                if cgst_pct == 0.0 and sgst_pct == 0.0:
                    stock_rates = stock_rate_map.get((str(iid), batch))
                    if stock_rates:
                        cgst_pct, sgst_pct = stock_rates

                total_rate = round(cgst_pct + sgst_pct, 2)
                if total_rate <= 0:
                    taxable = price
                    cgst_amt = 0.0
                    sgst_amt = 0.0
                else:
                    taxable = round(price / (1.0 + total_rate / 100.0), 2)
                    cgst_amt = round(taxable * (cgst_pct / 100.0), 2)
                    sgst_amt = round(taxable * (sgst_pct / 100.0), 2)

                if total_rate not in rate_buckets:
                    rate_buckets[total_rate] = {
                        "taxable": 0.0,
                        "cgst": 0.0,
                        "sgst": 0.0,
                        "igst": 0.0,
                        "cess": 0.0,
                    }
                rate_buckets[total_rate]["taxable"] += taxable
                rate_buckets[total_rate]["cgst"] += cgst_amt
                rate_buckets[total_rate]["sgst"] += sgst_amt

                meta = item_meta_map.get(iid, {})
                hsn_code = meta.get("hsn") or str(itm.get("hsn") or itm.get("hsn_code") or "").strip() or "30049099"
                itm_desc = str(itm.get("item_name") or meta.get("name") or "MEDICINE").strip().upper()
                uom = "Numbers"

                hsn_key = (hsn_code, total_rate, uom, itm_desc)
                if hsn_key not in hsn_map:
                    hsn_map[hsn_key] = {
                        "description": itm_desc,
                        "hsn": hsn_code,
                        "uom": uom,
                        "total_quantity": 0.0,
                        "tax_rate": total_rate,
                        "taxable_value": 0.0,
                        "igst": 0.0,
                        "cgst": 0.0,
                        "sgst": 0.0,
                        "cess": 0.0,
                    }
                hsn_map[hsn_key]["total_quantity"] += qty
                hsn_map[hsn_key]["taxable_value"] += taxable
                hsn_map[hsn_key]["cgst"] += cgst_amt
                hsn_map[hsn_key]["sgst"] += sgst_amt

        if not rate_buckets:
            rate_buckets[0.0] = {
                "taxable": invoice_value,
                "cgst": 0.0,
                "sgst": 0.0,
                "igst": 0.0,
                "cess": 0.0,
            }

        for rate, bkt in rate_buckets.items():
            if tax_rate_filter and str(tax_rate_filter).lower() != "all":
                try:
                    if abs(float(tax_rate_filter) - float(rate)) > 0.01:
                        continue
                except ValueError:
                    pass

            b2b_list.append({
                "id": f"OP-{str(b.get('_id') or bill_no)}-{rate}",
                "invoice_no": bill_no,
                "bill_no": bill_no,
                "customer_name": customer_name,
                "gstin": gstin,
                "invoice_date": invoice_date,
                "invoice_value": invoice_value,
                "tax_rate": rate,
                "taxable_value": round(bkt["taxable"], 2),
                "igst": round(bkt["igst"], 2) if bkt["igst"] else None,
                "cgst": round(bkt["cgst"], 2),
                "sgst": round(bkt["sgst"], 2),
                "cess": round(bkt["cess"], 2) if bkt["cess"] else None,
                "state_of_supply": "Tamil Nadu",
                "reverse_charge": "N",
            })

            total_taxable_value += bkt["taxable"]
            total_cgst_value += bkt["cgst"]
            total_sgst_value += bkt["sgst"]

    b2b_list.sort(key=lambda x: str(x.get("invoice_date") or ""), reverse=True)

    hsn_list = list(hsn_map.values())
    hsn_list.sort(key=lambda x: (x.get("hsn") or "", x.get("tax_rate") or 0))

    docs_summary["sl_no_from"] = min_bill_num or "—"
    docs_summary["sl_no_to"] = max_bill_num or "—"
    docs_summary["net_issued"] = max(0, docs_summary["total_count"] - docs_summary["cancelled"])

    summary = {
        "total_invoices": total_invoices_count,
        "total_sales_value": round(total_sales_value, 2),
        "total_taxable": round(total_taxable_value, 2),
        "total_cgst": round(total_cgst_value, 2),
        "total_sgst": round(total_sgst_value, 2),
        "total_igst": round(total_igst_value, 2),
        "total_tax": round(total_cgst_value + total_sgst_value + total_igst_value, 2),
    }

    return {
        "sales_data": b2b_list,
        "invoices_data": b2b_list,
        "b2b_data": b2b_list,
        "hsn_data": hsn_list,
        "docs_data": [docs_summary],
        "summary": summary
    }


@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def op_pharmacy_sales_report_api(request):
    """
    HTTP Endpoint for OP Pharmacy Sales GST Register (GSTR-1 Format)
    """
    try:
        from_date_param = request.GET.get("from_date")
        to_date_param = request.GET.get("to_date")
        outlet_code_filter = (request.GET.get("outlet_code") or request.GET.get("outlet") or "").strip()
        tax_rate_filter = request.GET.get("tax_rate")
        search_query = (request.GET.get("search") or "").strip().lower()

        data = get_op_pharmacy_sales_report_data(
            from_date_param=from_date_param,
            to_date_param=to_date_param,
            outlet_code_filter=outlet_code_filter,
            tax_rate_filter=tax_rate_filter,
            search_query=search_query
        )

        return Response(
            {
                "success": True,
                "data": data,
                "summary": data.get("summary", {}),
                "sales_data": data.get("sales_data", []),
                "invoices_data": data.get("invoices_data", []),
                "b2b_data": data.get("b2b_data", []),
                "hsn_data": data.get("hsn_data", []),
                "docs_data": data.get("docs_data", []),
            },
            status=status.HTTP_200_OK,
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
