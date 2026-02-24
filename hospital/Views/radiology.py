from rest_framework.decorators import api_view, permission_classes
from pyauth.auth import HasRoleAndDataPermission
from django.shortcuts import render
from django.http import JsonResponse
from rest_framework import status
from pymongo import MongoClient
from django.utils.timezone import now
from django.views.decorators.csrf import csrf_exempt
import os, json
import logging
logger = logging.getLogger(__name__)
from ..models import RadiologyReport
from datetime import datetime, timedelta
from django.utils import timezone

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_investigations(request):
    bill_type_no = request.GET.get('billTypeNo')
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    invest_bill_no_filter = request.GET.get('investBillNo')

    if not bill_type_no:
        return JsonResponse({'error': 'billTypeNo query parameter is required'}, status=400)

    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    db = client['HMS']
    invest_billing_collection = db['hospital_investbilling']
    ct_report_collection = db['hospital_radiologyreport']
    patient_collection = db['hospital_patient']

    try:
        # ── 1. Fetch billing records ─────────────────────────────────────────
        billing_filter = {'is_active': True}

        if invest_bill_no_filter:
            billing_filter['investBillNo'] = invest_bill_no_filter

        if from_date or to_date:
            date_filter = {}
            if from_date:
                try:
                    date_filter['$gte'] = datetime.strptime(from_date, '%Y-%m-%d')
                except ValueError:
                    return JsonResponse({'error': 'Invalid from_date format. Use YYYY-MM-DD'}, status=400)
            if to_date:
                try:
                    to_date_obj = datetime.strptime(to_date, '%Y-%m-%d')
                    date_filter['$lte'] = to_date_obj + timedelta(days=1) - timedelta(seconds=1)
                except ValueError:
                    return JsonResponse({'error': 'Invalid to_date format. Use YYYY-MM-DD'}, status=400)
            billing_filter['investBillDate'] = date_filter

        billing_records = list(invest_billing_collection.find(billing_filter, {'_id': 0}))

        if not billing_records:
            return JsonResponse([], safe=False)

        # ── 2. Filter records where item JSON contains the requested billTypeNo ──
        filtered_records = []
        for record in billing_records:
            try:
                items = json.loads(record.get('item', '[]'))
            except (json.JSONDecodeError, TypeError):
                items = []

            matched_items = [i for i in items if i.get('billTypeNo') == bill_type_no]
            if not matched_items:
                continue

            record['_matched_items'] = matched_items
            filtered_records.append(record)

        if not filtered_records:
            return JsonResponse([], safe=False)

        # ── 3. Get investBillNos to fetch matching reports ───────────────────
        bill_nos = [r['investBillNo'] for r in filtered_records if r.get('investBillNo')]

        # ── 4. Fetch active CT reports — key by (investBillNo, itemName) ─────
        ct_reports = list(ct_report_collection.find(
            {'investBillNo': {'$in': bill_nos}, 'is_active': True},
            {'_id': 0}
        ))
        report_map = {}
        for r in ct_reports:
            bill = r.get('investBillNo')
            item_name = r.get('itemName', '')
            if bill:
                for field in ['date', 'created_date', 'lastmodified_date', 'approved_date', 'deleted_date']:
                    if field in r and isinstance(r[field], datetime):
                        r[field] = r[field].isoformat()
                report_map[(bill, item_name)] = r

        # ── 5. Fetch patient details ─────────────────────────────────────────
        uhid_list = list({r['uhid'] for r in filtered_records if r.get('uhid')})
        patients = list(patient_collection.find(
            {'uhid': {'$in': uhid_list}},
            {'_id': 0, 'uhid': 1, 'salutation': 1, 'firstName': 1, 'lastName': 1, 'age': 1, 'gender': 1}
        ))
        patient_map = {p['uhid']: p for p in patients}

        # ── 6. Expand one row per matched item and merge ─────────────────────
        result = []
        for record in filtered_records:
            invest_bill_no = record.get('investBillNo')
            if not invest_bill_no:
                continue

            uhid = record.get('uhid', '')
            patient = patient_map.get(uhid, {})
            matched_items = record.get('_matched_items', [])

            base = record.copy()
            base.pop('_matched_items', None)

            for field in ['investBillDate', 'created_date', 'lastmodified_date']:
                if field in base and isinstance(base[field], datetime):
                    base[field] = base[field].isoformat()

            base['salutation'] = patient.get('salutation', '')
            base['firstName'] = patient.get('firstName', '')
            base['lastName'] = patient.get('lastName', '')
            base['age'] = patient.get('age', None)
            base['gender'] = patient.get('gender', '')

            for item in matched_items:
                item_name = item.get('itemName', '')
                report = report_map.get((invest_bill_no, item_name))

                row = base.copy()
                row['itemName'] = item_name
                row['report'] = report
                row['hasReport'] = report is not None

                result.append(row)

        return JsonResponse(result, safe=False)

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
    finally:
        client.close()
        
@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def create_scan_report(request):
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    collection = client['HMS']['hospital_radiologyreport']
    try:
        data = request.data
        user_id = data.get('auth-user-id', 'system')
        invest_bill_no = data.get('investBillNo')

        # ✅ Duplicate check — any active report for this investBillNo
        existing = collection.find_one(
            {'investBillNo': invest_bill_no,'itemName': data.get('itemName'), 'is_active': True},
            {'_id': 1}
        )
        if existing:
            return JsonResponse(
                {'error': f'A report already exists for Bill No {invest_bill_no}'},
                status=409
            )

        # Parse investBillDate
        invest_bill_date = data.get('investBillDate')
        if invest_bill_date:
            try:
                date_value = datetime.fromisoformat(invest_bill_date.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                date_value = timezone.now()
        else:
            date_value = timezone.now()

        # ✅ Store with is_active=True
        ct_report = RadiologyReport.objects.create(
            date=date_value,
            investBillNo=invest_bill_no,
            itemName=data.get('itemName'),
            impression=data.get('impression'),
            billTypeNo=data.get('billTypeNo'),
            is_active=True,
            created_by=user_id,
        )

        return JsonResponse({
            "id": str(ct_report.id),
            "investBillNo": ct_report.investBillNo,
            "message": "Report created successfully",
        }, status=201)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({"error": str(e)}, status=400)
    finally:
        client.close()


@csrf_exempt
@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def approve_scan_report(request, investBillNo, itemName):
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    collection = client['HMS']['hospital_radiologyreport']
    try:
        user_id = request.data.get('auth-user-id', 'system')

        report = collection.find_one(
            {'investBillNo': investBillNo, 'itemName': itemName, 'is_active': True}
        )
        if not report:
            return JsonResponse({"error": "Report not found"}, status=404)

        collection.update_one(
            {"_id": report["_id"]},
            {"$set": {
                "is_approved": True,
                "approved_by": user_id,
                "approved_date": timezone.now(),
            }}
        )

        updated = collection.find_one({"_id": report["_id"]})
        updated["_id"] = str(updated["_id"])
        for field in ["date", "created_date", "lastmodified_date", "approved_date"]:
            if field in updated and isinstance(updated[field], datetime):
                updated[field] = updated[field].isoformat()

        return JsonResponse(updated, safe=False, status=200)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)
    finally:
        client.close()


@csrf_exempt
@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def edit_scan_report_impression(request, investBillNo, itemName):
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    collection = client['HMS']['hospital_radiologyreport']
    try:
        new_impression = request.data.get("impression")
        user_id = request.data.get('auth-user-id', 'system')

        if not new_impression:
            return JsonResponse({"error": "Impression field is required"}, status=400)

        report = collection.find_one(
            {'investBillNo': investBillNo, 'itemName': itemName, 'is_active': True}
        )
        if not report:
            return JsonResponse({"error": "Report not found"}, status=404)

        collection.update_one(
            {"_id": report["_id"]},
            {"$set": {
                "impression": new_impression,
                "lastmodified_by": user_id,
                "lastmodified_date": timezone.now(),
            }}
        )

        updated = collection.find_one({"_id": report["_id"]})
        updated["_id"] = str(updated["_id"])
        for field in ["date", "created_date", "lastmodified_date", "approved_date"]:
            if field in updated and isinstance(updated[field], datetime):
                updated[field] = updated[field].isoformat()

        return JsonResponse(updated, safe=False, status=200)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)
    finally:
        client.close()


@csrf_exempt
@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def soft_delete_scan_report(request, investBillNo, itemName):
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    collection = client['HMS']['hospital_radiologyreport']
    try:
        user_id = request.data.get('auth-user-id', 'system')

        report = collection.find_one(
            {'investBillNo': investBillNo, 'itemName': itemName, 'is_active': True}
        )
        if not report:
            return JsonResponse({"error": "Report not found"}, status=404)

        collection.update_one(
            {"_id": report["_id"]},
            {"$set": {
                "is_active": False,
                "deleted_by": user_id,
                "deleted_date": timezone.now(),
            }}
        )

        return JsonResponse({"message": "Report deleted successfully"}, status=200)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)
    finally:
        client.close()