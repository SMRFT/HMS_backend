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
import gridfs


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _serialize_report(doc):
    """Stringify _id and convert datetime fields to ISO strings."""
    doc["_id"] = str(doc["_id"])
    for field in ["date", "slot_DateTime", "created_date", "lastmodified_date", "approved_date", "deleted_date"]:
        if field in doc and isinstance(doc[field], datetime):
            doc[field] = doc[field].isoformat()
    return doc


def _parse_slot_datetime(raw):
    """
    Parse slot_DateTime from a string.
    Accepts ISO format (2025-07-01T14:30:00) or 'YYYY-MM-DDTHH:MM:SS'.
    Treats naive datetimes as UTC so the stored value matches what the user typed.
    Returns a timezone-aware datetime (UTC).
    """
    if not raw:
        return None
    try:
        from datetime import timezone as dt_timezone
        dt = datetime.fromisoformat(raw.replace("Z", ""))
        if dt.tzinfo is None:
            # Treat as UTC — do NOT use make_aware() which applies server's
            # local timezone (IST) and shifts the digits by +5:30.
            dt = dt.replace(tzinfo=dt_timezone.utc)
        return dt
    except (ValueError, AttributeError):
        return None


# ─── GET investigations ───────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_investigations(request):

    bill_type_no = request.GET.get('billTypeNo')
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    invest_bill_no_filter = request.GET.get('investBillNo')

    if not bill_type_no:
        return JsonResponse({'error': 'billTypeNo query parameter is required'}, status=400)

    branch_code   = request.data.get('auth-branch-code',   'system')
    hospital_code = request.data.get('auth-hospital-code', 'system')

    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    db = client['HMS']
    invest_billing_collection   = db['hospital_investbilling']
    ct_report_collection        = db['hospital_radiologyreport']
    patient_collection          = db['hospital_patient']
    invest_price_collection     = db['hospital_investigationprice']
    refund_collection           = db['hospital_investrefund']         # ← refund
    radiology_format_collection = db['hospital_radiology_formats']    # ← formats

    try:
        # ── 0. Build item_id → itemName map from investigationprice ──────────
        price_doc = invest_price_collection.find_one(
            {'billTypeNo': bill_type_no, 'is_active': True},
            {'_id': 0, 'Items': 1}
        )
        item_name_map = {}
        if price_doc:
            for itm in price_doc.get('Items', []):
                raw_id = itm.get('item_id')
                if raw_id is not None:
                    item_name_map[int(raw_id)] = itm.get('itemName', '')

        # ── 1. Fetch billing records ──────────────────────────────────────────
        billing_filter = {'is_active': True}
        if hospital_code:
            billing_filter['hospital_code'] = hospital_code
        if branch_code:
            billing_filter['branch_code'] = branch_code
        if invest_bill_no_filter:
            billing_filter['investBillNo'] = invest_bill_no_filter

        if from_date or to_date:
            date_filter = {}
            if from_date:
                try:
                    date_filter['$gte'] = datetime.strptime(from_date, '%Y-%m-%d')
                except ValueError:
                    return JsonResponse({'error': 'Invalid from_date format'}, status=400)
            if to_date:
                try:
                    to_date_obj = datetime.strptime(to_date, '%Y-%m-%d')
                    date_filter['$lte'] = to_date_obj + timedelta(days=1) - timedelta(seconds=1)
                except ValueError:
                    return JsonResponse({'error': 'Invalid to_date format'}, status=400)
            billing_filter['investBillDate'] = date_filter

        billing_records = list(invest_billing_collection.find(billing_filter, {'_id': 0}))
        if not billing_records:
            return JsonResponse([], safe=False)

        # ── 2. Batch Refund Cache ─────────────────────────────────────────────
        # Build { investBillNo → set of refunded test_ids }
        invest_bill_nos = [
            r.get('investBillNo') for r in billing_records if r.get('investBillNo')
        ]

        refunded_test_ids = {}  # investBillNo → set of int test_ids

        if invest_bill_nos:
            refund_docs = refund_collection.find(
                {'investBillNo': {'$in': invest_bill_nos}, 'is_active': True},
                {'_id': 0, 'investBillNo': 1, 'item': 1}
            )
            for rdoc in refund_docs:
                bill_no = rdoc.get('investBillNo')
                items   = rdoc.get('item', [])
                if isinstance(items, str):
                    try:
                        items = json.loads(items)
                    except:
                        items = []
                if bill_no not in refunded_test_ids:
                    refunded_test_ids[bill_no] = set()
                for it in items:
                    # refund docs store item_id (not test_id)
                    tid = it.get('item_id') or it.get('test_id')
                    if tid is not None:
                        try:
                            refunded_test_ids[bill_no].add(int(tid))
                        except (ValueError, TypeError):
                            refunded_test_ids[bill_no].add(tid)

        # ── 3. Filter by billTypeNo and exclude refunded items ────────────────
        filtered_records = []
        for record in billing_records:
            try:
                items = record.get('item', [])
                if isinstance(items, str):
                    try:
                        items = json.loads(items)
                    except:
                        items = []
            except:
                items = []

            bill_no          = record.get('investBillNo', '')
            already_refunded = refunded_test_ids.get(bill_no, set())

            matched_items = []
            for i in items:
                # Must match billTypeNo
                if i.get('billTypeNo') != bill_type_no:
                    continue
                # Exclude if already refunded — billing items use item_id
                tid = i.get('item_id') or i.get('test_id')
                try:
                    tid_norm = int(tid) if tid is not None else None
                except (ValueError, TypeError):
                    tid_norm = tid
                if tid_norm in already_refunded:
                    continue
                matched_items.append(i)

            if not matched_items:
                continue

            record['_matched_items'] = matched_items
            filtered_records.append(record)

        if not filtered_records:
            return JsonResponse([], safe=False)

        # ── 4. Fetch existing reports ─────────────────────────────────────────
        bill_nos = [r['investBillNo'] for r in filtered_records if r.get('investBillNo')]
        report_filter = {
            'investBillNo': {'$in': bill_nos},
            'is_active': True
        }
        if hospital_code:
            report_filter['hospital_code'] = hospital_code
        if branch_code:
            report_filter['branch_code'] = branch_code

        ct_reports = list(ct_report_collection.find(report_filter, {'_id': 0}))

        report_map = {}
        for r in ct_reports:
            for field in ['date', 'slot_DateTime', 'created_date', 'lastmodified_date',
                          'approved_date', 'deleted_date']:
                if field in r and isinstance(r[field], datetime):
                    r[field] = r[field].isoformat()
            raw_item_id        = r.get('item_id')
            normalized_item_id = int(raw_item_id) if raw_item_id is not None else None
            report_map[(r.get('investBillNo'), normalized_item_id)] = r

        # ── 5. Fetch patients ─────────────────────────────────────────────────
        uhid_list = list({r['uhid'] for r in filtered_records if r.get('uhid')})
        patient_filter = {'uhid': {'$in': uhid_list}}
        if hospital_code:
            patient_filter['hospital_code'] = hospital_code
        if branch_code:
            patient_filter['branch_code'] = branch_code

        patients = list(patient_collection.find(
            patient_filter,
            {'_id': 0, 'uhid': 1, 'salutation': 1, 'firstName': 1, 'middleName': 1,
             'lastName': 1, 'age': 1, 'gender': 1}
        ))
        patient_map = {p['uhid']: p for p in patients}

        # ── 6. Batch Radiology Format Cache ──────────────────────────────────
        # Collect all unique item_ids across all matched items
        all_item_ids = set()
        for record in filtered_records:
            for item in record.get('_matched_items', []):
                tid = item.get('test_id') or item.get('item_id')
                if tid is not None:
                    try:
                        all_item_ids.add(int(tid))
                    except (ValueError, TypeError):
                        pass

        # format_map: item_id (int) → full format doc (_id removed)
        format_map = {}
        if all_item_ids:
            format_docs = radiology_format_collection.find(
                {
                    'item_id':    {'$in': list(all_item_ids)},
                    'billTypeNo': bill_type_no,
                    'is_active':  True
                }
            )
            for fdoc in format_docs:
                fdoc.pop('_id', None)
                # Serialize datetime fields inside format doc
                for field in ['last_modified_date']:
                    if field in fdoc and isinstance(fdoc[field], datetime):
                        fdoc[field] = fdoc[field].isoformat()
                fid = fdoc.get('item_id')
                if fid is not None:
                    try:
                        format_map[int(fid)] = fdoc
                    except (ValueError, TypeError):
                        pass

        # ── 7. Build result ───────────────────────────────────────────────────
        result = []
        for record in filtered_records:
            invest_bill_no = record.get('investBillNo')
            if not invest_bill_no:
                continue

            uhid    = record.get('uhid', '')
            patient = patient_map.get(uhid, {})
            gender  = patient.get('gender', '').strip().upper()

            # Normalise gender → format doc key
            if gender in ('M', 'MALE'):
                gender_key = 'male'
            elif gender in ('F', 'FEMALE'):
                gender_key = 'female'
            else:
                gender_key = 'male'   # safe fallback

            matched_items = record.get('_matched_items', [])

            base = record.copy()
            base.pop('_matched_items', None)
            base.pop('item', None)

            for field in ['investBillDate', 'created_date', 'lastmodified_date']:
                if field in base and isinstance(base[field], datetime):
                    base[field] = base[field].isoformat()

            base['salutation']  = patient.get('salutation',  '')
            base['firstName']   = patient.get('firstName',   '')
            base['middleName']  = patient.get('middleName',  '')
            base['lastName']    = patient.get('lastName',    '')
            base['age']         = patient.get('age',         None)
            base['gender']      = patient.get('gender',      '')

            for item in matched_items:
                raw_item_id = item.get('item_id') or item.get('test_id')
                item_id     = int(raw_item_id) if raw_item_id is not None else None

                item_name = item_name_map.get(item_id) or item.get('itemName', '')
                report    = report_map.get((invest_bill_no, item_id))

                row = base.copy()
                row['item_id']   = item_id
                row['itemName']  = item_name
                row['report']    = report
                row['hasReport'] = report.get('has_report', False) if report else False

                # ── Radiology format: all fields + gender-resolved titles ─────
                fmt_doc = format_map.get(item_id)
                if fmt_doc:
                    # All fields except the raw male/female arrays
                    fmt_base = {
                        k: v for k, v in fmt_doc.items()
                        if k not in ('male', 'female')
                    }
                    # Gender-matched titles array under a unified key
                    fmt_base['format_titles'] = fmt_doc.get(gender_key, [])
                    row['radiology_format'] = fmt_base
                else:
                    row['radiology_format'] = None

                result.append(row)

        return JsonResponse(result, safe=False)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'error': str(e)}, status=500)

    finally:
        client.close()

# ─── POST: Create scan report (with optional slot_DateTime) ───────────────────

@csrf_exempt
@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def create_scan_report(request):
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    collection = client['HMS']['hospital_radiologyreport']
    try:
        data          = request.data
        user_id       = data.get('auth-user-id', 'system')
        branch_code   = data.get('auth-branch-code', 'SHB001')
        outlet_code   = data.get('auth-outlet-code', 'OLET003')
        hospital_code = data.get('auth-hospital-code', 'SH001')
        invest_bill_no = data.get('investBillNo')

        try:
            item_id = int(data.get('item_id'))
        except (ValueError, TypeError):
            return JsonResponse({"error": "item_id must be a valid integer"}, status=400)

        # ── Parse dates ──────────────────────────────────────────────────────
        invest_bill_date = data.get('investBillDate')
        if invest_bill_date:
            try:
                date_value = datetime.fromisoformat(invest_bill_date.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                date_value = timezone.now()
        else:
            date_value = timezone.now()

        slot_dt = _parse_slot_datetime(data.get('slot_DateTime'))

        # ── Build valuedetails ───────────────────────────────────────────────
        sections = data.get('sections', [])
        valuedetails = {
            "device_id":    data.get('device_id', []),
            "approve":      False,
            "approve_time": None,
            "approve_by":   None,
            "value": [
                {
                    "title_id":    sec.get('title_id', ''),
                    "title_value": sec.get('value', ''),
                }
                for sec in sections
            ]
        }

        impression = data.get('impression', '')
        item_name  = data.get('itemName', '')
        bill_type_no = data.get('billTypeNo', '')

        # ── Check if a slot-only record exists (has_report=False) ────────────
        existing_slot = collection.find_one({
            'investBillNo': invest_bill_no,
            'item_id':      item_id,
            'is_active':    True,
            'has_report':   False,
        })

        if existing_slot:
            # ── PATCH: fill in the report on the existing slot record ─────────
            set_payload = {
                "impression":        impression,
                "valuedetails":      valuedetails,
                "has_report":        True,
                "lastmodified_by":   user_id,
                "lastmodified_date": timezone.now(),
            }
            if slot_dt:
                set_payload["slot_DateTime"] = slot_dt
            if item_name:
                set_payload["itemName"] = item_name
            if bill_type_no:
                set_payload["billTypeNo"] = bill_type_no

            collection.update_one(
                {"_id": existing_slot["_id"]},
                {"$set": set_payload}
            )
            updated = collection.find_one({"_id": existing_slot["_id"]})
            return JsonResponse({
                "id":           str(existing_slot["_id"]),
                "investBillNo": invest_bill_no,
                "message":      "Report updated on existing slot record",
                "report":       _serialize_report(updated),
            }, status=200)

        # ── Duplicate check: fully submitted report already exists ────────────
        existing_full = collection.find_one({
            'investBillNo': invest_bill_no,
            'item_id':      item_id,
            'is_active':    True,
            'has_report':   True,
        })
        if existing_full:
            return JsonResponse(
                {'error': f'A report already exists for Bill No {invest_bill_no}'},
                status=409
            )

        # ── POST: create new record ───────────────────────────────────────────
        ct_report = RadiologyReport.objects.create(
            date          = date_value,
            slot_DateTime = slot_dt,
            investBillNo  = invest_bill_no,
            itemName      = item_name,
            item_id       = item_id,
            impression    = impression,
            billTypeNo    = bill_type_no,
            valuedetails  = valuedetails,
            is_active     = True,
            has_report    = True,        # ✅ full report on create
            created_by    = user_id,
            branch_code   = branch_code,
            outlet_code   = outlet_code,
            hospital_code = hospital_code,
        )

        return JsonResponse({
            "id":           str(ct_report.id),
            "investBillNo": ct_report.investBillNo,
            "message":      "Report created successfully",
        }, status=201)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({"error": str(e)}, status=400)
    finally:
        client.close()
# ─── PATCH: Update slot_DateTime (and optionally impression) ──────────────────

@csrf_exempt
@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def update_slot_datetime(request, investBillNo, item_id):
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    collection = client['HMS']['hospital_radiologyreport']
    try:
        user_id   = request.data.get('auth-user-id', 'system')
        branch_code   = request.data.get('auth-branch-code', 'SHB001')
        outlet_code   = request.data.get('auth-outlet-code', 'OLET003')
        hospital_code = request.data.get('auth-hospital-code', 'SH001')
        raw_slot  = request.data.get('slot_DateTime')

        if not raw_slot:
            return JsonResponse({"error": "slot_DateTime is required"}, status=400)

        slot_dt = _parse_slot_datetime(raw_slot)
        if not slot_dt:
            return JsonResponse({"error": "Invalid slot_DateTime format."}, status=400)

        try:
            item_id_int = int(item_id)
        except (ValueError, TypeError):
            return JsonResponse({"error": "item_id must be a valid integer"}, status=400)

        # ── Try to find a slot-only record (has_report=False) ────────────────
        report = collection.find_one({
            'investBillNo': investBillNo,
            'item_id':      item_id_int,
            'is_active':    True,
            'has_report':   False,        # ✅ only update slot-only records
        })

        if report:
            # ── PATCH existing slot record ────────────────────────────────────
            update_fields = {
                "slot_DateTime":     slot_dt,
                "lastmodified_by":   user_id,
                "lastmodified_date": timezone.now(),
            }
            new_impression = request.data.get('impression')
            if new_impression:
                update_fields["impression"] = new_impression

            collection.update_one({"_id": report["_id"]}, {"$set": update_fields})
            updated = collection.find_one({"_id": report["_id"]})
            return JsonResponse(_serialize_report(updated), safe=False, status=200)

        else:
            # ── No slot record exists → create one with has_report=False ─────
            invest_bill_date = request.data.get('investBillDate')
            if invest_bill_date:
                try:
                    date_value = datetime.fromisoformat(invest_bill_date.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    date_value = timezone.now()
            else:
                date_value = timezone.now()

            ct_report = RadiologyReport.objects.create(
                date          = date_value,
                slot_DateTime = slot_dt,
                investBillNo  = investBillNo,
                itemName      = request.data.get('itemName', ''),
                item_id       = item_id_int,
                impression    = request.data.get('impression', ''),
                billTypeNo    = request.data.get('billTypeNo', ''),
                valuedetails  = {"device_id": [], "approve": False, "approve_time": None, "approve_by": None, "value": []},
                is_active     = True,
                has_report    = False,       # ✅ slot-only
                created_by    = user_id,
                branch_code   = branch_code,
                outlet_code   = outlet_code,
                hospital_code = hospital_code,
            )
            updated = collection.find_one({"investBillNo": investBillNo, "item_id": item_id_int, "is_active": True})
            return JsonResponse(_serialize_report(updated), safe=False, status=201)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({"error": str(e)}, status=500)
    finally:
        client.close()

# ─── PATCH: Approve ───────────────────────────────────────────────────────────

@csrf_exempt
@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def approve_scan_report(request, investBillNo, item_id):
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    collection = client['HMS']['hospital_radiologyreport']
    try:
        user_id = request.data.get('auth-user-id', 'system')
        item_id = int(item_id)
        report = collection.find_one(
            {'investBillNo': investBillNo, 'item_id': item_id, 'is_active': True}
        )
        if not report:
            return JsonResponse({"error": "Report not found"}, status=404)

        collection.update_one(
            {"_id": report["_id"]},
            {"$set": {"is_approved": True, "approved_by": user_id, "approved_date": timezone.now()}}
        )
        updated = collection.find_one({"_id": report["_id"]})
        return JsonResponse(_serialize_report(updated), safe=False, status=200)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)
    finally:
        client.close()


# ─── PATCH: Edit impression ───────────────────────────────────────────────────

@csrf_exempt
@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def edit_scan_report_impression(request, investBillNo, item_id):
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    collection = client['HMS']['hospital_radiologyreport']
    try:
        new_impression = request.data.get("impression")
        new_sections = request.data.get("sections")  # list of {title_id, value}
        user_id = request.data.get('auth-user-id', 'system')
        item_id = int(item_id)
        # At least one of impression or sections must be provided
        if not new_impression and not new_sections:
            return JsonResponse(
                {"error": "At least one of 'impression' or 'sections' is required"},
                status=400
            )

        report = collection.find_one(
            {'investBillNo': investBillNo, 'item_id': item_id, 'is_active': True}
        )
        if not report:
            return JsonResponse({"error": "Report not found"}, status=404)

        # ── Build $set payload ────────────────────────────────────────────────
        set_payload = {
            "lastmodified_by": user_id,
            "lastmodified_date": timezone.now(),
        }

        if new_impression:
            set_payload["impression"] = new_impression

        # Update only the title_value fields that were sent,
        # leaving untouched sections as-is in the DB.
        if new_sections and isinstance(new_sections, list):
            existing_value = report.get("valuedetails", {}).get("value", [])

            # Build a map of existing sections: title_id -> index
            existing_map = {
                item["title_id"]: idx
                for idx, item in enumerate(existing_value)
            }

            # Apply incoming changes
            for incoming in new_sections:
                title_id = incoming.get("title_id")
                new_value = incoming.get("value")

                if not title_id or new_value is None:
                    continue  # skip malformed entries

                if title_id in existing_map:
                    # Update existing section in-place
                    idx = existing_map[title_id]
                    existing_value[idx]["title_value"] = new_value
                else:
                    # Append brand-new section if title_id not found
                    existing_value.append({
                        "title_id": title_id,
                        "title_value": new_value,
                    })

            set_payload["valuedetails.value"] = existing_value

        collection.update_one(
            {"_id": report["_id"]},
            {"$set": set_payload}
        )

        updated = collection.find_one({"_id": report["_id"]})
        return JsonResponse(_serialize_report(updated), safe=False, status=200)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)
    finally:
        client.close()

# ─── PATCH: Soft delete ───────────────────────────────────────────────────────

@csrf_exempt
@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def soft_delete_scan_report(request, investBillNo, item_id):
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    collection = client['HMS']['hospital_radiologyreport']
    try:
        user_id = request.data.get('auth-user-id', 'system')
        item_id = int(item_id)
        report = collection.find_one(
            {'investBillNo': investBillNo, 'item_id': item_id, 'is_active': True}
        )
        if not report:
            return JsonResponse({"error": "Report not found"}, status=404)

        collection.update_one(
            {"_id": report["_id"]},
            {"$set": {"is_active": False, "deleted_by": user_id, "deleted_date": timezone.now()}}
        )
        return JsonResponse({"message": "Report deleted successfully"}, status=200)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)
    finally:
        client.close()


@api_view(['GET'])
# @permission_classes([HasRoleAndDataPermission])
def get_radiology_format(request):
    """
    GET /scan-reports/format/
    Query params:
        - billTypeNo  (required)
        - test_id     (required)
        - gender      (required: 'Male' or 'Female')
    Returns gender-specific fields + common fields from hospital_radiology_formats.
    """

    bill_type_no = request.GET.get('billTypeNo')
    test_id      = request.GET.get('test_id')
    gender       = request.GET.get('gender', '').strip().lower()   # 'male' or 'female'

    # ── Validation ────────────────────────────────────────────────────────────
    if not bill_type_no:
        return JsonResponse({'error': 'billTypeNo is required'}, status=400)
    if not test_id:
        return JsonResponse({'error': 'test_id is required'}, status=400)
    if gender not in ('male', 'female'):
        return JsonResponse(
            {'error': "gender must be 'Male' or 'Female'"},
            status=400
        )

    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    db     = client['HMS']
    collection = db['hospital_radiology_formats']

    try:
        # Convert test_id to int if stored as int in MongoDB
        try:
            test_id_query = int(test_id)
        except (ValueError, TypeError):
            test_id_query = test_id

        # ── Fetch document ────────────────────────────────────────────────────
        doc = collection.find_one(
            {
                'billTypeNo': bill_type_no,
                'item_id':    test_id_query,
                'is_active':  True,
            },
            {'_id': 0}   # exclude Mongo _id
        )

        if not doc:
            return JsonResponse(
                {'error': 'No active format found for given billTypeNo and test_id'},
                status=404
            )

        # ── Gender-specific field ─────────────────────────────────────────────
        gender_fields = doc.get(gender, [])   # 'male' or 'female' key

        # ── Common fields (everything except male/female arrays) ──────────────
        GENDER_KEYS   = {'male', 'female'}
        EXCLUDED_KEYS = {'last_modified_by', 'last_modified_date'}   # internal/audit — remove if you want them

        common_fields = {
            k: v
            for k, v in doc.items()
            if k not in GENDER_KEYS and k not in EXCLUDED_KEYS
        }

        # Serialize any datetime objects
        for key, value in common_fields.items():
            if isinstance(value, datetime):
                common_fields[key] = value.isoformat()

        # ── Build response ────────────────────────────────────────────────────
        response_data = {
            **common_fields,          # test_code, department, itemName, billTypeNo,
                                      # impression, shortcuts, device_id, TAT_Time, etc.
            'format': gender_fields,  # list of { title_id, title, title_value }
        }

        return JsonResponse(response_data, safe=False)

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

    finally:
        client.close()

@api_view(['GET'])
# @permission_classes([HasRoleAndDataPermission])
def get_employee_signature_by_id(request):
    employee_id = request.GET.get('employee_id')
    if not employee_id:
        return JsonResponse({'error': 'employee_id is required'}, status=400)

    try:
        mongo_client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        global_db = mongo_client.Global

        profile_collection = global_db.backend_diagnostics_profile
        designation_collection = global_db.backend_diagnostics_Designation
        fs = gridfs.GridFS(global_db)

        # ── Fetch profile ─────────────────────────────────────────────────
        profile = profile_collection.find_one({"employeeId": str(employee_id)})
        if not profile:
            return JsonResponse({'error': 'Employee not found'}, status=404)

        employee_name = profile.get("employeeName", "")
        registration_number = profile.get("registrationNumber", "")
        designation_code = profile.get("designation", "")

        # ── Fetch designation name ────────────────────────────────────────
        designation_name = ""
        if designation_code:
            desig_doc = designation_collection.find_one({"Designation_code": designation_code})
            if desig_doc:
                designation_name = desig_doc.get("designation", "")

        # ── Fetch signature image as base64 ───────────────────────────────
        signature_base64 = None
        signature_file_id = profile.get("signatureFileId")
        if signature_file_id:
            try:
                from bson import ObjectId
                import base64
                if isinstance(signature_file_id, str):
                    signature_file_id = ObjectId(signature_file_id)
                signature_file = fs.get(signature_file_id)
                signature_bytes = signature_file.read()
                signature_base64 = base64.b64encode(signature_bytes).decode('utf-8')
            except Exception as e:
                print(f"Error fetching signature: {str(e)}")

        return JsonResponse({
            "employeeId": employee_id,
            "employeeName": employee_name,
            "designation": designation_name,
            "registrationNumber": registration_number,
            "signatureBase64": signature_base64,
        })

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return JsonResponse({'error': str(e)}, status=500)