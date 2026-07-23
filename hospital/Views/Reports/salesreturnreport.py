from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from pyauth.auth import HasRoleAndDataPermission
from pymongo import MongoClient
import os
from datetime import datetime
from ...models import SalesReturn, Patient, PharmacyBilling, PharmacyItem


def get_employee_mapping(client, employee_ids):
    if not employee_ids:
        return {}
    try:
        global_db = client['Global']
        diagnostics_collection = global_db['backend_diagnostics_profile']
        profiles = diagnostics_collection.find(
            {"employeeId": {"$in": list(employee_ids)}},
            {"employeeId": 1, "employeeName": 1, "_id": 0}
        )
        return {str(p['employeeId']): p.get('employeeName', '') for p in profiles}
    except Exception:
        return {}


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def sales_return_report_view(request):
    """
    Sales Return Report — lists pharmacy sales returns for a date range,
    classified as IP or OP based on the original bill's inpatient_number.

    Query params:
    - start_date: YYYY-MM-DD
    - end_date: YYYY-MM-DD
    - return_type: 'all' | 'ip' | 'op' (default 'all')
    """
    try:
        start_date_str = request.GET.get('start_date')
        end_date_str = request.GET.get('end_date')
        return_type = (request.GET.get('return_type') or 'all').strip().lower()

        if not start_date_str or not end_date_str:
            return Response({"error": "start_date and end_date are required"}, status=400)

        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
        except ValueError:
            return Response({"error": "Invalid date format. Use YYYY-MM-DD"}, status=400)

        records = list(
            SalesReturn.objects.filter(
                return_bill_date__range=(start_date, end_date)
            ).order_by('-return_bill_date')
        )

        if not records:
            return Response({
                "data": [],
                "summary": {"total_returns": 0, "op_returns": 0, "ip_returns": 0, "total_amount": 0},
                "count": 0
            }, status=200)

        bill_nos = {r.bill_no for r in records if r.bill_no}
        uhids = {r.uhid for r in records if r.uhid}

        # Original bill -> tells us IP vs OP (via inpatient_number) and the doctor
        billing_map = {b.bill_no: b for b in PharmacyBilling.objects.filter(bill_no__in=bill_nos)}

        patient_map = {}
        for p in Patient.objects.filter(uhid__in=uhids):
            name_parts = [p.salutation, p.firstName, p.lastName]
            patient_map[p.uhid] = " ".join([x for x in name_parts if x]).strip() or "Unknown"

        item_ids = set()
        for r in records:
            items = r.medicine_particulars
            if isinstance(items, list):
                for it in items:
                    if isinstance(it, dict) and it.get('item_id') is not None:
                        try:
                            item_ids.add(int(it['item_id']))
                        except (TypeError, ValueError):
                            pass
        item_name_map = {}
        if item_ids:
            item_name_map = {
                i.item_id: i.item_name
                for i in PharmacyItem.objects.filter(item_id__in=item_ids)
            }

        employee_ids = {r.created_by for r in records if r.created_by}
        employee_ids |= {b.doctor_id for b in billing_map.values() if b.doctor_id}

        mongo_client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        employee_map = get_employee_mapping(mongo_client, employee_ids)
        mongo_client.close()

        data = []
        for r in records:
            original_bill = billing_map.get(r.bill_no)
            is_ip = bool(original_bill and original_bill.inpatient_number)
            patient_type = "IP" if is_ip else "OP"

            if return_type in ("ip", "op") and patient_type.lower() != return_type:
                continue

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
                total_qty += float(str(qty or 0))
                item_labels.append(f"{name} x{qty}")

            doctor_id = original_bill.doctor_id if original_bill else None

            data.append({
                "return_bill_no": r.return_bill_no,
                "return_bill_date": r.return_bill_date,
                "bill_no": r.bill_no,
                "patient_type": patient_type,
                "ip_number": (original_bill.inpatient_number if original_bill else "") or "",
                "uhid": r.uhid,
                "patient_name": patient_map.get(r.uhid, "Unknown"),
                "doctor_name": employee_map.get(str(doctor_id), doctor_id) if doctor_id else "N/A",
                "item_count": len(items),
                "return_qty": total_qty,
                "items_summary": ", ".join(item_labels),
                "return_amount": float(str(r.return_amount or 0)),
                "status": r.status,
                "mode": "Cash Return" if r.PaymentType == "Cash" else "IP Credit",
                "pharmacist_name": employee_map.get(str(r.created_by), r.created_by or "")
            })

        summary = {
            "total_returns": len(data),
            "op_returns": len([d for d in data if d["patient_type"] == "OP"]),
            "ip_returns": len([d for d in data if d["patient_type"] == "IP"]),
            "total_amount": sum(d["return_amount"] for d in data),
        }

        return Response({"data": data, "summary": summary, "count": len(data)}, status=200)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"error": str(e)}, status=500)
