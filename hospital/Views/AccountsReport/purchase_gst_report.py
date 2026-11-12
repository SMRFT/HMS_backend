import os
import re
import json
from datetime import datetime, time
from decimal import Decimal
from bson.decimal128 import Decimal128
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
    """
    Parses various date formats (datetime, date, ISO string, DD/MM/YYYY, etc.)
    into a datetime object with timezone or naive.
    """
    if not date_val:
        return None
    if isinstance(date_val, datetime):
        return date_val
    if hasattr(date_val, "year") and hasattr(date_val, "month") and hasattr(date_val, "day"):
        return datetime(date_val.year, date_val.month, date_val.day)

    s = str(date_val).strip()
    if not s:
        return None

    # Try common formats
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
        # ISO fallback
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


def normalize_uom(unit_str):
    if not unit_str:
        return "Numbers"
    u = str(unit_str).strip().lower()
    if any(k in u for k in ["box", "bx"]):
        return "Box"
    if any(k in u for k in ["bottle", "btl"]):
        return "Bottles"
    if any(k in u for k in ["can"]):
        return "Cans"
    if any(k in u for k in ["carton", "ctn"]):
        return "Carton"
    if any(k in u for k in ["bag"]):
        return "Bags"
    if any(k in u for k in ["dozen", "doz"]):
        return "Dozen"
    if any(k in u for k in ["bundle", "bdl"]):
        return "Bundles"
    return "Numbers"


@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def purchase_gst_report_api(request):
    """
    GST Purchase Register (GSTR-1 Format for Purchases)
    Provides:
      1. B2B Purchase Invoices (VELAVAN HOSPITAL NEEDS_GSTR 1_B2B.xlsm)
      2. HSN Wise Summary (VELAVAN HOSPITAL NEEDS_GSTR 1_HSN wise.xlsm)
      3. Document Summary (VELAVAN HOSPITAL NEEDS_GSTR 1_Docs.xlsm)

    Sources:
      - Drug Purchase: hospital_grn & hospital_vendor
      - General Stores: hospital_storesgrn & hospital_generalstorevendor
    """
    try:
        from_date_param = request.GET.get("from_date")
        to_date_param = request.GET.get("to_date")
        source_type = (request.GET.get("source_type") or "all").lower().strip()  # "all" | "drug" | "stores"
        tax_rate_filter = request.GET.get("tax_rate")
        vendor_filter = request.GET.get("vendor_id")
        search_query = (request.GET.get("search") or "").strip().lower()

        now = timezone.now()
        # Default date range: current month 1st to today
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

        # ── 1. PRE-LOAD VENDORS ────────────────────────────────────────────────
        drug_vendors = {}
        for v in hms_db["hospital_vendor"].find({}, {"vendor_id": 1, "name": 1, "gstin": 1, "state": 1, "city": 1}):
            vid = str(v.get("vendor_id") or "").strip()
            if vid:
                drug_vendors[vid] = v

        stores_vendors = {}
        for v in hms_db["hospital_generalstorevendor"].find({}, {"vendor_id": 1, "name": 1, "gstin": 1, "state": 1, "city": 1}):
            vid = str(v.get("vendor_id") or "").strip()
            if vid:
                stores_vendors[vid] = v

        # ── 2. PREPARE AGGREGATION STRUCTURES ─────────────────────────────────
        b2b_list = []
        hsn_map = {}  # key: (hsn, tax_rate, uom, description) -> accumulator
        docs_drug = {
            "particulars": "Invoices for inward supplies (Drug Purchase)",
            "min_no": None,
            "max_no": None,
            "total_count": 0,
            "cancelled": 0,
        }
        docs_stores = {
            "particulars": "Invoices for inward supplies (General Stores)",
            "min_no": None,
            "max_no": None,
            "total_count": 0,
            "cancelled": 0,
        }

        # Date query filter (catches records where invoice_date, date, or created_date falls in range)
        date_query = {
            "$or": [
                {"invoice_date": {"$gte": dt_from, "$lte": dt_to}},
                {"date": {"$gte": dt_from, "$lte": dt_to}},
                {"created_date": {"$gte": dt_from, "$lte": dt_to}},
                # String representations
                {"invoice_date": {"$gte": dt_from.strftime("%Y-%m-%d"), "$lte": dt_to.strftime("%Y-%m-%d")}},
                {"date": {"$gte": dt_from.strftime("%Y-%m-%d"), "$lte": dt_to.strftime("%Y-%m-%d")}},
            ]
        }

        # ── 3. PROCESS DRUG PURCHASE (hospital_grn) ───────────────────────────
        if source_type in ("all", "drug", "pharmacy"):
            drug_records = list(hms_db["hospital_grn"].find(date_query).sort("created_date", -1))
            # Fallback if strict date query missed string/flexible formats
            if not drug_records and not from_date_param and not to_date_param:
                drug_records = list(hms_db["hospital_grn"].find().sort("created_date", -1).limit(500))

            for g in drug_records:
                # Check status
                status_str = str(g.get("status") or "").lower()
                is_cancelled = bool(g.get("is_cancelled")) or status_str in ("cancelled", "rejected")

                raw_date = g.get("invoice_date") or g.get("date") or g.get("created_date")
                parsed_dt = parse_date(raw_date)
                if parsed_dt:
                    if parsed_dt < dt_from or parsed_dt > dt_to:
                        # Skip out of range records
                        continue

                inv_no = str(g.get("invoice_no") or g.get("grn_number") or g.get("draft_number") or "").strip()
                grn_no = str(g.get("grn_number") or g.get("draft_number") or "").strip()
                if not inv_no:
                    inv_no = grn_no or "-"

                # Track doc numbers for Docs sheet
                doc_ident = inv_no if inv_no != "-" else grn_no
                if doc_ident and doc_ident != "-":
                    if docs_drug["min_no"] is None or doc_ident < docs_drug["min_no"]:
                        docs_drug["min_no"] = doc_ident
                    if docs_drug["max_no"] is None or doc_ident > docs_drug["max_no"]:
                        docs_drug["max_no"] = doc_ident

                docs_drug["total_count"] += 1
                if is_cancelled:
                    docs_drug["cancelled"] += 1
                    continue

                vid = str(g.get("vendor_id") or "").strip()
                vendor = drug_vendors.get(vid) or stores_vendors.get(vid) or {}
                vendor_name = vendor.get("name") or str(g.get("vendor_name") or f"Vendor #{vid}").strip()
                gstin = (vendor.get("gstin") or "").strip() or "-"
                vendor_state = (vendor.get("state") or "Tamil Nadu").strip()

                # State of supply determination
                state_of_supply = vendor_state if vendor_state else "Tamil Nadu"

                invoice_value = to_float(g.get("net_invoice_amount") or g.get("total_amount") or 0.0)

                # Parse items
                raw_items = g.get("items") or []
                if isinstance(raw_items, str):
                    try:
                        raw_items = json.loads(raw_items)
                    except Exception:
                        raw_items = []

                # Group items by Tax Rate for B2B & HSN
                rate_buckets = {}

                if isinstance(raw_items, list) and raw_items:
                    for itm in raw_items:
                        if not isinstance(itm, dict):
                            continue
                        rate = to_float(itm.get("purchase_tax_rate") or itm.get("tax") or 0.0)
                        qty = to_float(itm.get("quantity") or itm.get("unit") or 1.0)
                        base = to_float(
                            itm.get("item_value")
                            or itm.get("baseAmount")
                            or (to_float(itm.get("unit_price") or itm.get("packing_price")) * qty)
                        )
                        cgst = to_float(itm.get("cgst_amt") or 0.0)
                        sgst = to_float(itm.get("sgst_amt") or 0.0)
                        igst = to_float(itm.get("igst_amt") or 0.0)

                        if rate not in rate_buckets:
                            rate_buckets[rate] = {"taxable": 0.0, "cgst": 0.0, "sgst": 0.0, "igst": 0.0}
                        rate_buckets[rate]["taxable"] += base
                        rate_buckets[rate]["cgst"] += cgst
                        rate_buckets[rate]["sgst"] += sgst
                        rate_buckets[rate]["igst"] += igst

                        # HSN accumulation
                        hsn_code = str(itm.get("hsn") or "").strip() or "30031000"
                        itm_desc = str(itm.get("name") or "MEDICINE").strip().upper()
                        uom = normalize_uom(itm.get("packing") or itm.get("unit"))

                        hsn_key = (hsn_code, rate, uom, "MEDICINE")
                        if hsn_key not in hsn_map:
                            hsn_map[hsn_key] = {
                                "description": "MEDICINE",
                                "hsn": hsn_code,
                                "uom": uom,
                                "total_quantity": 0.0,
                                "tax_rate": rate,
                                "taxable_value": 0.0,
                                "igst": 0.0,
                                "cgst": 0.0,
                                "sgst": 0.0,
                                "cess": 0.0,
                                "source_type": "Drug Purchase",
                            }
                        hsn_map[hsn_key]["total_quantity"] += qty
                        hsn_map[hsn_key]["taxable_value"] += base
                        hsn_map[hsn_key]["cgst"] += cgst
                        hsn_map[hsn_key]["sgst"] += sgst
                        hsn_map[hsn_key]["igst"] += igst

                # Fallback if items were empty or missing tax rate
                if not rate_buckets:
                    taxable = to_float(g.get("taxable_amount") or 0.0)
                    cgst = to_float(g.get("cgst") or 0.0)
                    sgst = to_float(g.get("sgst") or 0.0)
                    igst = to_float(g.get("igst") or 0.0)
                    rate = round(((cgst + sgst + igst) / taxable * 100), 1) if taxable > 0 else 0.0
                    rate_buckets[rate] = {"taxable": taxable, "cgst": cgst, "sgst": sgst, "igst": igst}

                    hsn_key = ("30031000", rate, "Numbers", "MEDICINE")
                    if hsn_key not in hsn_map:
                        hsn_map[hsn_key] = {
                            "description": "MEDICINE",
                            "hsn": "30031000",
                            "uom": "Numbers",
                            "total_quantity": 1.0,
                            "tax_rate": rate,
                            "taxable_value": 0.0,
                            "igst": 0.0,
                            "cgst": 0.0,
                            "sgst": 0.0,
                            "cess": 0.0,
                            "source_type": "Drug Purchase",
                        }
                    hsn_map[hsn_key]["taxable_value"] += taxable
                    hsn_map[hsn_key]["cgst"] += cgst
                    hsn_map[hsn_key]["sgst"] += sgst
                    hsn_map[hsn_key]["igst"] += igst

                # Push to B2B list (one row per tax rate for this invoice)
                for rate, b in rate_buckets.items():
                    b2b_list.append({
                        "id": f"drug_{g.get('_id')}_{rate}",
                        "invoice_no": inv_no,
                        "customer_name": vendor_name,
                        "vendor_name": vendor_name,
                        "gstin": gstin,
                        "invoice_date": format_date_str(parsed_dt or raw_date),
                        "invoice_value": round(invoice_value, 2),
                        "tax_rate": rate,
                        "taxable_value": round(b["taxable"], 2),
                        "igst": round(b["igst"], 2) if b["igst"] > 0 else None,
                        "cgst": round(b["cgst"], 2),
                        "sgst": round(b["sgst"], 2),
                        "cess": None,
                        "state_of_supply": state_of_supply,
                        "reverse_charge": "N",
                        "grn_number": grn_no,
                        "source_type": "Drug Purchase",
                        "vendor_id": vid,
                    })

        # ── 4. PROCESS GENERAL STORES (hospital_storesgrn) ────────────────────
        if source_type in ("all", "stores", "general"):
            stores_records = list(hms_db["hospital_storesgrn"].find(date_query).sort("created_date", -1))
            if not stores_records and not from_date_param and not to_date_param:
                stores_records = list(hms_db["hospital_storesgrn"].find().sort("created_date", -1).limit(500))

            for g in stores_records:
                is_cancelled = bool(g.get("is_cancelled")) or str(g.get("status") or "").lower() == "cancelled"

                raw_date = g.get("invoice_date") or g.get("date") or g.get("created_date")
                parsed_dt = parse_date(raw_date)
                if parsed_dt:
                    if parsed_dt < dt_from or parsed_dt > dt_to:
                        continue

                inv_no = str(g.get("invoice_no") or g.get("grn_number") or "").strip()
                grn_no = str(g.get("grn_number") or "").strip()
                if not inv_no:
                    inv_no = grn_no or "-"

                doc_ident = inv_no if inv_no != "-" else grn_no
                if doc_ident and doc_ident != "-":
                    if docs_stores["min_no"] is None or doc_ident < docs_stores["min_no"]:
                        docs_stores["min_no"] = doc_ident
                    if docs_stores["max_no"] is None or doc_ident > docs_stores["max_no"]:
                        docs_stores["max_no"] = doc_ident

                docs_stores["total_count"] += 1
                if is_cancelled:
                    docs_stores["cancelled"] += 1
                    continue

                vid = str(g.get("vendor_id") or "").strip()
                vendor = stores_vendors.get(vid) or drug_vendors.get(vid) or {}
                vendor_name = vendor.get("name") or str(g.get("vendor_name") or f"Vendor #{vid}").strip()
                gstin = (vendor.get("gstin") or "").strip() or "-"
                vendor_state = (vendor.get("state") or "Tamil Nadu").strip()
                state_of_supply = vendor_state if vendor_state else "Tamil Nadu"

                invoice_value = to_float(g.get("net_invoice_amount") or g.get("total_amount") or 0.0)

                raw_items = g.get("items") or []
                if isinstance(raw_items, str):
                    try:
                        raw_items = json.loads(raw_items)
                    except Exception:
                        raw_items = []

                rate_buckets = {}
                if isinstance(raw_items, list) and raw_items:
                    for itm in raw_items:
                        if not isinstance(itm, dict):
                            continue
                        rate = to_float(itm.get("tax") or itm.get("purchase_tax_rate") or 0.0)
                        qty = to_float(itm.get("quantity") or itm.get("no_of_unit") or 1.0)
                        base = to_float(
                            itm.get("baseAmount")
                            or itm.get("itemValue")
                            or (to_float(itm.get("unitPrice")) * qty)
                        )
                        cgst = to_float(itm.get("cgstAmt") or itm.get("cgst_amt") or 0.0)
                        sgst = to_float(itm.get("sgstAmt") or itm.get("sgst_amt") or 0.0)
                        igst = to_float(itm.get("igstAmt") or itm.get("igst_amt") or 0.0)

                        # Auto-multiply per-unit tax if it was stored per unit
                        if cgst > 0 and cgst < 15 and qty > 10 and (cgst * qty) <= (base * 0.28):
                            cgst = cgst * qty
                        if sgst > 0 and sgst < 15 and qty > 10 and (sgst * qty) <= (base * 0.28):
                            sgst = sgst * qty
                        if igst > 0 and igst < 30 and qty > 10 and (igst * qty) <= (base * 0.28):
                            igst = igst * qty

                        if rate not in rate_buckets:
                            rate_buckets[rate] = {"taxable": 0.0, "cgst": 0.0, "sgst": 0.0, "igst": 0.0}
                        rate_buckets[rate]["taxable"] += base
                        rate_buckets[rate]["cgst"] += cgst
                        rate_buckets[rate]["sgst"] += sgst
                        rate_buckets[rate]["igst"] += igst

                        # HSN accumulation
                        hsn_code = str(itm.get("hsn") or "").strip() or "9999"
                        itm_desc = str(itm.get("name") or "GENERAL SUPPLIES").strip().upper()
                        uom = normalize_uom(itm.get("packing") or itm.get("unit"))

                        hsn_key = (hsn_code, rate, uom, itm_desc[:25])
                        if hsn_key not in hsn_map:
                            hsn_map[hsn_key] = {
                                "description": itm_desc[:25],
                                "hsn": hsn_code,
                                "uom": uom,
                                "total_quantity": 0.0,
                                "tax_rate": rate,
                                "taxable_value": 0.0,
                                "igst": 0.0,
                                "cgst": 0.0,
                                "sgst": 0.0,
                                "cess": 0.0,
                                "source_type": "General Stores",
                            }
                        hsn_map[hsn_key]["total_quantity"] += qty
                        hsn_map[hsn_key]["taxable_value"] += base
                        hsn_map[hsn_key]["cgst"] += cgst
                        hsn_map[hsn_key]["sgst"] += sgst
                        hsn_map[hsn_key]["igst"] += igst

                if not rate_buckets:
                    taxable = to_float(g.get("taxable_amount") or 0.0)
                    cgst = to_float(g.get("cgst") or 0.0)
                    sgst = to_float(g.get("sgst") or 0.0)
                    igst = to_float(g.get("igst") or 0.0)
                    rate = round(((cgst + sgst + igst) / taxable * 100), 1) if taxable > 0 else 0.0
                    rate_buckets[rate] = {"taxable": taxable, "cgst": cgst, "sgst": sgst, "igst": igst}

                    hsn_key = ("9999", rate, "Numbers", "GENERAL SUPPLIES")
                    if hsn_key not in hsn_map:
                        hsn_map[hsn_key] = {
                            "description": "GENERAL SUPPLIES",
                            "hsn": "9999",
                            "uom": "Numbers",
                            "total_quantity": 1.0,
                            "tax_rate": rate,
                            "taxable_value": 0.0,
                            "igst": 0.0,
                            "cgst": 0.0,
                            "sgst": 0.0,
                            "cess": 0.0,
                            "source_type": "General Stores",
                        }
                    hsn_map[hsn_key]["taxable_value"] += taxable
                    hsn_map[hsn_key]["cgst"] += cgst
                    hsn_map[hsn_key]["sgst"] += sgst
                    hsn_map[hsn_key]["igst"] += igst

                for rate, b in rate_buckets.items():
                    b2b_list.append({
                        "id": f"stores_{g.get('_id')}_{rate}",
                        "invoice_no": inv_no,
                        "customer_name": vendor_name,
                        "vendor_name": vendor_name,
                        "gstin": gstin,
                        "invoice_date": format_date_str(parsed_dt or raw_date),
                        "invoice_value": round(invoice_value, 2),
                        "tax_rate": rate,
                        "taxable_value": round(b["taxable"], 2),
                        "igst": round(b["igst"], 2) if b["igst"] > 0 else None,
                        "cgst": round(b["cgst"], 2),
                        "sgst": round(b["sgst"], 2),
                        "cess": None,
                        "state_of_supply": state_of_supply,
                        "reverse_charge": "N",
                        "grn_number": grn_no,
                        "source_type": "General Stores",
                        "vendor_id": vid,
                    })

        # ── 5. OPTIONAL FILTERS ───────────────────────────────────────────────
        if tax_rate_filter is not None and str(tax_rate_filter).strip() != "":
            try:
                target_rate = float(tax_rate_filter)
                b2b_list = [r for r in b2b_list if abs(r["tax_rate"] - target_rate) < 0.01]
            except Exception:
                pass

        if vendor_filter:
            v_target = str(vendor_filter).strip().lower()
            b2b_list = [r for r in b2b_list if v_target in str(r.get("vendor_id", "")).lower() or v_target in str(r.get("customer_name", "")).lower()]

        if search_query:
            b2b_list = [
                r for r in b2b_list
                if search_query in str(r.get("invoice_no", "")).lower()
                or search_query in str(r.get("customer_name", "")).lower()
                or search_query in str(r.get("gstin", "")).lower()
                or search_query in str(r.get("grn_number", "")).lower()
            ]

        # ── 6. FORMAT HSN LIST ────────────────────────────────────────────────
        hsn_list = []
        for key, val in sorted(hsn_map.items(), key=lambda x: (x[0][0], x[0][1])):
            val["taxable_value"] = round(val["taxable_value"], 2)
            val["cgst"] = round(val["cgst"], 2)
            val["sgst"] = round(val["sgst"], 2)
            val["igst"] = round(val["igst"], 2)
            val["total_quantity"] = round(val["total_quantity"], 2)
            hsn_list.append(val)

        # ── 7. FORMAT DOCS LIST ───────────────────────────────────────────────
        docs_list = []
        if docs_drug["total_count"] > 0 or source_type in ("all", "drug", "pharmacy"):
            docs_list.append({
                "particulars": docs_drug["particulars"],
                "sl_no_from": docs_drug["min_no"] or "-",
                "sl_no_to": docs_drug["max_no"] or "-",
                "total_count": docs_drug["total_count"],
                "cancelled": docs_drug["cancelled"],
                "net_issued": docs_drug["total_count"] - docs_drug["cancelled"],
            })

        if docs_stores["total_count"] > 0 or source_type in ("all", "stores", "general"):
            docs_list.append({
                "particulars": docs_stores["particulars"],
                "sl_no_from": docs_stores["min_no"] or "-",
                "sl_no_to": docs_stores["max_no"] or "-",
                "total_count": docs_stores["total_count"],
                "cancelled": docs_stores["cancelled"],
                "net_issued": docs_stores["total_count"] - docs_stores["cancelled"],
            })

        # ── 8. COMPUTE KPI SUMMARY ────────────────────────────────────────────
        unique_invs = len({r["invoice_no"] for r in b2b_list if r.get("invoice_no")})
        # Distinct invoice values sum to avoid double counting multi-rate invoices
        seen_inv_values = {}
        for r in b2b_list:
            inv = r.get("invoice_no") or r.get("grn_number")
            if inv not in seen_inv_values:
                seen_inv_values[inv] = r.get("invoice_value", 0.0)

        total_inv_val = sum(seen_inv_values.values())
        total_taxable = sum(r.get("taxable_value", 0.0) for r in b2b_list)
        total_cgst = sum(r.get("cgst", 0.0) for r in b2b_list)
        total_sgst = sum(r.get("sgst", 0.0) for r in b2b_list)
        total_igst = sum(r.get("igst") or 0.0 for r in b2b_list)

        # Rate-wise aggregation
        rate_summary_map = {}
        for r in b2b_list:
            rt = r["tax_rate"]
            if rt not in rate_summary_map:
                rate_summary_map[rt] = {"rate": rt, "taxable": 0.0, "cgst": 0.0, "sgst": 0.0, "igst": 0.0, "total_tax": 0.0, "invoices": set()}
            rate_summary_map[rt]["taxable"] += r.get("taxable_value", 0.0)
            rate_summary_map[rt]["cgst"] += r.get("cgst", 0.0)
            rate_summary_map[rt]["sgst"] += r.get("sgst", 0.0)
            rate_summary_map[rt]["igst"] += r.get("igst") or 0.0
            rate_summary_map[rt]["total_tax"] += (r.get("cgst", 0.0) + r.get("sgst", 0.0) + (r.get("igst") or 0.0))
            rate_summary_map[rt]["invoices"].add(r.get("invoice_no"))

        rate_wise_summary = []
        for rt, sm in sorted(rate_summary_map.items(), key=lambda x: x[0]):
            rate_wise_summary.append({
                "rate": rt,
                "taxable": round(sm["taxable"], 2),
                "cgst": round(sm["cgst"], 2),
                "sgst": round(sm["sgst"], 2),
                "igst": round(sm["igst"], 2),
                "total_tax": round(sm["total_tax"], 2),
                "invoice_count": len(sm["invoices"]),
            })

        summary = {
            "total_invoices": unique_invs,
            "total_rows": len(b2b_list),
            "total_invoice_value": round(total_inv_val, 2),
            "total_taxable_value": round(total_taxable, 2),
            "total_cgst": round(total_cgst, 2),
            "total_sgst": round(total_sgst, 2),
            "total_igst": round(total_igst, 2),
            "total_tax": round(total_cgst + total_sgst + total_igst, 2),
            "from_date": dt_from.strftime("%Y-%m-%d"),
            "to_date": dt_to.strftime("%Y-%m-%d"),
            "source_type": source_type,
            "drug_invoices_count": docs_drug["total_count"],
            "stores_invoices_count": docs_stores["total_count"],
            "rate_wise_summary": rate_wise_summary,
        }

        return Response({
            "success": True,
            "summary": summary,
            "b2b_data": b2b_list,
            "hsn_data": hsn_list,
            "docs_data": docs_list,
        }, status=status.HTTP_200_OK)

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print("❌ Error in purchase_gst_report_api:", tb)
        return Response({"success": False, "error": str(e), "traceback": tb}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

