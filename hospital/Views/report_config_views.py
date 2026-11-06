import json
import re
from datetime import datetime
from bson import ObjectId
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone
from hospital.Views.dbcollection import hms_db


def _now():
    return datetime.utcnow()


def serialize_doc(doc):
    if not doc:
        return None
    d = dict(doc)
    if '_id' in d:
        d['_id'] = str(d['_id'])
    # Normalize aliases
    group_name = d.get('group') or d.get('report_title') or ''
    group_id = d.get('group_id')
    if group_id is None:
        group_id = d.get('report_id')

    d['group'] = group_name
    d['group_id'] = group_id
    d['report_title'] = group_name
    d['report_id'] = str(group_id) if group_id is not None else ''

    # Ensure pages array
    pages = d.get('pages')
    if pages is None:
        raw_reports = d.get('reports')
        if isinstance(raw_reports, dict):
            pages = []
            for idx, (route, meta) in enumerate(raw_reports.items(), 1):
                if isinstance(meta, dict):
                    pages.append({
                        "name": meta.get('title') or route,
                        "route": route,
                        "description": meta.get('description', ''),
                        "icon": meta.get('icon', 'FileText'),
                        "permissions": {meta.get('title', route): meta.get('permission', '')},
                        "page_id": meta.get('page_id', idx)
                    })
                else:
                    pages.append({
                        "name": str(meta),
                        "route": route,
                        "description": "",
                        "icon": "FileText",
                        "permissions": {},
                        "page_id": idx
                    })
        else:
            pages = []
    d['pages'] = pages

    # Normalize dates
    for k in ['created_date', 'lastmodified_date']:
        if isinstance(d.get(k), datetime):
            d[k] = d[k].isoformat()
    return d


@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def report_master_list_create(request):
    """
    GET: List all ReportMaster documents from MongoDB (hospital_reportmaster).
         Optional query params:
         - ?group=Stores (matches group/report_title)
         - ?group_id=1
    POST: Create or update a ReportMaster group and its pages array.
    """
    collection = hms_db['hospital_reportmaster']

    if request.method == 'GET':
        query = {}
        group_filter = request.GET.get('group') or request.GET.get('report_title')
        if group_filter:
            regex_pat = re.compile(f".*{re.escape(group_filter.strip())}.*", re.IGNORECASE)
            query['$or'] = [
                {'group': {'$regex': regex_pat}},
                {'report_title': {'$regex': regex_pat}}
            ]

        gid_filter = request.GET.get('group_id') or request.GET.get('report_id')
        if gid_filter:
            try:
                numeric_gid = int(gid_filter)
                query['$or'] = [{'group_id': numeric_gid}, {'group_id': str(numeric_gid)}, {'report_id': str(gid_filter)}]
            except ValueError:
                query['$or'] = [{'group_id': gid_filter}, {'report_id': str(gid_filter)}]

        cursor = collection.find(query).sort('order', 1)
        data = [serialize_doc(doc) for doc in cursor]

        return Response({"success": True, "count": len(data), "data": data}, status=status.HTTP_200_OK)

    elif request.method == 'POST':
        payload = request.data or {}
        group_name = str(payload.get('group') or payload.get('report_title') or '').strip()
        if not group_name:
            return Response({"success": False, "message": "group or report_title is required"}, status=status.HTTP_400_BAD_REQUEST)

        group_id = payload.get('group_id')
        if group_id is None or str(group_id).strip() == '':
            group_id = payload.get('report_id')

        if group_id is None or str(group_id).strip() == '':
            # Autoincrement highest group_id
            existing = list(collection.find({}, {'group_id': 1}))
            max_id = 0
            for e in existing:
                try:
                    max_id = max(max_id, int(e.get('group_id', 0)))
                except (ValueError, TypeError):
                    pass
            group_id = max_id + 1
        else:
            try:
                group_id = int(group_id)
            except ValueError:
                group_id = str(group_id).strip()

        order = payload.get('order', 1)
        try:
            order = int(order)
        except (ValueError, TypeError):
            order = 1

        pages = payload.get('pages')
        if pages is None:
            raw_reports = payload.get('reports')
            if isinstance(raw_reports, dict):
                pages = []
                for idx, (route, meta) in enumerate(raw_reports.items(), 1):
                    if isinstance(meta, dict):
                        pages.append({
                            "name": meta.get('title') or meta.get('name') or route,
                            "route": route,
                            "description": meta.get('description', ''),
                            "icon": meta.get('icon', 'FileText'),
                            "permissions": meta.get('permissions') or {meta.get('title', route): meta.get('permission', '')},
                            "page_id": meta.get('page_id', idx)
                        })
                    else:
                        pages.append({
                            "name": str(meta),
                            "route": route,
                            "description": "",
                            "icon": "FileText",
                            "permissions": {},
                            "page_id": idx
                        })
            elif isinstance(raw_reports, str):
                try:
                    parsed = json.loads(raw_reports)
                    if isinstance(parsed, list):
                        pages = parsed
                    elif isinstance(parsed, dict):
                        pages = [{"name": str(v), "route": k, "page_id": i+1} for i, (k, v) in enumerate(parsed.items())]
                except Exception:
                    pages = []
            else:
                pages = []

        current_user = request.headers.get('auth-user-id') or payload.get('created_by') or 'system'
        now = _now()

        update_filter = {
            '$or': [
                {'group_id': group_id},
                {'group_id': str(group_id)},
                {'report_id': str(group_id)},
                {'group': group_name}
            ]
        }

        doc = {
            'group': group_name,
            'group_id': group_id,
            'order': order,
            'pages': pages,
            'is_active': payload.get('is_active', True),
            'lastmodified_by': current_user,
            'lastmodified_date': now
        }

        existing_doc = collection.find_one(update_filter)
        if existing_doc:
            collection.update_one({'_id': existing_doc['_id']}, {'$set': doc})
            doc['_id'] = existing_doc['_id']
        else:
            doc['created_by'] = current_user
            doc['created_date'] = now
            ins = collection.insert_one(doc)
            doc['_id'] = ins.inserted_id

        return Response({
            "success": True,
            "message": "Report master saved successfully",
            "data": serialize_doc(doc)
        }, status=status.HTTP_200_OK)


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([AllowAny])
def report_master_detail(request, report_id):
    """
    GET, PUT, DELETE a specific ReportMaster group by group_id or group name.
    """
    collection = hms_db['hospital_reportmaster']
    target = str(report_id).strip()

    or_conditions = [{'group': target}, {'report_id': target}]
    try:
        or_conditions.append({'group_id': int(target)})
    except ValueError:
        pass
    or_conditions.append({'group_id': target})

    doc = collection.find_one({'$or': or_conditions})
    if not doc:
        return Response({"success": False, "message": "Report master not found"}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        return Response({"success": True, "data": serialize_doc(doc)}, status=status.HTTP_200_OK)

    elif request.method == 'PUT':
        payload = request.data or {}
        updates = {
            'lastmodified_by': request.headers.get('auth-user-id') or 'system',
            'lastmodified_date': _now()
        }

        if 'group' in payload or 'report_title' in payload:
            updates['group'] = payload.get('group') or payload.get('report_title')
        if 'order' in payload:
            try:
                updates['order'] = int(payload['order'])
            except (ValueError, TypeError):
                pass
        if 'pages' in payload and isinstance(payload['pages'], list):
            updates['pages'] = payload['pages']
        if 'is_active' in payload:
            updates['is_active'] = bool(payload['is_active'])

        collection.update_one({'_id': doc['_id']}, {'$set': updates})
        updated_doc = collection.find_one({'_id': doc['_id']})

        return Response({
            "success": True,
            "message": "Report master updated successfully",
            "data": serialize_doc(updated_doc)
        }, status=status.HTTP_200_OK)

    elif request.method == 'DELETE':
        # Soft delete or deactivate
        collection.update_one({'_id': doc['_id']}, {
            '$set': {
                'is_active': False,
                'lastmodified_by': request.headers.get('auth-user-id') or 'system',
                'lastmodified_date': _now()
            }
        })
        return Response({"success": True, "message": "Report master deactivated"}, status=status.HTTP_200_OK)


@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def report_configuration_master_view(request):
    """
    GET: Retrieve report configuration for a specific employee (?employeeId=...).
    POST: Save or update report configuration for an employee in format:
          {
            "employeeid": "EMP123",
            "report_permissions": { "route/page": "pageid" },
            "reports": { "group_id": "group_name" }
          }
    """
    collection = hms_db['hospital_reportconfigurationmaster']

    if request.method == 'GET':
        employee_id = request.GET.get('employeeId') or request.GET.get('employee_id') or request.GET.get('employeeid')
        if not employee_id:
            return Response({"success": False, "message": "employeeId is required"}, status=status.HTTP_400_BAD_REQUEST)

        emp_str = str(employee_id).strip()
        doc = collection.find_one({
            '$or': [
                {'employeeid': emp_str},
                {'employee_id': emp_str}
            ]
        })

        if not doc:
            return Response({
                "success": True,
                "data": {
                    "employeeid": emp_str,
                    "employee_id": emp_str,
                    "report_permissions": {},
                    "reports": {},
                    "is_configured": False
                }
            }, status=status.HTTP_200_OK)

        d = dict(doc)
        d['_id'] = str(d.get('_id'))
        d['employeeid'] = d.get('employeeid') or d.get('employee_id') or emp_str
        d['employee_id'] = d['employeeid']
        d['is_configured'] = True
        for k in ['created_date', 'lastmodified_date']:
            if isinstance(d.get(k), datetime):
                d[k] = d[k].isoformat()

        return Response({"success": True, "data": d}, status=status.HTTP_200_OK)

    elif request.method == 'POST':
        payload = request.data or {}
        employee_id = payload.get('employeeid') or payload.get('employee_id') or payload.get('employeeId')
        if not employee_id:
            return Response({"success": False, "message": "employeeid is required"}, status=status.HTTP_400_BAD_REQUEST)

        emp_str = str(employee_id).strip()
        report_permissions = payload.get('report_permissions') or {}
        reports = payload.get('reports') or {}

        if isinstance(report_permissions, str):
            try:
                report_permissions = json.loads(report_permissions)
            except Exception:
                report_permissions = {}

        if isinstance(reports, str):
            try:
                reports = json.loads(reports)
            except Exception:
                reports = {}

        current_user = request.headers.get('auth-user-id') or payload.get('created_by') or 'system'
        now = _now()

        filter_q = {
            '$or': [
                {'employeeid': emp_str},
                {'employee_id': emp_str}
            ]
        }

        existing = collection.find_one(filter_q)
        update_data = {
            'employeeid': emp_str,
            'employee_id': emp_str,
            'report_permissions': report_permissions,
            'reports': reports,
            'is_active': True,
            'lastmodified_by': current_user,
            'lastmodified_date': now
        }

        if existing:
            collection.update_one({'_id': existing['_id']}, {'$set': update_data})
            update_data['_id'] = str(existing['_id'])
        else:
            update_data['created_by'] = current_user
            update_data['created_date'] = now
            ins = collection.insert_one(update_data)
            update_data['_id'] = str(ins.inserted_id)

        for k in ['created_date', 'lastmodified_date']:
            if isinstance(update_data.get(k), datetime):
                update_data[k] = update_data[k].isoformat()

        return Response({
            "success": True,
            "message": "Report configuration saved successfully",
            "data": update_data
        }, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([AllowAny])
def report_configuration_copy_view(request):
    """
    Copy or transfer report configuration from a source employee to target employees.
    Payload:
    {
        "source_employee_id": "EMP001",
        "target_employee_ids": ["EMP002", "EMP003"],
        "is_transfer": false
    }
    """
    collection = hms_db['hospital_reportconfigurationmaster']
    payload = request.data or {}

    source_emp = str(payload.get('source_employee_id') or payload.get('source_employeeid') or '').strip()
    target_emps = payload.get('target_employee_ids') or payload.get('target_employeeids') or []
    is_transfer = bool(payload.get('is_transfer', False))

    if not source_emp:
        return Response({"success": False, "message": "source_employee_id is required"}, status=status.HTTP_400_BAD_REQUEST)

    if not target_emps or not isinstance(target_emps, list):
        return Response({"success": False, "message": "target_employee_ids must be a non-empty list"}, status=status.HTTP_400_BAD_REQUEST)

    source_doc = collection.find_one({
        '$or': [
            {'employeeid': source_emp},
            {'employee_id': source_emp}
        ]
    })

    if not source_doc:
        return Response({"success": False, "message": f"Source employee {source_emp} has no report configuration"}, status=status.HTTP_404_NOT_FOUND)

    current_user = request.headers.get('auth-user-id') or 'system'
    now = _now()
    src_perms = dict(source_doc.get('report_permissions') or {})
    src_reports = dict(source_doc.get('reports') or {})

    applied_count = 0
    for target_id in target_emps:
        t_str = str(target_id).strip()
        if not t_str or t_str == source_emp:
            continue

        existing_t = collection.find_one({
            '$or': [
                {'employeeid': t_str},
                {'employee_id': t_str}
            ]
        })

        t_doc = {
            'employeeid': t_str,
            'employee_id': t_str,
            'report_permissions': dict(src_perms),
            'reports': dict(src_reports),
            'is_active': True,
            'lastmodified_by': current_user,
            'lastmodified_date': now
        }

        if existing_t:
            collection.update_one({'_id': existing_t['_id']}, {'$set': t_doc})
        else:
            t_doc['created_by'] = current_user
            t_doc['created_date'] = now
            collection.insert_one(t_doc)
        applied_count += 1

    if is_transfer:
        collection.update_one({'_id': source_doc['_id']}, {
            '$set': {
                'report_permissions': {},
                'reports': {},
                'lastmodified_by': current_user,
                'lastmodified_date': now
            }
        })

    return Response({
        "success": True,
        "message": f"Successfully {'transferred' if is_transfer else 'copied'} report permissions to {applied_count} employee(s)",
        "applied_count": applied_count
    }, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([AllowAny])
def my_report_permissions_view(request):
    """
    Returns the current employee's active report permissions and allocated reports.
    Checks ?employeeId=... or request headers.
    """
    employee_id = request.GET.get('employeeId') or request.GET.get('employee_id') or request.headers.get('auth-user-id')
    if not employee_id:
        return Response({"success": False, "message": "employeeId is required"}, status=status.HTTP_400_BAD_REQUEST)

    emp_str = str(employee_id).strip()
    collection = hms_db['hospital_reportconfigurationmaster']

    doc = collection.find_one({
        '$or': [
            {'employeeid': emp_str},
            {'employee_id': emp_str}
        ],
        'is_active': True
    })

    if not doc:
        return Response({
            "success": True,
            "has_custom_config": False,
            "report_permissions": {},
            "reports": {}
        }, status=status.HTTP_200_OK)

    return Response({
        "success": True,
        "has_custom_config": True,
        "employeeid": emp_str,
        "report_permissions": doc.get('report_permissions') or {},
        "reports": doc.get('reports') or {}
    }, status=status.HTTP_200_OK)
