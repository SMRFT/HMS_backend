from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from ..models import Summary, CommunicationLog
from ..serializers import SummarySerializer
from django.shortcuts import render
from rest_framework.response import Response
from django.http import JsonResponse, HttpResponse
from rest_framework import status
from pymongo import MongoClient
from django.utils.timezone import now
from rest_framework.parsers import MultiPartParser, FormParser
from bson import Decimal128
from rest_framework.decorators import api_view, permission_classes
from django.views.decorators.csrf import csrf_exempt
from pymongo import MongoClient
import os, json, requests
from ..serializers import  Patient,PatientSerializer
from ..serializers import   PatientSerializer
from ..serializers import   VendorSerializer
from ..models import RadiologyReport
from django.views.decorators.http import require_http_methods
import logging
logger = logging.getLogger(__name__)
from pymongo import MongoClient
from datetime import datetime
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from pyauth.auth import HasRoleAndDataPermission
import json
from urllib.parse import unquote
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from pymongo import MongoClient
import os
from datetime import datetime
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
import base64
from bson import ObjectId
import gridfs

import re
from ..models import Summary, CommunicationLog, SummaryType, SummaryHeading
from ..serializers import SummarySerializer, SummaryTypeSerializer, SummaryHeadingSerializer

@api_view(['GET', 'POST'])
@permission_classes([HasRoleAndDataPermission])
def summary_type(request):
    """Get list of active summary types or create a new summary type in hospital_summarytype collection"""
    client = None
    try:
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        hms_db = client['HMS']
        summary_collection = hms_db['hospital_summarytype']

        if request.method == 'GET':
            summary_types = list(summary_collection.find(
                {},                           # fetch all records in db
                {"_id": 0, "summaryNo": 1, "summaryType": 1, "headings": 1, "is_active": 1}  # projection
            ))
            for st in summary_types:
                if 'headings' not in st or not isinstance(st['headings'], list):
                    st['headings'] = []
                else:
                    for h in st['headings']:
                        if isinstance(h, dict):
                            h['defaultValue'] = str(h.get('defaultValue') if h.get('defaultValue') is not None else (h.get('default_value') or ''))
                st['is_active'] = bool(st.get('is_active', True))
            return Response(summary_types, status=status.HTTP_200_OK)

        elif request.method == 'POST':
            summary_type_val = (request.data.get('summaryType') or '').strip()
            if not summary_type_val:
                return Response({"error": "Summary type is required"}, status=status.HTTP_400_BAD_REQUEST)

            # Case-insensitive duplicate check
            existing = summary_collection.find_one({
                "summaryType": {"$regex": f"^{re.escape(summary_type_val)}$", "$options": "i"},
                "is_active": True
            })
            if existing:
                return Response({"error": f"Summary type '{summary_type_val}' already exists"}, status=status.HTTP_400_BAD_REQUEST)

            # Auto-increment summaryNo
            all_types = list(summary_collection.find({}, {"summaryNo": 1, "_id": 0}))
            numbers = []
            for item in all_types:
                s_no = str(item.get('summaryNo', '')).strip()
                digits = re.findall(r'\d+', s_no)
                if digits:
                    numbers.append(int(digits[0]))
            next_num = max(numbers) + 1 if numbers else 1
            next_summary_no = f"{next_num:02d}"

            created_by = request.data.get('auth-user-id', "system")
            branch_code = request.data.get('auth-branch-code', "system")
            hospital_code = request.data.get('auth-hospital-code', "system")
            outlet_code = request.data.get('auth-outlet-code', "system")

            headings = request.data.get('headings', [])
            clean_headings = []
            if isinstance(headings, list):
                for idx, h in enumerate(headings, start=1):
                    if isinstance(h, dict):
                        def_val = str(h.get('defaultValue') if h.get('defaultValue') is not None else (h.get('default_value') or ''))
                        clean_headings.append({
                            "order_id": int(h.get('order_id', idx)),
                            "headingNo": str(h.get('headingNo', '')),
                            "heading": str(h.get('heading', '')).strip(),
                            "defaultValue": def_val.strip()
                        })
                    elif isinstance(h, str) and h.strip():
                        clean_headings.append({
                            "order_id": idx,
                            "headingNo": "",
                            "heading": h.strip(),
                            "defaultValue": ""
                        })

            now_dt = datetime.utcnow()
            new_doc = {
                "summaryNo": next_summary_no,
                "summaryType": summary_type_val,
                "headings": clean_headings,
                "is_active": True,
                "created_by": created_by,
                "created_date": now_dt,
                "lastmodified_by": None,
                "lastmodified_date": None,
                "branch_code": branch_code,
                "hospital_code": hospital_code,
                "outlet_code": outlet_code,
            }
            summary_collection.insert_one(new_doc)

            return Response({
                "message": "Summary type created successfully",
                "data": {
                    "summaryNo": next_summary_no,
                    "summaryType": summary_type_val,
                    "headings": clean_headings,
                    "is_active": True,
                }
            }, status=status.HTTP_201_CREATED)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    finally:
        if client:
            client.close()


@api_view(['PUT', 'POST'])
@permission_classes([HasRoleAndDataPermission])
def update_summary_type(request, summary_no):
    """Update summary type name, headings, or is_active by summaryNo"""
    client = None
    try:
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        hms_db = client['HMS']
        summary_collection = hms_db['hospital_summarytype']

        modified_by = request.data.get('auth-user-id', "system")
        set_payload = {
            "lastmodified_by": modified_by,
            "lastmodified_date": datetime.utcnow()
        }

        if 'summaryType' in request.data:
            summary_type_val = (request.data.get('summaryType') or '').strip()
            if not summary_type_val:
                return Response({"error": "Summary type name is required"}, status=status.HTTP_400_BAD_REQUEST)

            # Duplicate check excluding current
            existing = summary_collection.find_one({
                "summaryNo": {"$ne": str(summary_no)},
                "summaryType": {"$regex": f"^{re.escape(summary_type_val)}$", "$options": "i"},
                "is_active": True
            })
            if existing:
                return Response({"error": f"Summary type '{summary_type_val}' already exists"}, status=status.HTTP_400_BAD_REQUEST)
            set_payload["summaryType"] = summary_type_val

        if 'headings' in request.data:
            headings = request.data.get('headings') or []
            clean_headings = []
            if isinstance(headings, list):
                for idx, h in enumerate(headings, start=1):
                    if isinstance(h, dict):
                        def_val = str(h.get('defaultValue') if h.get('defaultValue') is not None else (h.get('default_value') or ''))
                        clean_headings.append({
                            "order_id": int(h.get('order_id', idx)),
                            "headingNo": str(h.get('headingNo', '')),
                            "heading": str(h.get('heading', '')).strip(),
                            "defaultValue": def_val.strip()
                        })
                    elif isinstance(h, str) and h.strip():
                        clean_headings.append({
                            "order_id": idx,
                            "headingNo": "",
                            "heading": h.strip(),
                            "defaultValue": ""
                        })
            set_payload["headings"] = clean_headings

        if 'is_active' in request.data:
            set_payload["is_active"] = bool(request.data.get('is_active'))

        res = summary_collection.update_one(
            {"summaryNo": str(summary_no)},
            {"$set": set_payload}
        )

        if res.matched_count == 0:
            return Response({"error": "Summary type not found"}, status=status.HTTP_404_NOT_FOUND)

        return Response({"message": "Summary type updated successfully"}, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if client:
            client.close()


@api_view(['DELETE', 'POST'])
@permission_classes([HasRoleAndDataPermission])
def delete_summary_type(request, summary_no):
    """Soft delete summary type by summaryNo"""
    client = None
    try:
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        hms_db = client['HMS']
        summary_collection = hms_db['hospital_summarytype']

        modified_by = request.data.get('auth-user-id', "system")
        res = summary_collection.update_one(
            {"summaryNo": str(summary_no)},
            {"$set": {
                "is_active": False,
                "lastmodified_by": modified_by,
                "lastmodified_date": datetime.utcnow()
            }}
        )

        if res.matched_count == 0:
            return Response({"error": "Summary type not found"}, status=status.HTTP_404_NOT_FOUND)

        return Response({"message": "Summary type deleted successfully"}, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if client:
            client.close()


@api_view(['GET', 'POST'])
@permission_classes([HasRoleAndDataPermission])
def summary_heading(request):
    """Get list of active headings or create a new heading in hospital_summaryheading collection"""
    client = None
    try:
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        hms_db = client['HMS']
        heading_collection = hms_db['hospital_summaryheading']

        if request.method == 'GET':
            headings = list(heading_collection.find(
                {},                           # fetch all in db
                {"_id": 0, "headingNo": 1, "heading": 1, "is_active": 1}      # projection
            ))
            for h in headings:
                h['is_active'] = bool(h.get('is_active', True))
            return Response(headings, status=status.HTTP_200_OK)

        elif request.method == 'POST':
            heading_val = (request.data.get('heading') or '').strip()
            if not heading_val:
                return Response({"error": "Heading is required"}, status=status.HTTP_400_BAD_REQUEST)

            # Case-insensitive duplicate check
            existing = heading_collection.find_one({
                "heading": {"$regex": f"^{re.escape(heading_val)}$", "$options": "i"},
                "is_active": True
            })
            if existing:
                return Response({"error": f"Heading '{heading_val}' already exists"}, status=status.HTTP_400_BAD_REQUEST)

            # Auto-increment headingNo
            all_headings = list(heading_collection.find({}, {"headingNo": 1, "_id": 0}))
            numbers = []
            for item in all_headings:
                h_no = str(item.get('headingNo', '')).strip()
                digits = re.findall(r'\d+', h_no)
                if digits:
                    numbers.append(int(digits[0]))
            next_num = max(numbers) + 1 if numbers else 1
            next_heading_no = f"{next_num:02d}"

            created_by = request.data.get('auth-user-id', "system")
            branch_code = request.data.get('auth-branch-code', "system")
            hospital_code = request.data.get('auth-hospital-code', "system")
            outlet_code = request.data.get('auth-outlet-code', "system")

            now_dt = datetime.utcnow()
            new_doc = {
                "headingNo": next_heading_no,
                "heading": heading_val,
                "is_active": True,
                "created_by": created_by,
                "created_date": now_dt,
                "lastmodified_by": None,
                "lastmodified_date": None,
                "branch_code": branch_code,
                "hospital_code": hospital_code,
                "outlet_code": outlet_code,
            }
            heading_collection.insert_one(new_doc)

            return Response({
                "message": "Summary heading created successfully",
                "data": {
                    "headingNo": next_heading_no,
                    "heading": heading_val,
                    "is_active": True,
                }
            }, status=status.HTTP_201_CREATED)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    finally:
        if client:
            client.close()


@api_view(['PUT', 'POST'])
@permission_classes([HasRoleAndDataPermission])
def update_summary_heading(request, heading_no):
    """Update heading name or is_active by headingNo"""
    client = None
    try:
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        hms_db = client['HMS']
        heading_collection = hms_db['hospital_summaryheading']

        modified_by = request.data.get('auth-user-id', "system")
        set_payload = {
            "lastmodified_by": modified_by,
            "lastmodified_date": datetime.utcnow()
        }

        if 'heading' in request.data:
            heading_val = (request.data.get('heading') or '').strip()
            if not heading_val:
                return Response({"error": "Heading name is required"}, status=status.HTTP_400_BAD_REQUEST)

            # Duplicate check excluding current
            existing = heading_collection.find_one({
                "headingNo": {"$ne": str(heading_no)},
                "heading": {"$regex": f"^{re.escape(heading_val)}$", "$options": "i"},
                "is_active": True
            })
            if existing:
                return Response({"error": f"Heading '{heading_val}' already exists"}, status=status.HTTP_400_BAD_REQUEST)
            set_payload["heading"] = heading_val

        if 'is_active' in request.data:
            set_payload["is_active"] = bool(request.data.get('is_active'))

        res = heading_collection.update_one(
            {"headingNo": str(heading_no)},
            {"$set": set_payload}
        )

        if res.matched_count == 0:
            return Response({"error": "Heading not found"}, status=status.HTTP_404_NOT_FOUND)

        # Also sync heading name in summary types that include this heading
        if 'heading' in set_payload:
            try:
                hms_db['hospital_summarytype'].update_many(
                    {"headings.headingNo": str(heading_no)},
                    {"$set": {"headings.$[elem].heading": set_payload['heading']}},
                    array_filters=[{"elem.headingNo": str(heading_no)}]
                )
            except Exception as sync_err:
                logger.warning(f"Failed to sync heading update to summary types: {sync_err}")

        return Response({"message": "Heading updated successfully"}, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if client:
            client.close()


@api_view(['DELETE', 'POST'])
@permission_classes([HasRoleAndDataPermission])
def delete_summary_heading(request, heading_no):
    """Soft delete heading by headingNo"""
    client = None
    try:
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        hms_db = client['HMS']
        heading_collection = hms_db['hospital_summaryheading']

        modified_by = request.data.get('auth-user-id', "system")
        res = heading_collection.update_one(
            {"headingNo": str(heading_no)},
            {"$set": {
                "is_active": False,
                "lastmodified_by": modified_by,
                "lastmodified_date": datetime.utcnow()
            }}
        )

        if res.matched_count == 0:
            return Response({"error": "Heading not found"}, status=status.HTTP_404_NOT_FOUND)

        return Response({"message": "Heading deleted successfully"}, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if client:
            client.close()


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def summary_clinical_notes(request):
    """
    Get list of active summary clinical notes titles from hospital_summary_clinicalNotes collection sorted by title_no
    """
    client = None
    try:
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        hms_db = client['HMS']
        notes_collection = hms_db['hospital_summary_clinicalNotes']

        notes = list(notes_collection.find(
            {"is_active": True},
            {"_id": 0, "title_no": 1, "title_name": 1, "is_active": 1}
        ))

        def sort_key(item):
            try:
                return int(item.get('title_no', 0))
            except (ValueError, TypeError):
                return 9999

        notes.sort(key=sort_key)
        return Response(notes, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error fetching summary clinical notes titles: {str(e)}")
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if client:
            client.close()



from datetime import datetime

def enrich_summary_type_and_heading(summaries, hms_db):
    """
    Resolves summaryType name from summaryNo (and summaryNo from summaryType)
    and heading name from headingNo (and headingNo from heading).
    """
    if not summaries:
        return summaries

    is_single = isinstance(summaries, dict)
    items = [summaries] if is_single else summaries

    type_map = {}
    type_rev_map = {}
    heading_map = {}
    heading_rev_map = {}

    try:
        types = list(hms_db['hospital_summarytype'].find({}, {"_id": 0, "summaryNo": 1, "summaryType": 1}))
        for t in types:
            s_no = str(t.get('summaryNo', '')).strip()
            s_type = str(t.get('summaryType', '')).strip()
            if s_no and s_type:
                type_map[s_no] = s_type
                type_rev_map[s_type.upper()] = s_no

        headings = list(hms_db['hospital_summaryheading'].find({}, {"_id": 0, "headingNo": 1, "heading": 1}))
        for h in headings:
            h_no = str(h.get('headingNo', '')).strip()
            h_val = str(h.get('heading', '')).strip()
            if h_no and h_val:
                heading_map[h_no] = h_val
                heading_rev_map[h_val.upper()] = h_no
    except Exception as e:
        logger.warning(f"Error fetching summary type/heading mappings: {e}")

    for s in items:
        # summaryType <-> summaryNo
        cur_no = str(s.get('summaryNo') or '').strip()
        cur_type = str(s.get('summaryType') or '').strip()
        if cur_no and cur_no in type_map:
            s['summaryType'] = type_map[cur_no]
            s['summaryNo'] = cur_no
        elif cur_type and cur_type.upper() in type_rev_map:
            s['summaryNo'] = type_rev_map[cur_type.upper()]
        
        # Preserve custom heading input string; only fallback if heading is empty
        cur_h_no = str(s.get('headingNo') or '').strip()
        cur_h_val = str(s.get('heading') or '').strip()
        if not cur_h_val and cur_h_no and cur_h_no in heading_map:
            s['heading'] = heading_map[cur_h_no]

    return items[0] if is_single else summaries


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_summaries(request):
    client = None
    try:
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        hms_db = client['HMS']
        summary_collection  = hms_db['hospital_summary']
        patient_collection  = hms_db['hospital_patient']

        # ✅ Get auth codes
        branch_code   = request.data.get("auth-branch-code",   "system")
        hospital_code = request.data.get("auth-hospital-code", "system")

        # ✅ Base filter
        query = {"is_active": True}

        # ✅ Apply hospital + branch filter
        if hospital_code:
            query["hospital_code"] = hospital_code
        if branch_code:
            query["branch_code"] = branch_code

        # ── Date filter ─────────────────────────
        from_date = request.query_params.get('fromDate', '').strip()
        to_date   = request.query_params.get('toDate', '').strip()

        if from_date or to_date:
            date_filter = {}
            if from_date:
                date_filter['$gte'] = datetime.strptime(from_date, '%Y-%m-%d')
            if to_date:
                to_dt = datetime.strptime(to_date, '%Y-%m-%d')
                date_filter['$lte'] = to_dt.replace(hour=23, minute=59, second=59)
            query['date'] = date_filter

        # ── Summary type filter (supports summaryType text or summaryNo) ─────────────────
        summary_type = request.query_params.get('summaryType', '').strip()
        if summary_type:
            matching_nos = [t['summaryNo'] for t in hms_db['hospital_summarytype'].find(
                {"summaryType": {'$regex': summary_type, '$options': 'i'}},
                {"_id": 0, "summaryNo": 1}
            ) if t.get('summaryNo')]
            query['$or'] = [
                {'summaryType': {'$regex': summary_type, '$options': 'i'}},
                {'summaryNo': {'$in': matching_nos}},
                {'summaryNo': summary_type}
            ]

        print("SUMMARY QUERY:", query)  # debug

        summaries = list(summary_collection.find(query, {"_id": 0}))

        if summaries:
            # ── Enrich summaryType and heading from masters ─────────────────
            enrich_summary_type_and_heading(summaries, hms_db)

            # ── Batch patient fetch ─────────────────
            uhids = list({s['uhid'] for s in summaries if s.get('uhid')})

            patient_query = {"uhid": {"$in": uhids}}

            # ✅ Apply SAME hospital + branch filter to patient
            if hospital_code:
                patient_query["hospital_code"] = hospital_code
            if branch_code:
                patient_query["branch_code"] = branch_code

            patients = patient_collection.find(
                patient_query,
                {"_id": 0, "uhid": 1, "salutation": 1, "firstName": 1, "lastName": 1}
            )

            # Map
            patient_map = {}
            for p in patients:
                full_name = f"{p.get('salutation', '')} {p.get('firstName', '')} {p.get('lastName', '')}".strip()
                patient_map[p['uhid']] = full_name

            # ── Batch admission fetch for is_high_risk ──
            ip_nos = list({str(s.get('ipNo')).strip() for s in summaries if s.get('ipNo')})
            adm_map = {}
            if ip_nos:
                adm_query = {"ipNumber": {"$in": ip_nos}}
                if hospital_code:
                    adm_query["hospital_code"] = hospital_code
                if branch_code:
                    adm_query["branch_code"] = branch_code
                for adm in hms_db['hospital_admission'].find(
                    adm_query,
                    {"_id": 0, "ipNumber": 1, "is_high_risk": 1, "high_risk_reason": 1, "high_risk_date": 1}
                ):
                    adm_map[str(adm.get('ipNumber'))] = adm

            # Attach names, high risk flags, and convert approve_time to IST (+5:30)
            from datetime import timezone, timedelta
            from .dbcollection import get_employee_name_by_id, resolve_created_by_name
            IST = timezone(timedelta(hours=5, minutes=30))

            # Batch employee name resolution from Global.backend_diagnostics_profile
            emp_ids = set()
            for s in summaries:
                if s.get('created_by'):
                    emp_ids.add(str(s['created_by']).strip())
                if s.get('approved_by'):
                    emp_ids.add(str(s['approved_by']).strip())

            emp_name_map = {}
            for eid in emp_ids:
                if eid:
                    name = resolve_created_by_name(eid)
                    if name:
                        emp_name_map[eid] = name

            for s in summaries:
                uhid = s.get('uhid', '')
                s['patient'] = patient_map.get(uhid, s.get('patient', ''))
                adm_info = adm_map.get(str(s.get('ipNo', '')).strip(), {})
                s['is_high_risk'] = bool(adm_info.get('is_high_risk', False))
                s['high_risk_reason'] = adm_info.get('high_risk_reason') or ''
                hr_d = adm_info.get('high_risk_date')
                s['high_risk_date'] = hr_d.isoformat() if hasattr(hr_d, 'isoformat') else str(hr_d or '')

                cb = str(s.get('created_by') or '').strip()
                s['created_by_name'] = emp_name_map.get(cb) or resolve_created_by_name(cb)

                ab = str(s.get('approved_by') or '').strip()
                s['approved_by_name'] = emp_name_map.get(ab) or resolve_created_by_name(ab)

                ap = s.get('approve_time')
                if ap:
                    if isinstance(ap, str):
                        try:
                            ap = datetime.fromisoformat(ap.replace("Z", "+00:00"))
                        except Exception:
                            pass
                    if isinstance(ap, datetime):
                        if ap.tzinfo is None:
                            ap = ap.replace(tzinfo=timezone.utc)
                        s['approve_time'] = ap.astimezone(IST).isoformat()

        return Response(summaries, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    finally:
        if client:
            client.close()


def sort_fields_data_by_summary_type(fields_data, summary_no=None, summary_type=None, db=None):
    """Sort fieldsData array according to the order_id of hospital_summarytype.headings."""
    if not isinstance(fields_data, list) or len(fields_data) <= 1 or db is None:
        return fields_data
    try:
        st = None
        if summary_no:
            st = db['hospital_summarytype'].find_one({"summaryNo": str(summary_no).strip()})
        if not st and summary_type:
            st = db['hospital_summarytype'].find_one({
                "summaryType": {"$regex": f"^{re.escape(str(summary_type).strip())}$", "$options": "i"}
            })
        if not st or not isinstance(st.get('headings'), list):
            return fields_data

        sorted_headings = sorted(
            st['headings'],
            key=lambda x: (int(x.get('order_id', 0)) if isinstance(x, dict) and str(x.get('order_id', '')).isdigit() else 0)
        )
        order_map = {}
        for idx, h in enumerate(sorted_headings):
            h_name = h.get('heading') if isinstance(h, dict) else str(h)
            if h_name:
                order_map[h_name.strip().upper()] = idx

        def get_sort_key(entry):
            if isinstance(entry, dict):
                k = str(entry.get('key', '')).strip().upper()
                return order_map.get(k, 99999)
            return 99999

        fields_data.sort(key=get_sort_key)
    except Exception as e:
        logger.warning(f"Error sorting fieldsData: {e}")
    return fields_data


@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def create_summary(request):
    data = request.data.copy()

    for dt_field in ('surgeryDate', 'nextReviewDate', 'doa', 'dod', 'doaTime', 'dodTime', 'date'):
        val = data.get(dt_field)
        if val == '' or val is None or (isinstance(val, str) and not val.strip()):
            data[dt_field] = None
        elif dt_field == 'date' and val:
            data['date'] = str(val)[:10]

    # Resolve summaryNo and headingNo if names were passed
    summary_no = (data.get('summaryNo') or '').strip()
    heading_no = (data.get('headingNo') or '').strip()

    if not summary_no and data.get('summaryType'):
        try:
            client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
            hms_db = client['HMS']
            match_t = hms_db['hospital_summarytype'].find_one({
                "summaryType": {"$regex": f"^{re.escape(str(data['summaryType']).strip())}$", "$options": "i"}
            })
            if match_t:
                summary_no = match_t.get('summaryNo', '')
            client.close()
        except Exception as e:
            logger.warning(f"Error resolving summaryNo: {e}")

    heading_val = (data.get('heading') or '').strip()
    data['heading'] = heading_val
    data['summaryNo'] = summary_no
    # summaryType is normalized by summaryNo, heading is input text, headingNo is not used
    data.pop('summaryType', None)
    data.pop('headingNo', None)

    # Sort fieldsData by summary type headings order if present
    if 'fieldsData' in data and isinstance(data['fieldsData'], list):
        try:
            client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
            db = client['HMS']
            data['fieldsData'] = sort_fields_data_by_summary_type(
                data['fieldsData'],
                summary_no=summary_no,
                summary_type=request.data.get('summaryType'),
                db=db
            )
            client.close()
        except Exception as e:
            logger.warning(f"Error sorting fieldsData in create_summary: {e}")

    serializer = SummarySerializer(data=data)
    if serializer.is_valid():
        ip_no = serializer.validated_data.get('ipNo')

        if Summary.objects.filter(ipNo=ip_no).exists():
            return Response(
                {"error": f"Summary already exists for ipNo: {ip_no}"},
                status=status.HTTP_409_CONFLICT
            )

        created_by    = request.data.get('auth-user-id', "system")
        branch_code   = request.data.get('auth-branch-code', "system")
        hospital_code = request.data.get('auth-hospital-code', "system")

        instance = serializer.save(
            branch_code=branch_code,
            hospital_code=hospital_code,
            created_by=created_by,
            created_date=datetime.utcnow()
        )

        # ── After ORM save, fix fieldsData and ensure summaryNo/heading in MongoDB ──
        raw_fields = request.data.get('fieldsData', [])
        if isinstance(raw_fields, str):
            try:
                raw_fields = json.loads(raw_fields)
            except (json.JSONDecodeError, ValueError):
                raw_fields = []

        if isinstance(raw_fields, list):
            fields_array = [
                f for f in raw_fields
                if isinstance(f, dict)
                and f.get('key') not in (None, '', 'undefined')
                and f.get('value', '') != ''
            ]
        else:
            fields_array = []

        try:
            client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
            db = client['HMS']
            patch_doc = {
                "summaryNo": summary_no,
                "heading": heading_val,
                "explainedBy": (data.get('explainedBy') or '').strip(),
                "explainedTo": (data.get('explainedTo') or '').strip(),
                "created_by": created_by,
            }
            if fields_array:
                fields_array = sort_fields_data_by_summary_type(
                    fields_array,
                    summary_no=summary_no,
                    summary_type=request.data.get('summaryType'),
                    db=db
                )
                patch_doc["fieldsData"] = fields_array
            
            db['hospital_summary'].update_one(
                {"ipNo": ip_no},
                {
                    "$set": patch_doc,
                    "$unset": {"summaryType": "", "headingNo": ""}
                }
            )
            client.close()
        except Exception as e:
            logger.warning(f"Mongo patch failed for {ip_no}: {e}")

        return Response(
            {"message": "Summary created successfully", "ipNo": instance.ipNo},
            status=status.HTTP_201_CREATED
        )

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)



@require_http_methods(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_patient_investigations(request, ip_no):
    client = None
    try:
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        hms_db = client['HMS']
        investbilling_collection      = hms_db['hospital_investbilling']
        investigationprice_collection = hms_db['hospital_investigationprice']
        radiology_collection          = hms_db['hospital_radiologyreport']  # direct mongo collection

        # ── Step 1: Get investBillNos for this IP ────────────────────────────
        invest_bills = list(investbilling_collection.find(
            {'ipNumber': ip_no, 'is_active': True},
            {'investBillNo': 1, '_id': 0}
        ))        

        if not invest_bills:
            return JsonResponse([], safe=False)

        invest_bill_nos = [b['investBillNo'] for b in invest_bills]       

        # ── Step 2: Query RadiologyReport directly via MongoDB ───────────────
        radiology_reports = list(radiology_collection.find(
            {
                'investBillNo': {'$in': invest_bill_nos},
                'is_active': True
            },
            {
                'investBillNo': 1,
                'billTypeNo': 1,
                'itemName': 1,
                'impression': 1,
                'is_approved': 1,
                'date': 1,
                '_id': 0
            }
        ))       

        if not radiology_reports:
            return JsonResponse([], safe=False)

       # ── Step 3: Get BillType labels from hospital_investigationprice ──────
        bill_type_nos = list({r['billTypeNo'] for r in radiology_reports})       

        price_records = list(investigationprice_collection.find(
            {'billTypeNo': {'$in': bill_type_nos}, 'is_active': True},  # added is_active
            {'billTypeNo': 1, 'BillType': 1, '_id': 0}
        ))       

        bill_type_label = {p['billTypeNo']: p['BillType'] for p in price_records}

        # ── Step 4: Build final response ──────────────────────────────────────
        all_reports = []
        for report in radiology_reports:
            bill_type_no = report.get('billTypeNo', '')
            report_type  = bill_type_label.get(bill_type_no, bill_type_no)

            all_reports.append({
                'reportType':    report_type,
                'investigation': report.get('itemName', ''),
                'impression':    report.get('impression', ''),
                'is_approved':   report.get('is_approved', False),
                'investBillNo':  report.get('investBillNo', ''),
                'billTypeNo':    bill_type_no,
            })
       
        return JsonResponse(all_reports, safe=False)

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return JsonResponse({'error': str(e), 'type': type(e).__name__}, status=500)

    finally:
        if client:
            client.close()   

@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def approve_summary(request, ip_no):
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    db = client['HMS']
    collection = db['hospital_summary']

    try:
        created_by = request.data.get('auth-user-id', "system")
        now_dt = datetime.utcnow()
        
        # Find the summary by IP number and update
        result = collection.update_one(
            {"ipNo": ip_no},  # Query to find the document by IP No
            {"$set": {
                "approve": True,
                "approved_by": created_by,
                "approve_time": now_dt  # Store as Date/Time object in MongoDB (ISODate)
            }}
        )
        
        # Check if the document was updated
        if result.matched_count > 0:
            return Response({"message": "Summary approved successfully"}, status=status.HTTP_200_OK)
        else:
            return Response({"error": "Summary not found"}, status=status.HTTP_404_NOT_FOUND)
    
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['PATCH'])  # Changed from DELETE to PATCH
@permission_classes([HasRoleAndDataPermission])
def delete_summary(request, ip_no):
    # MongoDB connection setup
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    db = client['HMS']
    collection = db['hospital_summary']
    
    try:
        # Get the user who is performing the soft delete (if available)
        created_by = request.data.get('auth-user-id', "system")

        
        # Update the document to set is_active to False
        result = collection.update_one(
            {"ipNo": ip_no, "is_active": True},  # Only update if currently active
            {
                "$set": {
                    "is_active": False,
                    "deleted_by": created_by,
                    "deleted_date": datetime.now()
                }
            }
        )
        
        # Check if the document was updated
        if result.matched_count > 0:
            return Response(
                {"message": "Summary deleted successfully"}, 
                status=status.HTTP_200_OK
            )
        else:
            return Response(
                {"error": "Summary not found or already deleted"}, 
                status=status.HTTP_404_NOT_FOUND
            )
    
    except Exception as e:
        return Response(
            {"error": str(e)}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    finally:
        client.close()  # Always close the MongoDB connection
    

from urllib.parse import unquote

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def check_summary_exists(request, ip_no):
    """Check if a discharge summary already exists for the given ipNo in hospital_summary collection"""
    client = None
    try:
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        hms_db = client['HMS']
        summary_collection = hms_db['hospital_summary']

        decoded_ip_no = unquote(ip_no).strip()
        if not decoded_ip_no:
            return Response({"exists": False, "message": "No IP number provided"}, status=status.HTTP_400_BAD_REQUEST)

        branch_code   = request.data.get("auth-branch-code", "system")
        hospital_code = request.data.get("auth-hospital-code", "system")

        query = {
            "ipNo": {"$regex": f"^{re.escape(decoded_ip_no)}$", "$options": "i"},
            "is_active": {"$ne": False}
        }
        if hospital_code and hospital_code != "system":
            query["hospital_code"] = hospital_code
        if branch_code and branch_code != "system":
            query["branch_code"] = branch_code

        existing = summary_collection.find_one(
            query,
            {"_id": 0, "ipNo": 1, "patient": 1, "date": 1, "approve": 1, "summaryNo": 1}
        )

        if not existing:
            # Fallback across branch/hospital codes in case codes were different or unset
            existing = summary_collection.find_one(
                {
                    "ipNo": {"$regex": f"^{re.escape(decoded_ip_no)}$", "$options": "i"},
                    "is_active": {"$ne": False}
                },
                {"_id": 0, "ipNo": 1, "patient": 1, "date": 1, "approve": 1, "summaryNo": 1}
            )

        if existing:
            return Response({
                "exists": True,
                "message": "Discharge Summary already exist with this IP number",
                "data": existing
            }, status=status.HTTP_200_OK)
        else:
            return Response({
                "exists": False,
                "message": "No summary exists for this IP number"
            }, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if client:
            client.close()


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_editsummary(request, ip_no):
    from datetime import timezone, timedelta

    client = None
    try:
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        db = client['HMS']
        summary_collection = db['hospital_summary']
        patient_collection = db['hospital_patient']

        decoded_ip_no = unquote(ip_no)
        summary = summary_collection.find_one({"ipNo": decoded_ip_no})

        if not summary:
            return Response({"error": "Summary not found"}, status=status.HTTP_404_NOT_FOUND)

        summary['_id'] = str(summary['_id'])

        IST = timezone(timedelta(hours=5, minutes=30))

        def fmt_date_only(value):
            if not value:
                return None
            if isinstance(value, str):
                return value[:10]
            if isinstance(value, datetime):
                return value.replace(tzinfo=timezone.utc).astimezone(IST).strftime("%Y-%m-%d")
            return None

        def fmt_datetime(value):
            """Full datetime fields — convert UTC to IST."""
            if not value:
                return None, None
            if isinstance(value, str):
                try:
                    value = datetime.fromisoformat(value.replace("Z", "+00:00"))
                except ValueError:
                    return value, None
            if isinstance(value, datetime):
                value = value.replace(tzinfo=timezone.utc).astimezone(IST)
                return value.strftime("%Y-%m-%d"), value.strftime("%H:%M")
            return None, None

        def fmt_time_only(value):
            """Time-only fields stored as datetime epoch — extract HH:MM without timezone shift."""
            if not value:
                return None
            if isinstance(value, datetime):
                return value.strftime("%H:%M")  # no IST conversion
            if isinstance(value, str):
                try:
                    value = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    return value.strftime("%H:%M")
                except ValueError:
                    return value
            return None

        # ── Summary created date ──
        date_str, date_time_str = fmt_datetime(summary.get('date'))
        summary['date']     = date_str
        summary['dateTime'] = date_time_str

        # ── DOA (plain string already) ──
        summary['doa'] = summary.get('doa', '')

        # ── DOA Time (time-only epoch — no IST shift) ──
        summary['doaTime'] = fmt_time_only(summary.get('doaTime')) or ""

        # ── DOD ──
        summary['dod'] = fmt_date_only(summary.get('dod'))

        # ── DOD Time (time-only epoch — no IST shift) ──
        summary['dodTime'] = fmt_time_only(summary.get('dodTime')) or "17:00"

        # ── Surgery Date ──
        summary['surgeryDate'] = fmt_date_only(summary.get('surgeryDate'))

        # ── Next Review Date ──
        summary['nextReviewDate'] = fmt_date_only(summary.get('nextReviewDate'))

        # ── Approve time ──
        ap_date, ap_time = fmt_datetime(summary.get('approve_time'))
        summary['approve_time']      = ap_date
        summary['approve_time_time'] = ap_time

        # ── Patient details from hospital_patient ──
        uhid = summary.get('uhid', '')
        if uhid:
            patient = patient_collection.find_one(
                {"uhid": uhid},
                {"_id": 0, "salutation": 1, "firstName": 1, "lastName": 1,
                 "age": 1, "gender": 1, "area": 1, "city": 1, "state": 1}
            )
            if patient:
                full_name = f"{patient.get('salutation', '')} {patient.get('firstName', '')} {patient.get('lastName', '')}".strip()
                full_address = ", ".join(p for p in [patient.get('area'), patient.get('city'), patient.get('state')] if p)
                summary['patient'] = full_name
                summary['age']     = patient.get('age') or summary.get('age', '')
                summary['gender']  = patient.get('gender', '')
                summary['address'] = full_address

        # ── Admission details (is_high_risk & high_risk_reason) ──
        adm_doc = db['hospital_admission'].find_one(
            {"ipNumber": decoded_ip_no},
            {"_id": 0, "is_high_risk": 1, "high_risk_reason": 1, "high_risk_date": 1}
        )
        if adm_doc:
            summary['is_high_risk']     = bool(adm_doc.get('is_high_risk', False))
            summary['high_risk_reason'] = adm_doc.get('high_risk_reason') or ''
            hr_date = adm_doc.get('high_risk_date')
            summary['high_risk_date']   = hr_date.isoformat() if hasattr(hr_date, 'isoformat') else str(hr_date or '')
        else:
            summary['is_high_risk']     = False
            summary['high_risk_reason'] = ''
            summary['high_risk_date']   = None

        # ── fieldsData: hand back exactly as stored ──────────────────────────
        # Stored natively in Mongo as an array: [{"key": "...", "value": "..."}, ...]
        # (see update_summary_fields). The frontend's normalizeFieldsData()
        # tolerates a JSON-string-encoded array or an older object shape too,
        # for summaries saved before this change, so we don't need to convert
        # anything here — just pass the raw value through.

        # ── Enrich summaryType and heading from masters ───────────────────────
        enrich_summary_type_and_heading(summary, db)

        return Response(summary, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    finally:
        if client:
            client.close()

@api_view(['PATCH'])
@permission_classes([HasRoleAndDataPermission])
def update_summary_fields(request, ip_no):
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    db = client['HMS']
    collection = db['hospital_summary']

    try:
        decoded_ip_no = unquote(ip_no)
        lastmodified_by = request.data.get('auth-user-id', "system")

        # Fields to never update
        exclude_keys = {
            # Immutable / auth fields
            '_id', 'created_by', 'created_date',
            'lastmodified_date', 'lastmodified_by',
            # Strip ALL auth-* keys
            *[k for k in request.data.keys() if k.startswith('auth-')],
            # Frontend-only state fields not stored in DB
            'notes', 'currentField', 'dateTime',
            'approve_time_time', 'selectedDiseases',
            # Patient info fetched from hospital_patient — not stored in summary
            'patient', 'age', 'gender', 'address',
        }

        data = {k: v for k, v in request.data.items() if k not in exclude_keys}

        if 'fieldsData' not in data or not data['fieldsData']:
            return Response({"error": "No fieldsData provided"}, status=status.HTTP_400_BAD_REQUEST)

        # ── Resolve summaryNo & headingNo and do not store raw names ──
        summary_no = str(data.get('summaryNo') or '').strip()
        if not summary_no and data.get('summaryType'):
            match_t = db['hospital_summarytype'].find_one({
                "summaryType": {"$regex": f"^{re.escape(str(data['summaryType']).strip())}$", "$options": "i"}
            })
            if match_t:
                summary_no = match_t.get('summaryNo', '')
        if not summary_no:
            existing_doc = collection.find_one({"ipNo": decoded_ip_no}, {"summaryNo": 1})
            if existing_doc:
                summary_no = existing_doc.get("summaryNo", "")

        if 'heading' in request.data:
            data['heading'] = str(request.data.get('heading') or '').strip()
        data['summaryNo'] = summary_no
        data.pop('summaryType', None)
        data.pop('headingNo', None)

        # ── fieldsData is now a native array of {"key": ..., "value": ...} ──
        fields_data = data['fieldsData']

        if isinstance(fields_data, str):
            try:
                fields_data = json.loads(fields_data)
            except json.JSONDecodeError as e:
                return Response({"error": f"Invalid JSON in fieldsData: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

        if not isinstance(fields_data, list):
            return Response(
                {"error": "fieldsData must be a list of {key, value} objects"},
                status=status.HTTP_400_BAD_REQUEST
            )

        for entry in fields_data:
            if not isinstance(entry, dict) or 'key' not in entry or 'value' not in entry:
                return Response(
                    {"error": "Each fieldsData entry must be an object with 'key' and 'value'"},
                    status=status.HTTP_400_BAD_REQUEST
                )

        fields_data = sort_fields_data_by_summary_type(
            fields_data,
            summary_no=summary_no,
            summary_type=request.data.get('summaryType'),
            db=db
        )

        data['fieldsData'] = fields_data

        def to_date(value):
            """'YYYY-MM-DD' string → datetime at midnight UTC (for DateField)."""
            if not value:
                return None
            try:
                return datetime.strptime(str(value)[:10], "%Y-%m-%d")
            except ValueError:
                return None

        def to_time(value):
            """'HH:MM' string → datetime(1900,1,1,H,M) (for TimeField)."""
            if not value:
                return None
            try:
                h, m = map(int, str(value).split(":"))
                return datetime(1900, 1, 1, h, m, 0)
            except (ValueError, AttributeError):
                return None

        # DateField columns → datetime at midnight
        for field in ('doa', 'dod', 'surgeryDate', 'nextReviewDate', 'date'):
            if field in data:
                data[field] = to_date(data[field])

        # TimeField columns → epoch datetime
        for field in ('doaTime', 'dodTime'):
            if field in data:
                data[field] = to_time(data[field])

        # DateTimeField columns → datetime object (ISODate in Mongo)
        if 'approve_time' in data:
            ap_val = data['approve_time']
            if ap_val:
                if isinstance(ap_val, str):
                    try:
                        data['approve_time'] = datetime.fromisoformat(ap_val.replace("Z", "+00:00")).replace(tzinfo=None)
                    except Exception:
                        data['approve_time'] = datetime.utcnow()
                elif isinstance(ap_val, datetime):
                    data['approve_time'] = ap_val
            else:
                data['approve_time'] = None

        # Only set lastmodified_* from auth
        data['lastmodified_date'] = datetime.utcnow()
        data['lastmodified_by']   = lastmodified_by

        updated = collection.update_one(
            {"ipNo": decoded_ip_no},
            {
                "$set": data,
                "$unset": {"summaryType": "", "headingNo": ""}
            }
        )

        if updated.matched_count > 0:
            return Response({"message": "Summary updated successfully!"}, status=status.HTTP_200_OK)
        else:
            return Response({"error": "Summary not found"}, status=status.HTTP_404_NOT_FOUND)

    except json.JSONDecodeError as e:
        return Response({"error": f"Invalid JSON in fieldsData: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        client.close()

def serialize_mongo(val):
    if isinstance(val, (datetime,)):
        return val.isoformat()
    if isinstance(val, ObjectId):
        return str(val)
    if isinstance(val, Decimal128):
        return float(val.to_decimal())
    if isinstance(val, list):
        return [serialize_mongo(x) for x in val]
    if isinstance(val, dict):
        return {k: serialize_mongo(v) for k, v in val.items()}
    return val

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_printsummary(request, ip_no):
    decoded_ip_no = unquote(ip_no)

    try:
        client         = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        hms_db         = client['HMS']
        diagnostics_db = client['Diagnostics']
        global_db      = client['Global']

        # Collections
        core_testdetails_collection = diagnostics_db['core_testdetails']
        profile_collection          = global_db['backend_diagnostics_profile']
        fs                          = gridfs.GridFS(global_db)

        # ── STEP 1: Hospital summary ──────────────────────────────────────────
        summary = hms_db['hospital_summary'].find_one({"ipNo": decoded_ip_no})
        if not summary:
            client.close()
            return JsonResponse(
                {'error': 'Hospital summary not found for the given IP number'},
                status=404
            )
        summary['_id'] = str(summary['_id'])

        # ── STEP 1b: fieldsData — hand back exactly as stored ─────────────────
        raw_fields_data = summary.get('fieldsData')
        if isinstance(raw_fields_data, str):
            try:
                parsed = json.loads(raw_fields_data)
            except (json.JSONDecodeError, TypeError):
                parsed = []
        else:
            parsed = raw_fields_data or []

        # Tolerate legacy object-shaped fieldsData saved before this change.
        if isinstance(parsed, dict):
            parsed = [{"key": k, "value": v} for k, v in parsed.items()]

        summary['fieldsData'] = parsed

        # ── Enrich summaryType and heading from masters ───────────────────────
        enrich_summary_type_and_heading(summary, hms_db)

        # ── STEP 2: Patient info from hospital_patient ────────────────────────
        uhid           = summary.get('uhid')
        patient_record = None

        if uhid:
            patient_record = hms_db['hospital_patient'].find_one({"uhid": uhid})
        if not patient_record:
            patient_record = hms_db['hospital_patient'].find_one(
                {"ip_number": decoded_ip_no}
            )

        if patient_record:
            salutation = (patient_record.get('salutation') or '').strip()
            first_name = (patient_record.get('firstName')  or '').strip()
            last_name  = (patient_record.get('lastName')   or '').strip()
            full_name  = ' '.join(filter(None, [salutation, first_name, last_name]))

            addr_parts = [
                patient_record.get('permanent_address') or '',
                patient_record.get('area')              or '',
                patient_record.get('city')              or '',
                patient_record.get('state')             or '',
            ]
            full_address = ', '.join(p for p in addr_parts if p)

            summary['patient']     = full_name   or summary.get('patient', '')
            summary['age']         = patient_record.get('age')    or summary.get('age', '')
            summary['gender']      = patient_record.get('gender') or summary.get('gender', '')
            summary['email'] = patient_record.get('email', '')
            summary['mobilePhone'] = patient_record.get('mobilePhone', '')
            summary['address']     = full_address or summary.get('address', '')
        else:
            summary.setdefault('mobilePhone', '')
            summary.setdefault('address', summary.get('address', ''))

        # Guarantee gender is always a string
        if not summary.get('gender'):
            summary['gender'] = ''

        # ── Admission details for High Risk ──
        adm_doc = hms_db['hospital_admission'].find_one(
            {"ipNumber": decoded_ip_no},
            {"_id": 0, "is_high_risk": 1, "high_risk_reason": 1, "high_risk_date": 1}
        )
        if adm_doc:
            summary['is_high_risk']     = bool(adm_doc.get('is_high_risk', False))
            summary['high_risk_reason'] = adm_doc.get('high_risk_reason') or ''
            hr_d = adm_doc.get('high_risk_date')
            summary['high_risk_date']   = hr_d.isoformat() if hasattr(hr_d, 'isoformat') else str(hr_d or '')
        else:
            summary['is_high_risk']     = False
            summary['high_risk_reason'] = ''
            summary['high_risk_date']   = None

        # Init test fields
        summary['testdetails']  = []
        summary['barcode']      = None
        summary['investBillNo'] = None
        summary['signatures']   = []

        # ── STEP 3: Get barcode strictly requiring ipnumber == decoded_ip_no ──
        barcode_record = None

        # 1. Fetch investBillNo(s) for this specific ipNumber from hospital_investbilling
        investbilling_collection = hms_db['hospital_investbilling']
        invest_bills = list(investbilling_collection.find(
            {'ipNumber': decoded_ip_no, 'is_active': True},
            {'investBillNo': 1, '_id': 0}
        ).sort("created_date", -1))

        bill_numbers = [b['investBillNo'] for b in invest_bills if b.get('investBillNo')]

        # 2. In core_hmsbarcode, MUST match ipnumber == decoded_ip_no AND billnumber in this IP's invest bills
        if bill_numbers and decoded_ip_no:
            barcode_record = diagnostics_db['core_hmsbarcode'].find_one(
                {
                    "ipnumber": decoded_ip_no,
                    "billnumber": {"$in": bill_numbers}
                },
                sort=[("created_date", -1)]
            )

        # 3. If not matched with billnumber, check core_hmsbarcode strictly with ipnumber == decoded_ip_no
        if not barcode_record and decoded_ip_no:
            barcode_record = diagnostics_db['core_hmsbarcode'].find_one(
                {"ipnumber": decoded_ip_no},
                sort=[("created_date", -1)]
            )

        # If core_hmsbarcode does not have matching ipnumber, DO NOT fall back to anything
        if not barcode_record:
            client.close()
            return JsonResponse(serialize_mongo(summary), safe=False)

        barcode                 = barcode_record.get('barcode')
        summary['barcode']      = barcode
        summary['investBillNo'] = barcode_record.get('billnumber')

        if not barcode:
            client.close()
            return JsonResponse(serialize_mongo(summary), safe=False)

        # ── STEP 4: Fetch standard test result documents from core_testvalue ──
        test_value_records = list(
            diagnostics_db['core_testvalue'].find({"barcode": barcode})
        )

        # ── Helper: get parameter definition from core_testdetails ────────────
        def get_parameter_from_core(core_test, device_id, test_code=None, param_index=None):
            """
            Match a parameter definition from core_testdetails.
            Supports both dict (device_id-keyed) and list formats.
            Uses param_index for accuracy; falls back to test_code match.
            """
            core_parameters = core_test.get("parameters", {})
            params_list = []

            if isinstance(core_parameters, dict):
                if device_id and device_id != "N/A" and device_id in core_parameters:
                    params_list = core_parameters[device_id]
                elif core_parameters:
                    params_list = list(core_parameters.values())[0]
            elif isinstance(core_parameters, list):
                params_list = core_parameters

            if not isinstance(params_list, list):
                return None

            if param_index is not None and 0 <= param_index < len(params_list):
                return params_list[param_index]

            if test_code:
                for p in params_list:
                    if isinstance(p, dict) and p.get("test_code") == test_code:
                        return p

            return None

        # ── Helper: fetch employee signature ──────────────────────────────────
        def get_employee_signature_data(employee_id):
            if not employee_id:
                return None
            try:
                profile = profile_collection.find_one({"employeeId": employee_id})
                if not profile:
                    return None

                employee_name       = profile.get("employeeName", "")
                designation         = profile.get("designation", "")
                signature_file_id   = profile.get("signatureFileId")
                signature_base64    = None

                if signature_file_id:
                    try:
                        if isinstance(signature_file_id, str):
                            signature_file_id = ObjectId(signature_file_id)
                        sig_file         = fs.get(signature_file_id)
                        signature_base64 = base64.b64encode(sig_file.read()).decode('utf-8')
                    except Exception as e:
                        print(f"Signature fetch error for {employee_id}: {e}")

                return {
                    "employeeName":    employee_name,
                    "designation":     designation,
                    "signatureBase64": signature_base64
                }
            except Exception as e:
                print(f"Employee data error for {employee_id}: {e}")
                return None

        # ── STEP 5: Parse & enrich STANDARD test details ──────────────────────
        test_details   = []
        lab_approvers  = set()   # approvers from standard core_testvalue
        micro_approvers = set()  # approvers from core_mbtestvalue

        for test_value in test_value_records:
            try:
                raw     = test_value.get('testdetails', '[]')
                details = json.loads(raw) if isinstance(raw, str) else raw

                if not isinstance(details, list):
                    continue

                for test in details:

                    # Only include APPROVED tests
                    if test.get("approve") is not True:
                        continue

                    test_id     = test.get("test_id")
                    device_id   = test.get("device_id", "N/A")
                    parameters  = test.get("parameters", [])
                    approve_by  = test.get("approve_by", "")
                    verified_by = test.get("verified_by", "N/A")
                    approve_time  = test.get("approve_time", "N/A")
                    dispatch_time = test.get("dispatch_time", "")
                    outsourced    = test.get("outsourced", False)
                    comment       = test.get("comment", "")
                    remarks       = test.get("remarks", "")

                    if approve_by:
                        lab_approvers.add(approve_by)
                    core_test = core_testdetails_collection.find_one({"test_id": test_id})

                    if core_test:
                        testname      = core_test.get("test_name", test.get("testname", ""))
                        department    = core_test.get("department", "N/A")
                        NABL          = core_test.get("NABL", False)
                        specimen_type = core_test.get("specimen_type", "N/A")
                    else:
                        testname      = test.get("testname", "")
                        department    = test.get("department", "N/A")
                        NABL          = test.get("NABL", False)
                        specimen_type = test.get("specimen_type", "N/A")

                    test_detail = {
                        "test_id":        test_id,
                        "department":     department,
                        "NABL":           NABL,
                        "outsourced":     outsourced,
                        "comment":        comment,
                        "remarks":        remarks,
                        "testname":       testname,
                        "verified_by":    verified_by,
                        "approve_by":     approve_by,
                        "approve_time":   approve_time,
                        "dispatch_time":  dispatch_time,
                        "is_microbiology": False,  # Flag: standard test
                    }

                    if parameters and len(parameters) > 0 and core_test:
                        enriched_parameters = []

                        for param_index, param_value in enumerate(parameters):
                            test_code     = param_value.get("test_code")
                            value         = param_value.get("value", "")
                            param_comment = param_value.get("comment", "")

                            param_def = get_parameter_from_core(
                                core_test,
                                device_id,
                                test_code=test_code,
                                param_index=param_index
                            )

                            if param_def:
                                enriched_parameters.append({
                                    "name":            param_def.get("test_name", ""),
                                    "test_code":       test_code,
                                    "value":           value,
                                    "unit":            param_def.get("unit", ""),
                                    "reference_range": param_def.get("reference_range", ""),
                                    "method":          param_def.get("method", ""),
                                    "specimen_type":   specimen_type,
                                    "sub_title":       param_def.get("sub_title", ""),
                                    "value_option":    param_def.get("value_option", []),
                                    "comment":         param_comment,
                                })
                            else:
                                enriched_parameters.append({
                                    "name":            param_value.get("name", "N/A"),
                                    "test_code":       test_code,
                                    "value":           value,
                                    "unit":            param_value.get("unit", "N/A"),
                                    "reference_range": param_value.get("reference_range", "N/A"),
                                    "method":          param_value.get("method", "N/A"),
                                    "specimen_type":   specimen_type,
                                    "sub_title":       param_value.get("sub_title", ""),
                                    "value_option":    [],
                                    "comment":         param_comment,
                                })

                        test_detail["parameters"] = enriched_parameters

                    elif parameters and len(parameters) > 0:
                        test_detail["parameters"] = parameters

                    else:
                        if core_test:
                            test_detail.update({
                                "method":          core_test.get("method", ""),
                                "specimen_type":   specimen_type,
                                "value":           test.get("value", ""),
                                "unit":            core_test.get("unit", ""),
                                "reference_range": core_test.get("reference_range", ""),
                                "sub_title":       test.get("sub_title", ""),
                            })
                        else:
                            test_detail.update({
                                "method":          test.get("method", ""),
                                "specimen_type":   test.get("specimen_type", ""),
                                "value":           test.get("value", ""),
                                "unit":            test.get("unit", ""),
                                "reference_range": test.get("reference_range", ""),
                                "sub_title":       test.get("sub_title", ""),
                            })

                    test_details.append(test_detail)

            except (json.JSONDecodeError, AttributeError):
                continue

        # ── STEP 6: Fetch MICROBIOLOGY tests from core_mbtestvalue (MongoDB) ────
        mb_testvalue_collection = diagnostics_db['core_mbtestvalue']
        mb_test_value_records   = list(mb_testvalue_collection.find({"barcode": barcode}))

        for mb_record in mb_test_value_records:
            try:
                mb_details = mb_record.get('testdetails', [])
                if isinstance(mb_details, str):
                    try:
                        mb_details = json.loads(mb_details)
                    except (json.JSONDecodeError, ValueError):
                        mb_details = []

                if not isinstance(mb_details, list):
                    mb_details = []

                for test in mb_details:
                    # Only include approved tests
                    if test.get("approve") is not True:
                        continue

                    test_id      = test.get("test_id")
                    approve_by   = test.get("approve_by", "")
                    verified_by  = test.get("verified_by", "N/A")
                    approve_time = test.get("approve_time", "N/A")
                    comment      = test.get("comment", "")
                    remarks      = test.get("remarks", "")
                    colony_count = test.get("colony_count", "")
                    parameter_type = test.get("parameter_type", "N/A")

                    if approve_by:
                        micro_approvers.add(approve_by)

                    # Fetch core test definition from core_testdetails (for MB)
                    core_test = core_testdetails_collection.find_one({"test_id": test_id})

                    if core_test:
                        testname      = core_test.get("test_name", test.get("testname", ""))
                        department    = core_test.get("department", "Microbiology")
                        specimen_type = core_test.get("specimen_type", "N/A")
                        is_AG_title   = core_test.get("is_AG_title", False)
                    else:
                        testname      = test.get("testname", "")
                        department    = test.get("department", "Microbiology")
                        specimen_type = test.get("specimen_type", "N/A")
                        is_AG_title   = test.get("is_AG_title", False)

                    # Build microbiology test detail (matches handlePrint MB format)
                    mb_test_detail = {
                        "test_id":         test_id,
                        "testname":        testname,
                        "department":      department,
                        "specimen_type":   specimen_type,
                        "is_AG_title":     is_AG_title,
                        "remarks":         remarks,
                        "colony_count":    colony_count,
                        "comment":         comment,
                        "verified_by":     verified_by,
                        "approve_by":      approve_by,
                        "approve_time":    approve_time,
                        "is_microbiology": True,  # Flag for frontend renderer
                    }

                    # Process parameters (antibiogram rows)
                    raw_parameters = test.get("parameters", [])
                    if raw_parameters and len(raw_parameters) > 0 and core_test:
                        simplified_parameters = []

                        for param_index, param_value in enumerate(raw_parameters):
                            test_code     = param_value.get("test_code")
                            value         = param_value.get("value", "")
                            result        = param_value.get("result", "")
                            param_comment = param_value.get("comment", "")

                            # Get parameter definition using index-based matching
                            param_def = get_parameter_from_core(
                                core_test,
                                parameter_type,
                                test_code=test_code,
                                param_index=param_index
                            )

                            if param_def:
                                simplified_parameters.append({
                                    "test_name": param_def.get("test_name", ""),
                                    "test_code": test_code,
                                    "value":     value,   # zone of inhibition
                                    "result":    result,  # S / R / I
                                    "comment":   param_comment,
                                })
                            else:
                                simplified_parameters.append({
                                    "test_name": param_value.get("name", "N/A"),
                                    "test_code": test_code,
                                    "value":     value,
                                    "result":    result,
                                    "comment":   param_comment,
                                })

                        mb_test_detail["parameters"] = simplified_parameters

                    elif raw_parameters and len(raw_parameters) > 0:
                        # No core_test found — use raw data
                        simplified_parameters = []
                        for param_value in raw_parameters:
                            simplified_parameters.append({
                                "test_name": param_value.get("name", "N/A"),
                                "test_code": param_value.get("test_code", ""),
                                "value":     param_value.get("value", ""),
                                "result":    param_value.get("result", ""),
                                "comment":   param_value.get("comment", ""),
                            })
                        mb_test_detail["parameters"] = simplified_parameters
                    else:
                        mb_test_detail["parameters"] = []

                    test_details.append(mb_test_detail)

            except (json.JSONDecodeError, AttributeError, Exception) as e:
                print(f"Error processing MBTestValue record: {e}")
                continue

        summary['testdetails'] = test_details

        # ── STEP 7: Fetch approver signatures separately ───────────────────────
        # Lab (standard) signatures
        signatures = []
        for approver_id in lab_approvers:
            sig_data = get_employee_signature_data(approver_id)
            if sig_data:
                signatures.append(sig_data)

        # Microbiology signatures (kept separate so frontend can render them independently)
        micro_signatures = []
        for approver_id in micro_approvers:
            sig_data = get_employee_signature_data(approver_id)
            if sig_data:
                micro_signatures.append(sig_data)

        summary['signatures']       = signatures        # for standard lab sections
        summary['micro_signatures'] = micro_signatures  # for microbiology section

        # Enrich employee display names from Global.backend_diagnostics_profile
        from .dbcollection import get_employee_name_by_id, resolve_created_by_name
        cb = str(summary.get('created_by') or '').strip()
        if cb:
            summary['created_by_name'] = resolve_created_by_name(cb)
        ab = str(summary.get('approved_by') or '').strip()
        if ab:
            summary['approved_by_name'] = resolve_created_by_name(ab)

        client.close()
        return JsonResponse(serialize_mongo(summary), safe=False)

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return JsonResponse({'error': str(e)}, status=500)
    

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_patient_medicines(request, ip_no):
    client = None
    try:
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        hms_db = client['HMS']
        pharmacy_collection = hms_db['hospital_pharmacybilling']
        items_collection = hms_db['hospital_pharmacyitem']

        decoded_ip_no = unquote(ip_no)

        bills = list(pharmacy_collection.find(
            {
                'inpatient_number': decoded_ip_no,
                'billing_mode': 'WARD REQUEST',
                'is_ward_request': True,
            },
            {
                '_id': 0,
                'bill_no': 1,
                'medicine_particulars': 1
            }
        ))

        if not bills:
            return Response([], status=status.HTTP_200_OK)

        # Collect all unique item_ids across all bills
        item_ids = set()
        for bill in bills:
            for item in bill.get('medicine_particulars', []):
                if item.get('item_id') is not None:
                    item_ids.add(item['item_id'])

        # Single query to fetch all item names
        item_name_map = {}
        if item_ids:
            items = items_collection.find(
                {'item_id': {'$in': list(item_ids)}},
                {'_id': 0, 'item_id': 1, 'item_name': 1}
            )
            item_name_map = {i['item_id']: i['item_name'] for i in items}

        # Flatten all medicine_particulars across all bills
        medicines = []
        for bill in bills:
            for item in bill.get('medicine_particulars', []):
                item_id = item.get('item_id')
                medicines.append({
                    'itemName': item_name_map.get(item_id, f'Item {item_id}'),
                    'dosage': item.get('dosage', ''),
                    'noOfDays': item.get('noOfDays', ''),
                    'qty': item.get('qty', ''),
                    'doseUnit': item.get('doseunit', ''),
                    'route': item.get('route', ''),
                    'remark': item.get('instruction', ''),
                    'bill_no': bill.get('bill_no', ''),
                })

        return Response(medicines, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if client:
            client.close()


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_patient_discharge_medicines(request, ip_no):
    client = None
    try:
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        hms_db = client['HMS']
        pharmacy_collection = hms_db['hospital_pharmacybilling']
        items_collection = hms_db['hospital_pharmacyitem']

        decoded_ip_no = unquote(ip_no)

        bills = list(pharmacy_collection.find(
            {
                'inpatient_number': decoded_ip_no,
                'billing_mode': 'DISCHARGE MEDICINE',
                'is_ward_request': True,
            },
            {
                '_id': 0,
                'bill_no': 1,
                'medicine_particulars': 1
            }
        ))

        if not bills:
            return Response([], status=status.HTTP_200_OK)

        # Collect all unique item_ids across all bills
        item_ids = set()
        for bill in bills:
            for item in bill.get('medicine_particulars', []):
                if item.get('item_id') is not None:
                    item_ids.add(item['item_id'])

        # Single query to fetch all item names
        item_name_map = {}
        if item_ids:
            items = items_collection.find(
                {'item_id': {'$in': list(item_ids)}},
                {'_id': 0, 'item_id': 1, 'item_name': 1}
            )
            item_name_map = {i['item_id']: i['item_name'] for i in items}

        # Flatten all medicine_particulars across all bills
        medicines = []
        for bill in bills:
            for item in bill.get('medicine_particulars', []):
                item_id = item.get('item_id')
                medicines.append({
                    'itemName': item_name_map.get(item_id, f'Item {item_id}'),
                    'dosage': item.get('dosage', ''),
                    'noOfDays': item.get('noOfDays', ''),
                    'qty': item.get('qty', ''),
                    'doseUnit': item.get('doseunit', ''),
                    'route': item.get('route', ''),
                    'remark': item.get('instruction', ''),
                    'bill_no': bill.get('bill_no', ''),
                })

        return Response(medicines, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if client:
            client.close()


def clinical_nlp_summarize(raw_text, field_name=""):
    """Fallback text normalizer without any hardcoded sentences or rules."""
    if not raw_text or not str(raw_text).strip():
        return ""
    return str(raw_text).strip()


def summarize_with_gemini(raw_text, field_name, patient_name, api_key):
    """Dynamically improvise, translate, elevate, and refine notes using Google Gemini with zero hardcoding."""
    models_to_try = ["gemini-3.5-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite"]
    prompt = (
        f"You are a master medical editor, clinical documentation specialist, and expert in advanced English prose.\n"
        f"Your task is to dynamically improvise, translate, rewrite, and elevate the following clinical notes for the '{field_name}' section of a hospital discharge summary.\n\n"
        f"CORE INSTRUCTIONS:\n"
        f"1. DYNAMIC MULTILINGUAL TRANSLATION: The input may be spoken or dictated in English, Tamil, or Hindi. Dynamically comprehend all linguistic context, semantics, and intent, and seamlessly translate everything into formal, fluent, professional medical English.\n"
        f"2. REMOVE ALL GRAMMATICAL MISTAKES & SYNTACTIC ERRORS: Thoroughly correct all grammar, faulty sentence structures, run-on clauses, incorrect tenses, fragmentations, subject-verb disagreements, punctuation errors, and awkward phrasing.\n"
        f"3. USE ADVANCED ENGLISH & ELEVATED MEDICAL VOCABULARY: Dynamically transform basic, conversational, or dictated words into sophisticated, articulate, high-level English words and authoritative clinical phrasing appropriate for a premier medical center discharge document.\n"
        f"4. STRICTLY NO SUBTITLES, HEADERS, OR CATEGORY LABELS: Do NOT insert any subtitles, bold headers, section markers, or category titles.\n"
        f"5. STRICTLY NO BULLET POINTS: Write as a continuous, coherent, flowing clinical narrative paragraph.\n"
        f"6. PRESERVE 100% CLINICAL FACTS & FIDELITY: Retain every diagnostic finding, procedure detail, device dimension, medication name, dosage, and date with complete fidelity. Do not fabricate or invent unstated clinical conditions.\n"
        f"7. OUTPUT: Output ONLY the improvised advanced English text directly. No conversational preamble, no closing remarks, and no markdown code fences.\n\n"
        f"Clinical notes to improvise:\n{raw_text}"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 2048},
    }

    for model_name in models_to_try:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
            res = requests.post(url, json=payload, timeout=15)
            if res.status_code == 200:
                data = res.json()
                candidates = data.get('candidates', [])
                if candidates:
                    parts = candidates[0].get('content', {}).get('parts', [])
                    if parts:
                        text = parts[0].get('text', '').strip()
                        # Strip conversational greeting if LLM added any
                        text = re.sub(r'^(here is (a|the) (concise|clinical|formatted|patient)?\s*(summary|notes?).*?:?\s*\n+)', '', text, flags=re.IGNORECASE)
                        # Remove markdown backtick code blocks if any
                        text = re.sub(r'^```(?:markdown)?\s*', '', text)
                        text = re.sub(r'\s*```$', '', text)
                        # Strip any unwanted subtitles or bold headers like **Header:**
                        text = re.sub(r'^\*\*[^*]+:\*\*\s*\n*', '', text)
                        text = re.sub(r'\n+\*\*[^*]+:\*\*\s*\n*', ' ', text)
                        # Strip leading bullet dots if any
                        text = re.sub(r'^[•\-\*]\s*', '', text, flags=re.MULTILINE)
                        # Normalize multiple whitespace/newlines into clean continuous paragraphs
                        text = re.sub(r'\n\s*\n+', '\n\n', text).strip()
                        if text:
                            return text
        except Exception as e:
            logger.warning(f"Gemini {model_name} summarization failed: {e}")
            continue

    return None


@api_view(['POST'])
def ai_summarize_notes(request):
    """
    Endpoint: /ai-summarize-notes/
    Summarizes and improvises raw or voice-dictated clinical notes into professional medical discharge prose using Google Gemini.
    """
    raw_text = request.data.get('text', '')
    field_name = request.data.get('field', 'CLINICAL NOTES')
    patient_name = request.data.get('patient_name', '')

    if not raw_text or not str(raw_text).strip():
        return Response({"error": "No notes provided to summarize"}, status=status.HTTP_400_BAD_REQUEST)

    from dotenv import load_dotenv
    load_dotenv(override=True)

    gemini_key = os.getenv('HMS_DS_GEMINI_API_KEY')
    if not gemini_key:
        return Response({
            "success": False,
            "error": "HMS_DS_GEMINI_API_KEY not configured in backend .env."
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    summarized_text = summarize_with_gemini(raw_text, field_name, patient_name, gemini_key)

    if not summarized_text:
        return Response({
            "success": False,
            "error": "Gemini AI could not improvise notes. Please verify API key quota and network connection."
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    return Response({
        "success": True,
        "summarized": summarized_text,
        "original": raw_text,
    }, status=status.HTTP_200_OK)
