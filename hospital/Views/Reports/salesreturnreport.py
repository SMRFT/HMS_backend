from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from pyauth.auth import HasRoleAndDataPermission
from pymongo import MongoClient
import os
from datetime import datetime
from ...models import SalesReturn, Patient, PharmacyBilling, PharmacyItem
from ..dbcollection import get_employee_name_by_id


def get_employee_mapping(client, employee_ids):
    if not employee_ids:
        return {}
    res = {}
    for eid in employee_ids:
        if not eid:
            continue
        estr = str(eid).strip()
        name = get_employee_name_by_id(estr)
        val = name if (name and name != "Unknown") else estr
        res[str(eid)] = val
        res[estr] = val
    return res


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def sales_return_report_view(request):
    """
    Sales Return & Refund Report — consolidates returns and refunds across:
    1. Pharmacy Sales Returns (SalesReturn model)
    2. Investigation / Lab / Radiology Refunds (hospital_investrefund collection)
    3. IP Advance Refunds (hospital_ipadvance_refund collection)

    Query params:
    - start_date: YYYY-MM-DD
    - end_date: YYYY-MM-DD
    - return_type: 'all' | 'op' | 'ip' | 'pharmacy' | 'investigation' | 'advance' (default 'all')
    - category: optional category filter
    - outlet_code / outlet: optional outlet filter
    """
    try:
        start_date_str = request.GET.get('start_date')
        end_date_str = request.GET.get('end_date')
        return_type = (request.GET.get('return_type') or 'all').strip().lower()
        category_param = (request.GET.get('category') or 'all').strip().lower()

        if not start_date_str or not end_date_str:
            return Response({"error": "start_date and end_date are required"}, status=400)

        try:
            start_date = datetime.strptime(start_date_str[:10], '%Y-%m-%d')
            end_date = datetime.strptime(end_date_str[:10], '%Y-%m-%d').replace(hour=23, minute=59, second=59)
        except ValueError:
            return Response({"error": "Invalid date format. Use YYYY-MM-DD"}, status=400)

        outlet_code = request.GET.get('outlet_code') or request.GET.get('outlet')
        filter_outlet = bool(outlet_code and outlet_code.lower() != 'all')

        mongo_client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        hms_db = mongo_client['HMS']

        # ---------------------------------------------------------------------
        # 1. Pharmacy Sales Return
        # ---------------------------------------------------------------------
        pharmacy_qs = SalesReturn.objects.filter(return_bill_date__range=(start_date, end_date))
        if filter_outlet:
            pharmacy_qs = pharmacy_qs.filter(outlet_code=outlet_code)
        pharmacy_records = list(pharmacy_qs.order_by('-return_bill_date'))

        bill_nos = {r.bill_no for r in pharmacy_records if r.bill_no}
        billing_map = {b.bill_no: b for b in PharmacyBilling.objects.filter(bill_no__in=bill_nos)} if bill_nos else {}

        pharmacy_item_ids = set()
        for r in pharmacy_records:
            items = r.medicine_particulars
            if isinstance(items, list):
                for it in items:
                    if isinstance(it, dict) and it.get('item_id') is not None:
                        try:
                            pharmacy_item_ids.add(int(it['item_id']))
                        except (TypeError, ValueError):
                            pass
        item_name_map = {}
        if pharmacy_item_ids:
            item_name_map = {
                i.item_id: i.item_name
                for i in PharmacyItem.objects.filter(item_id__in=pharmacy_item_ids)
            }

        # ---------------------------------------------------------------------
        # 2. Investigation Refund (hospital_investrefund)
        # ---------------------------------------------------------------------
        invest_query = {
            'refundBillDate': {'$gte': start_date, '$lte': end_date},
            'is_active': {'$ne': False}
        }
        if filter_outlet:
            invest_query['outlet_code'] = outlet_code
        invest_records = list(hms_db['hospital_investrefund'].find(invest_query))

        invest_bill_nos = [d.get('investBillNo') for d in invest_records if d.get('investBillNo')]
        invest_billing_map = {}
        if invest_bill_nos:
            for b in hms_db['hospital_investbilling'].find({'investBillNo': {'$in': invest_bill_nos}}, {'investBillNo': 1, 'doctor': 1, 'referredBy': 1}):
                invest_billing_map[b.get('investBillNo')] = b

        # ---------------------------------------------------------------------
        # 3. IP Advance Refund (hospital_ipadvance_refund)
        # ---------------------------------------------------------------------
        advance_query = {
            'refund_date': {'$gte': start_date, '$lte': end_date}
        }
        if filter_outlet:
            advance_query['outlet_code'] = outlet_code
        advance_records = list(hms_db['hospital_ipadvance_refund'].find(advance_query))

        advance_ip_numbers = [d.get('ip_number') for d in advance_records if d.get('ip_number')]
        invest_ip_numbers = [d.get('ipNumber') for d in invest_records if d.get('ipNumber')]
        all_ip_numbers = list(set([ip for ip in (advance_ip_numbers + invest_ip_numbers) if ip]))
        admission_map = {}
        if all_ip_numbers:
            for adm in hms_db['hospital_admission'].find({'ipNumber': {'$in': all_ip_numbers}}, {'ipNumber': 1, 'admittingDoctor': 1, 'consultingDoctor': 1}):
                admission_map[adm.get('ipNumber')] = adm

        # ---------------------------------------------------------------------
        # Patient & Employee Lookups
        # ---------------------------------------------------------------------
        all_uhids = set()
        for r in pharmacy_records:
            if r.uhid:
                all_uhids.add(r.uhid)
        for d in invest_records:
            if d.get('uhid'):
                all_uhids.add(d.get('uhid'))
        for d in advance_records:
            if d.get('uhid'):
                all_uhids.add(d.get('uhid'))

        patient_map = {}
        if all_uhids:
            # First try SQL Patient model
            for p in Patient.objects.filter(uhid__in=all_uhids):
                sal = (p.salutation or "").strip()
                fn = (p.firstName or "").strip()
                ln = (p.lastName or "").strip()
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
                words = full_name.split()
                if len(words) >= 2 and len(words) % 2 == 0:
                    half = len(words) // 2
                    if [w.lower() for w in words[:half]] == [w.lower() for w in words[half:]]:
                        words = words[:half]
                clean_words = []
                for idx, w in enumerate(words):
                    if idx > 0 and len(w) > 1 and w.lower() == words[idx - 1].lower():
                        continue
                    clean_words.append(w)
                pname = " ".join(clean_words).strip()
                if pname:
                    patient_map[p.uhid] = pname

            # Second fallback to MongoDB hospital_patient for any missing UHIDs
            missing_uhids = [u for u in all_uhids if u not in patient_map]
            if missing_uhids:
                for p in hms_db['hospital_patient'].find({'uhid': {'$in': missing_uhids}}, {'uhid': 1, 'name': 1, 'firstName': 1, 'lastName': 1}):
                    u = p.get('uhid')
                    pname = (p.get('name') or f"{p.get('firstName') or ''} {p.get('lastName') or ''}".strip() or '').strip()
                    if pname:
                        patient_map[u] = pname

        # Employee IDs across all 3
        employee_ids = set()
        for r in pharmacy_records:
            if r.created_by:
                employee_ids.add(r.created_by)
        for b in billing_map.values():
            if b.doctor_id:
                employee_ids.add(b.doctor_id)

        for d in invest_records:
            if d.get('created_by'):
                employee_ids.add(d.get('created_by'))
            inv_bill = invest_billing_map.get(d.get('investBillNo'))
            if inv_bill:
                if inv_bill.get('doctor'):
                    employee_ids.add(str(inv_bill.get('doctor')).strip())
                if inv_bill.get('referredBy'):
                    employee_ids.add(str(inv_bill.get('referredBy')).strip())

        for d in advance_records:
            if d.get('created_by'):
                employee_ids.add(d.get('created_by'))
            adm = admission_map.get(d.get('ip_number'))
            if adm:
                if adm.get('admittingDoctor'):
                    employee_ids.add(str(adm.get('admittingDoctor')).strip())
                if adm.get('consultingDoctor'):
                    employee_ids.add(str(adm.get('consultingDoctor')).strip())

        employee_map = get_employee_mapping(mongo_client, employee_ids)
        mongo_client.close()

        # ---------------------------------------------------------------------
        # Build Normalized Records
        # ---------------------------------------------------------------------
        data = []

        # 1. Pharmacy records
        for r in pharmacy_records:
            original_bill = billing_map.get(r.bill_no)
            is_ip = bool(original_bill and original_bill.inpatient_number)
            patient_type = "IP" if is_ip else "OP"

            items = r.medicine_particulars if isinstance(r.medicine_particulars, list) else []
            item_labels = []
            total_qty = 0
            for it in items:
                if not isinstance(it, dict):
                    continue
                try:
                    iid = int(it.get('item_id'))
                except (TypeError, ValueError):
                    iid = None
                name = item_name_map.get(iid, f"Item #{it.get('item_id')}")
                qty = it.get('return_qty', 0)
                try:
                    total_qty += float(str(qty or 0))
                except (ValueError, TypeError):
                    pass
                item_labels.append(f"{name} x{qty}")

            doctor_id = original_bill.doctor_id if original_bill else None
            doc_name = employee_map.get(str(doctor_id), doctor_id) if doctor_id else "N/A"

            date_val = r.return_bill_date
            if isinstance(date_val, datetime):
                date_str = date_val.isoformat()
            else:
                date_str = str(date_val)

            data.append({
                "return_category": "Pharmacy Return",
                "return_bill_no": r.return_bill_no,
                "return_bill_date": date_str,
                "bill_no": r.bill_no or "N/A",
                "patient_type": patient_type,
                "ip_number": (original_bill.inpatient_number if original_bill else "") or "",
                "uhid": r.uhid or "",
                "patient_name": patient_map.get(r.uhid, "Unknown"),
                "doctor_name": doc_name,
                "item_count": len(items),
                "return_qty": total_qty,
                "items_summary": ", ".join(item_labels) if item_labels else "Pharmacy return items",
                "return_amount": float(str(r.return_amount or 0)),
                "status": r.status or "Completed",
                "mode": "Cash Return" if r.PaymentType == "Cash" else "IP Credit",
                "pharmacist_name": employee_map.get(str(r.created_by), r.created_by or "N/A"),
                "outlet_code": r.outlet_code or ""
            })

        # 2. Investigation refunds
        for d in invest_records:
            ip_num = (d.get('ipNumber') or '').strip()
            patient_type = "IP" if ip_num else "OP"

            items = d.get('item', [])
            item_labels = []
            total_qty = 0
            if isinstance(items, list):
                for it in items:
                    if isinstance(it, dict):
                        iname = it.get('itemName') or 'Investigation'
                        iqty = 1
                        try:
                            iqty = float(str(it.get('quantity') or 1))
                        except (ValueError, TypeError):
                            iqty = 1
                        total_qty += iqty
                        item_labels.append(f"{iname} x{int(iqty) if iqty.is_integer() else iqty}")

            items_summary = ", ".join(item_labels) if item_labels else (d.get('refundRemarks') or 'Investigation Refund')

            inv_b = invest_billing_map.get(d.get('investBillNo'))
            doc_identifier = None
            if inv_b:
                doc_identifier = inv_b.get('doctor') or inv_b.get('referredBy')
            if not doc_identifier and ip_num:
                adm = admission_map.get(ip_num)
                if adm:
                    doc_identifier = adm.get('consultingDoctor') or adm.get('admittingDoctor')

            doc_name = "N/A"
            if doc_identifier:
                doc_str = str(doc_identifier).strip()
                doc_name = employee_map.get(doc_str, doc_str)

            amt = 0.0
            try:
                amt = float(str(d.get('refund_finalPrice') or 0))
            except (ValueError, TypeError):
                amt = 0.0

            date_val = d.get('refundBillDate')
            date_str = date_val.isoformat() if isinstance(date_val, datetime) else str(date_val or '')

            data.append({
                "return_category": "Investigation Refund",
                "return_bill_no": d.get('refundBillNo') or "N/A",
                "return_bill_date": date_str,
                "bill_no": d.get('investBillNo') or "N/A",
                "patient_type": patient_type,
                "ip_number": ip_num,
                "uhid": d.get('uhid') or "",
                "patient_name": patient_map.get(d.get('uhid'), "Unknown"),
                "doctor_name": doc_name,
                "item_count": len(items) if isinstance(items, list) else 1,
                "return_qty": total_qty or 1,
                "items_summary": items_summary,
                "return_amount": amt,
                "status": d.get('paymentStatus') or "Completed",
                "mode": "Investigation Refund",
                "pharmacist_name": employee_map.get(str(d.get('created_by')), d.get('created_by') or "N/A"),
                "outlet_code": d.get('outlet_code') or ""
            })

        # 3. IP Advance refunds
        for d in advance_records:
            ip_num = (d.get('ip_number') or '').strip()
            patient_type = "IP"  # Advance on admission is always IP

            adm = admission_map.get(ip_num)
            doc_identifier = None
            if adm:
                doc_identifier = adm.get('admittingDoctor') or adm.get('consultingDoctor')

            doc_name = "N/A"
            if doc_identifier:
                doc_str = str(doc_identifier).strip()
                doc_name = employee_map.get(doc_str, doc_str)

            amt = 0.0
            try:
                amt = float(str(d.get('refund_amount') or 0))
            except (ValueError, TypeError):
                amt = 0.0

            remarks = (d.get('remarks') or '').strip()
            summary_desc = remarks if remarks else f"IP Advance Refund (Bill #{d.get('bill_no', '')})"

            date_val = d.get('refund_date')
            date_str = date_val.isoformat() if isinstance(date_val, datetime) else str(date_val or '')

            data.append({
                "return_category": "IP Advance Refund",
                "return_bill_no": d.get('refund_bill_no') or "N/A",
                "return_bill_date": date_str,
                "bill_no": d.get('bill_no') or "N/A",
                "patient_type": patient_type,
                "ip_number": ip_num,
                "uhid": d.get('uhid') or "",
                "patient_name": patient_map.get(d.get('uhid'), "Unknown"),
                "doctor_name": doc_name,
                "item_count": 1,
                "return_qty": 1,
                "items_summary": summary_desc,
                "return_amount": amt,
                "status": d.get('status') or "Completed",
                "mode": "Advance Refund",
                "pharmacist_name": employee_map.get(str(d.get('created_by')), d.get('created_by') or "N/A"),
                "outlet_code": d.get('outlet_code') or ""
            })

        # ---------------------------------------------------------------------
        # Filter by return_type and category
        # ---------------------------------------------------------------------
        filtered_data = []
        for row in data:
            # Check category filter
            cat_lower = row["return_category"].lower()
            if category_param != 'all':
                if category_param in ('pharmacy', 'pharmacy return', 'pharmacy_return') and cat_lower != "pharmacy return":
                    continue
                elif category_param in ('investigation', 'investigation refund', 'investigation_refund', 'invest') and cat_lower != "investigation refund":
                    continue
                elif category_param in ('advance', 'ip advance', 'ip advance refund', 'ipadvance', 'ip_advance') and cat_lower != "ip advance refund":
                    continue

            # Check return_type filter
            if return_type in ("ip", "op") and row["patient_type"].lower() != return_type:
                continue
            elif return_type in ('pharmacy', 'pharmacy return', 'pharmacy_return') and cat_lower != "pharmacy return":
                continue
            elif return_type in ('investigation', 'investigation refund', 'investigation_refund', 'invest') and cat_lower != "investigation refund":
                continue
            elif return_type in ('advance', 'ip advance', 'ip advance refund', 'ipadvance', 'ip_advance') and cat_lower != "ip advance refund":
                continue

            filtered_data.append(row)

        # Sort by return_bill_date descending
        filtered_data.sort(key=lambda x: str(x.get("return_bill_date") or ""), reverse=True)

        summary = {
            "total_returns": len(filtered_data),
            "op_returns": len([d for d in filtered_data if d["patient_type"] == "OP"]),
            "ip_returns": len([d for d in filtered_data if d["patient_type"] == "IP"]),
            "pharmacy_returns": len([d for d in filtered_data if d["return_category"] == "Pharmacy Return"]),
            "investigation_refunds": len([d for d in filtered_data if d["return_category"] == "Investigation Refund"]),
            "advance_refunds": len([d for d in filtered_data if d["return_category"] == "IP Advance Refund"]),
            "total_amount": round(sum(d["return_amount"] for d in filtered_data), 2),
        }

        return Response({"data": filtered_data, "summary": summary, "count": len(filtered_data)}, status=200)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"error": str(e)}, status=500)
