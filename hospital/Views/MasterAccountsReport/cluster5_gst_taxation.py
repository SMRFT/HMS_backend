"""
Cluster 5: GST Taxation Registers (Winman GSTR-1 & ITC) APIs
============================================================
1. Day-Wise Sales Tax Register
2. Monthly Sales Tax Register
3. OP Pharmacy Sales GST (Invoices, HSN, Document Summary)
4. Drug Purchase GST (Inward Supplies, ITC, HSN)
5. General Stores GST (Inward Supplies, HSN)
6. Purchase GST Consolidated (Winman format)
"""

from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from pyauth.auth import HasRoleAndDataPermission
from .core_ledger_engine import clean_num, parse_date, format_dt, get_db, format_ist_date
from datetime import datetime, timedelta

from hospital.Views.AccountsReport.purchase_gst_report import get_purchase_gst_report_data
from hospital.Views.AccountsReport.op_pharmacy_sales_report import get_op_pharmacy_sales_report_data

@api_view(["GET", "POST"])
@permission_classes([HasRoleAndDataPermission])
def sales_tax_register_api(request):
    """
    Dedicated Sales Tax Register (Day-Wise & Monthly).
    Taxable values, CGST, SGST, IGST across pharmacy and taxable medical supplies.
    """
    try:
        data = request.data if request.method == "POST" else request.query_params
        from_str = data.get("from_date") or data.get("start_date")
        to_str = data.get("to_date") or data.get("end_date")
        
        f_d = parse_date(from_str) if from_str else datetime.now().date()
        t_d = parse_date(to_str, is_end=True) if to_str else datetime.now()
        f_dt_utc = f_d - timedelta(hours=5, minutes=30)
        t_dt_utc = t_d - timedelta(hours=5, minutes=30)

        client, db, g_db = get_db()
        try:
            pharm_docs = list(db["hospital_pharmacybilling"].find({
                "created_date": {"$gte": f_dt_utc, "$lte": t_dt_utc},
                "billing_status": {"$ne": "Cancelled"}
            }))

            day_map = {}
            tot_taxable = 0.0
            tot_cgst = 0.0
            tot_sgst = 0.0
            tot_gross = 0.0

            for p in pharm_docs:
                gross_amt = clean_num(p.get("net_amount") or p.get("total_amount"))
                c_date = p.get("created_date") or p.get("bill_date")
                d_str = format_ist_date(c_date) if c_date else str(f_d)[:10]
                
                # Standard pharmacy medicine rate in India: 5% GST (2.5% CGST + 2.5% SGST)
                taxable = round(gross_amt / 1.05, 2)
                gst = round(gross_amt - taxable, 2)
                cgst = round(gst / 2.0, 2)
                sgst = round(gst - cgst, 2)
                
                day_map.setdefault(d_str, {"date": d_str, "taxable": 0.0, "cgst": 0.0, "sgst": 0.0, "total": 0.0, "invoices": 0})
                day_map[d_str]["taxable"] += taxable
                day_map[d_str]["cgst"] += cgst
                day_map[d_str]["sgst"] += sgst
                day_map[d_str]["total"] += gross_amt
                day_map[d_str]["invoices"] += 1
                
                tot_taxable += taxable
                tot_cgst += cgst
                tot_sgst += sgst
                tot_gross += gross_amt

            rows = sorted(day_map.values(), key=lambda x: x["date"])
            for r in rows:
                r["taxable"] = round(r["taxable"], 2)
                r["cgst"] = round(r["cgst"], 2)
                r["sgst"] = round(r["sgst"], 2)
                r["total"] = round(r["total"], 2)

            return Response({
                "success": True,
                "report_title": "Sales Tax Register",
                "date_range": {"from_date": str(f_d)[:10], "to_date": str(t_d)[:10]},
                "summary": {
                    "total_taxable_value": round(tot_taxable, 2),
                    "total_cgst": round(tot_cgst, 2),
                    "total_sgst": round(tot_sgst, 2),
                    "total_tax": round(tot_cgst + tot_sgst, 2),
                    "total_invoice_value": round(tot_gross, 2)
                },
                "data": rows
            }, status=status.HTTP_200_OK)
        finally:
            client.close()
    except Exception as e:
        return Response({"success": False, "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(["GET", "POST"])
@permission_classes([HasRoleAndDataPermission])
def op_pharmacy_sales_gst_api(request):
    """
    Dedicated OP Pharmacy Sales GST API in Winman GSTR-1 format:
    - B2B/B2C Invoices (sales_data)
    - HSN Summary (hsn_data)
    - Document Summary (docs_data)
    """
    try:
        data = request.data if request.method == "POST" else (
            request.query_params if hasattr(request, "query_params") else getattr(request, "GET", {})
        )
        from_str = data.get("from_date") or data.get("start_date")
        to_str = data.get("to_date") or data.get("end_date")
        outlet_code = data.get("outlet_code")
        tax_rate = data.get("tax_rate")
        search = data.get("search")

        res_data = get_op_pharmacy_sales_report_data(
            from_date_param=from_str,
            to_date_param=to_str,
            outlet_code_filter=outlet_code,
            tax_rate_filter=tax_rate,
            search_query=search
        )
        if not isinstance(res_data, dict) or ("sales_data" not in res_data and not res_data.get("success")):
            return Response(res_data if isinstance(res_data, dict) else {"success": False}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        sales = res_data.get("sales_data") or []
        hsn = res_data.get("hsn_data") or []
        docs = res_data.get("docs_data") or []
        summary = res_data.get("summary") or {}

        # Standardized payload with multi-version aliases
        return Response({
            "success": True,
            "report_title": "OP Pharmacy Sales GST Register (GSTR-1)",
            "sales_data": sales,
            "invoices": sales,
            "invoices_data": sales,
            "b2b_data": sales,
            "hsn_data": hsn,
            "hsn_summary": hsn,
            "docs_data": docs,
            "document_summary": docs,
            "doc_summary": docs[0] if docs else {},
            "summary": summary
        }, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"success": False, "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(["GET", "POST"])
@permission_classes([HasRoleAndDataPermission])
def purchase_gst_consolidated_api(request):
    """
    Dedicated Purchase GST Consolidated Register API (ITC in Winman GSTR-1 Format).
    Supports:
    - Drug Purchase (source_type=drug)
    - General Stores (source_type=stores)
    - Consolidated (source_type=all)
    Returns:
    - B2B Invoices (b2b_data / invoices)
    - HSN Summary (hsn_data / hsn_summary)
    - Document Summary (docs_data / document_summary)
    """
    try:
        data = request.data if request.method == "POST" else (
            request.query_params if hasattr(request, "query_params") else getattr(request, "GET", {})
        )
        from_str = data.get("from_date") or data.get("start_date")
        to_str = data.get("to_date") or data.get("end_date")
        source_type = data.get("source_type") or "all"
        tax_rate_filter = data.get("tax_rate")
        vendor_filter = data.get("vendor_id")
        search_query = data.get("search") or ""

        res_data = get_purchase_gst_report_data(
            from_date_param=from_str,
            to_date_param=to_str,
            source_type=source_type,
            tax_rate_filter=tax_rate_filter,
            vendor_filter=vendor_filter,
            search_query=search_query
        )
        if not isinstance(res_data, dict) or ("b2b_data" not in res_data and not res_data.get("success")):
            return Response(res_data if isinstance(res_data, dict) else {"success": False}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        b2b = res_data.get("b2b_data") or []
        hsn = res_data.get("hsn_data") or []
        docs = res_data.get("docs_data") or []
        summary = res_data.get("summary") or {}

        # Filter by source_type if explicitly requested in query or body
        src = str(source_type).lower().strip()
        if src == "drug":
            b2b = [r for r in b2b if r.get("source_type") == "Drug Purchase"]
            hsn = [r for r in hsn if r.get("source_type") == "Drug Purchase"]
            docs = [r for r in docs if "Drug Purchase" in (r.get("particulars") or "")]
        elif src == "stores":
            b2b = [r for r in b2b if r.get("source_type") == "General Stores"]
            hsn = [r for r in hsn if r.get("source_type") == "General Stores"]
            docs = [r for r in docs if "General Stores" in (r.get("particulars") or "")]

        return Response({
            "success": True,
            "report_title": "Purchase GST Consolidated Register (ITC)",
            "b2b_data": b2b,
            "invoices": b2b,
            "hsn_data": hsn,
            "hsn_summary": hsn,
            "docs_data": docs,
            "document_summary": docs,
            "doc_summary": docs[0] if docs else {},
            "summary": summary
        }, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"success": False, "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(["GET", "POST"])
@permission_classes([HasRoleAndDataPermission])
def drug_purchase_gst_api(request):
    """Convenience endpoint specifically scoped for Drug Purchase inward supply."""
    try:
        data = request.data if request.method == "POST" else (
            request.query_params if hasattr(request, "query_params") else getattr(request, "GET", {})
        )
        from_str = data.get("from_date") or data.get("start_date")
        to_str = data.get("to_date") or data.get("end_date")
        tax_rate_filter = data.get("tax_rate")
        vendor_filter = data.get("vendor_id")
        search_query = data.get("search") or ""

        res_data = get_purchase_gst_report_data(
            from_date_param=from_str,
            to_date_param=to_str,
            source_type="drug",
            tax_rate_filter=tax_rate_filter,
            vendor_filter=vendor_filter,
            search_query=search_query
        )
        if not isinstance(res_data, dict) or ("b2b_data" not in res_data and not res_data.get("success")):
            return Response(res_data if isinstance(res_data, dict) else {"success": False}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        b2b = [r for r in res_data.get("b2b_data", []) if r.get("source_type") == "Drug Purchase"]
        hsn = [r for r in res_data.get("hsn_data", []) if r.get("source_type") == "Drug Purchase"]
        docs = [r for r in res_data.get("docs_data", []) if "Drug Purchase" in (r.get("particulars") or "")]

        return Response({
            "success": True,
            "report_title": "Drug Purchase GST Register (ITC)",
            "b2b_data": b2b,
            "invoices": b2b,
            "hsn_data": hsn,
            "hsn_summary": hsn,
            "docs_data": docs,
            "document_summary": docs,
            "doc_summary": docs[0] if docs else {},
            "summary": res_data.get("summary") or {}
        }, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"success": False, "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(["GET", "POST"])
@permission_classes([HasRoleAndDataPermission])
def stores_purchase_gst_api(request):
    """Convenience endpoint specifically scoped for General Stores inward supply."""
    try:
        data = request.data if request.method == "POST" else (
            request.query_params if hasattr(request, "query_params") else getattr(request, "GET", {})
        )
        from_str = data.get("from_date") or data.get("start_date")
        to_str = data.get("to_date") or data.get("end_date")
        tax_rate_filter = data.get("tax_rate")
        vendor_filter = data.get("vendor_id")
        search_query = data.get("search") or ""

        res_data = get_purchase_gst_report_data(
            from_date_param=from_str,
            to_date_param=to_str,
            source_type="stores",
            tax_rate_filter=tax_rate_filter,
            vendor_filter=vendor_filter,
            search_query=search_query
        )
        if not isinstance(res_data, dict) or ("b2b_data" not in res_data and not res_data.get("success")):
            return Response(res_data if isinstance(res_data, dict) else {"success": False}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        b2b = [r for r in res_data.get("b2b_data", []) if r.get("source_type") == "General Stores"]
        hsn = [r for r in res_data.get("hsn_data", []) if r.get("source_type") == "General Stores"]
        docs = [r for r in res_data.get("docs_data", []) if "General Stores" in (r.get("particulars") or "")]

        return Response({
            "success": True,
            "report_title": "General Stores GST Register (ITC)",
            "b2b_data": b2b,
            "invoices": b2b,
            "hsn_data": hsn,
            "hsn_summary": hsn,
            "docs_data": docs,
            "document_summary": docs,
            "doc_summary": docs[0] if docs else {},
            "summary": res_data.get("summary") or {}
        }, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"success": False, "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
