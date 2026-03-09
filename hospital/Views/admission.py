from decimal import Decimal, InvalidOperation
from bson import ObjectId
from rest_framework.response import Response
from rest_framework import status
from pymongo import MongoClient
import os
from datetime import datetime, date
from rest_framework.decorators import api_view, permission_classes
from pyauth.auth import HasRoleAndDataPermission
from django.http import JsonResponse
from django.forms.models import model_to_dict
from ..models import Admission, Room, Patient          # adjust Patient import to your app
from ..serializers import RoomSerializer, PatientSerializer
from django.views.decorators.csrf import csrf_exempt


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _global_db():
    client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
    return client['Global']


def _doctor_name(employee_id):
    """Resolve employeeId → employeeName from Global diagnostics collection."""
    if not employee_id:
        return ""
    doc = _global_db()['backend_diagnostics_profile'].find_one(
        {"employeeId": employee_id}
    ) or {}
    return doc.get('employeeName', str(employee_id))


def _doctor_names_bulk(ids):
    """Return {employeeId: employeeName} for a list of ids."""
    ids = [i for i in ids if i]
    if not ids:
        return {}
    docs = _global_db()['backend_diagnostics_profile'].find(
        {"employeeId": {"$in": ids}}
    )
    return {str(d['employeeId']): d.get('employeeName', '') for d in docs}


def _admission_to_dict(obj: Admission) -> dict:
    """
    Convert an Admission ORM object to a plain dict.
    We never hardcode field names – we use model_to_dict + getattr for
    any field not returned by model_to_dict (e.g. auto fields).
    """
    d = model_to_dict(obj)
    # model_to_dict skips auto/pk fields; add them manually
    d['id']               = obj.pk
    d['ipNumber']         = obj.ipNumber
    d['uhid']             = obj.uhid
    d['admissionDateTime'] = obj.admissionDateTime.isoformat() if obj.admissionDateTime else None
    d['created_date']     = obj.created_date.isoformat() if hasattr(obj, 'created_date') and obj.created_date else None
    d['lastmodified_date'] = obj.lastmodified_date.isoformat() if hasattr(obj, 'lastmodified_date') and obj.lastmodified_date else None
    # Decimal → float
    for f in ('advance', 'ip_advance', 'total_advance', 'creditLimit', 'refunded_Amount'):
        if d.get(f) is not None:
            d[f] = float(d[f])
    return d


def _enrich(d: dict) -> dict:
    """
    Attach patient info (from Patient model) and doctor names
    (from Global MongoDB) to an admission dict.
    """
    uhid = d.get('uhid')
    if uhid:
        try:
            patient = Patient.objects.get(uhid=uhid)
            ps = PatientSerializer(patient).data
            d.update({
                'salutation':          ps.get('salutation', ''),
                'firstName':           ps.get('firstName', ''),
                'middleName':          ps.get('middleName', ''),
                'lastName':            ps.get('lastName', ''),
                'age':                 ps.get('age', ''),
                'gender':              ps.get('gender', ''),
                'phone':               ps.get('phone', ''),
                'permanent_address':   ps.get('permanent_address', ''),
                'area':                ps.get('area', ''),
                'zipcode':             ps.get('zipcode', ''),
                'city':                ps.get('city', ''),
                'state':               ps.get('state', ''),
                'customerType':        ps.get('customerType', ''),
                'insuranceCompany':    ps.get('insuranceCompany', ''),
                'privilegedCustomerId': ps.get('privilegedCustomerId', ''),
            })
        except Patient.DoesNotExist:
            pass

    doctor_map = _doctor_names_bulk([d.get('admittingDoctor'), d.get('consultingDoctor')])
    d['admittingDoctorName']  = doctor_map.get(str(d.get('admittingDoctor', '')), '')
    d['consultingDoctorName'] = doctor_map.get(str(d.get('consultingDoctor', '')), '')
    return d


def _next_ip_number() -> str:
    """Generate the next IP number based on financial year."""
    now   = datetime.now()
    year  = now.year
    month = now.month
    fy    = (year - 2001) if month < 4 else (year - 2000)
    prefix = f"S{fy:03d}"

    latest = Admission.objects.order_by('-ipNumber').first()
    if latest:
        try:
            lp, ln = latest.ipNumber.split('/')
            next_n = 500001 if lp != prefix else int(ln) + 1
        except Exception:
            next_n = 500001
    else:
        next_n = 500001
    return f"{prefix}/{next_n:06d}"


def _next_bill_number(ip_number: str) -> str:
    """
    Generate a bill number for advance slip.
    Format: <YYMM>/<6-digit-seq>
    Sequence is global across all Admission advance_payments.
    """
    now    = datetime.now()
    prefix = f"{str(now.year)[2:]}{now.month:02d}"

    # Count all existing advance bill numbers across all admissions
    # to determine the next sequence
    from django.db.models import Q
    all_payments = []
    for adm in Admission.objects.exclude(advance_payments=None).exclude(advance_payments=[]):
        if adm.advance_payments:
            all_payments.extend(adm.advance_payments)

    max_seq = 0
    for p in all_payments:
        bn = p.get('bill_number', '')
        if '/' in bn:
            try:
                seq = int(bn.split('/')[-1])
                if seq > max_seq:
                    max_seq = seq
            except ValueError:
                pass
    return f"{prefix}/{max_seq + 1:06d}"


# ──────────────────────────────────────────────────────────────────────────────
# IP Number preview
# ──────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def get_next_ip_number(request):
    return Response({"next_ipNumber": _next_ip_number()})


# ──────────────────────────────────────────────────────────────────────────────
# Patient lookup  (uses Patient model, no hardcoded fields)
# ──────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def get_op_patient_by_uhid(request, uhid):
    try:
        patient = Patient.objects.get(uhid=uhid)
        return Response(PatientSerializer(patient).data)
    except Patient.DoesNotExist:
        return Response({"error": "Patient not found"}, status=404)


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def search_op_patients(request):
    q = request.GET.get('uhid', '').strip()
    if len(q) < 4:
        return Response({"error": "Enter at least 4 characters"}, status=400)
    patients = Patient.objects.filter(uhid__icontains=q)[:20]
    return Response(PatientSerializer(patients, many=True).data)


# ──────────────────────────────────────────────────────────────────────────────
# Rooms  (uses Room model + RoomSerializer)
# ──────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def search_rooms(request):
    try:
        qs = Room.objects.filter(is_active=True)
        if request.GET.get('room_number'):
            qs = qs.filter(room_number__icontains=request.GET['room_number'])
        if request.GET.get('room_category'):
            qs = qs.filter(room_category=request.GET['room_category'])
        if request.GET.get('block'):
            qs = qs.filter(block=request.GET['block'])
        if request.GET.get('floor') not in (None, ''):
            try:
                qs = qs.filter(floor=int(request.GET['floor']))
            except ValueError:
                return Response({"error": "Floor must be a number"}, status=400)
        return Response(RoomSerializer(qs, many=True).data)
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def get_room_beds(request, room_number):
    try:
        room = Room.objects.get(room_number=room_number, is_active=True)
        return Response(RoomSerializer(room).data)
    except Room.DoesNotExist:
        return Response({"error": "Room not found or inactive"}, status=404)


# ──────────────────────────────────────────────────────────────────────────────
# Admissions  List / Create
# ──────────────────────────────────────────────────────────────────────────────

@api_view(['GET', 'POST'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def admission_view(request):
    """
    GET  /admission/   – list active admissions
    POST /admission/   – create new admission
    """
    # ── GET ───────────────────────────────────────────────────────────────────
    if request.method == 'GET':
        try:
            qs = Admission.objects.filter(is_admissionActive=True)
            ip_filter = request.GET.get('ip_number', '').strip()
            if ip_filter:
                if len(ip_filter) < 4:
                    return JsonResponse({"error": "ip_number must be at least 4 chars"}, status=400)
                qs = qs.filter(ipNumber__icontains=ip_filter)

            data = [_enrich(_admission_to_dict(a)) for a in qs]
            return JsonResponse(data, safe=False)
        except Exception as e:
            import traceback; print(traceback.format_exc())
            return JsonResponse({"error": str(e)}, status=500)

    # ── POST ──────────────────────────────────────────────────────────────────
    elif request.method == 'POST':
        try:
            raw = dict(request.data)
            data = {k: v[0] if isinstance(v, list) and len(v) == 1 else v for k, v in raw.items()}

            # Parse admissionDateTime
            dt_raw = data.get('admissionDateTime')
            try:
                admission_dt = datetime.fromisoformat(dt_raw.replace('Z', '+00:00')) if dt_raw else datetime.now()
            except Exception:
                admission_dt = datetime.now()

            ip_number = _next_ip_number()
            employee_id = request.headers.get('auth-user-id', 'system')

            # Use only fields that exist on the model; avoid hardcoding names
            adm = Admission()
            adm.uhid              = data.get('uhid', '')
            adm.ipNumber          = ip_number
            adm.ipserial_number   = data.get('ipserial_number', '')
            adm.admissionDateTime = admission_dt
            adm.admittingDoctor   = data.get('admittingDoctor', '')
            adm.consultingDoctor  = data.get('consultingDoctor', '')
            adm.packageName       = data.get('packageName', '')
            adm.roomNo            = data.get('roomNo', '')
            adm.bedNo             = data.get('bedNo', '')
            adm.reasonForAdmission = data.get('reasonForAdmission', '')
            adm.mlc_type          = data.get('mlc_type') or None
            adm.mlc_remarks       = data.get('mlc_remarks') or None
            adm.is_admissionActive = True
            adm.is_advanceActive  = False
            adm.is_roomCleaned    = False
            adm.is_roomActive     = False
            adm.is_discharged     = False
            adm.advance_payments  = []
            if hasattr(adm, 'created_by'):
                adm.created_by = employee_id
                adm.lastmodified_by = employee_id
            adm.save()

            result = _enrich(_admission_to_dict(adm))
            return JsonResponse({'message': 'Admission created successfully!', 'data': result}, status=201)
        except Exception as e:
            import traceback; print(traceback.format_exc())
            return JsonResponse({'error': str(e)}, status=500)


# ──────────────────────────────────────────────────────────────────────────────
# Admission Detail  GET / PUT / DELETE   (lookup by ipNumber – unique per patient)
# ──────────────────────────────────────────────────────────────────────────────

@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def admission_detail(request, ip_number):
    """
    GET    /admission/<ip_number>/
    PUT    /admission/<ip_number>/
    DELETE /admission/<ip_number>/   – soft cancel
    """
    try:
        try:
            adm = Admission.objects.get(ipNumber=ip_number, is_admissionActive=True)
        except Admission.DoesNotExist:
            return JsonResponse({'error': 'Admission not found'}, status=404)

        employee_id = request.headers.get('auth-user-id', 'system')

        # ── GET ───────────────────────────────────────────────────────────────
        if request.method == 'GET':
            return JsonResponse(_enrich(_admission_to_dict(adm)))

        # ── PUT ───────────────────────────────────────────────────────────────
        elif request.method == 'PUT':
            raw = dict(request.data)
            data = {k: v[0] if isinstance(v, list) and len(v) == 1 else v for k, v in raw.items()}

            updatable = {
                'admittingDoctor', 'consultingDoctor',
                'roomNo', 'bedNo', 'packageName',
                'reasonForAdmission',
                'mlc_type', 'mlc_doc', 'mlc_remarks',
                'admissionDateTime',
            }
            for field in updatable:
                if field in data:
                    if field == 'admissionDateTime':
                        try:
                            setattr(adm, field, datetime.fromisoformat(data[field].replace('Z', '+00:00')))
                        except Exception:
                            pass
                    else:
                        setattr(adm, field, data[field])

            if hasattr(adm, 'lastmodified_by'):
                adm.lastmodified_by = employee_id
            adm.save()
            return JsonResponse({'message': 'Admission updated successfully!'})

        # ── DELETE (soft cancel) ──────────────────────────────────────────────
        elif request.method == 'DELETE':
            raw = dict(request.data)
            data = {k: v[0] if isinstance(v, list) and len(v) == 1 else v for k, v in raw.items()}
            adm.is_admissionActive = False
            if hasattr(adm, 'cancelled_by'):
                adm.cancelled_by = employee_id
            if hasattr(adm, 'cancellation_reason'):
                adm.cancellation_reason = data.get('cancellationReason', '')
            if hasattr(adm, 'lastmodified_by'):
                adm.lastmodified_by = employee_id
            adm.save()
            return JsonResponse({'message': 'Admission cancelled successfully'})

    except Exception as e:
        import traceback; print(traceback.format_exc())
        return JsonResponse({'error': str(e)}, status=500)


# ──────────────────────────────────────────────────────────────────────────────
# Advance  – Add / Update  (all stored inside the same Admission record)
# ──────────────────────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def add_advance(request, ip_number):
    """
    POST /admission/<ip_number>/advance/
    Body: { amount, payment_mode, remarks, type }
      type = "advance" | "ip_advance"

    Each call appends one entry to advance_payments[], regenerates totals,
    and returns the full enriched admission + a print-ready bill dict.
    """
    try:
        try:
            adm = Admission.objects.get(ipNumber=ip_number, is_admissionActive=True)
        except Admission.DoesNotExist:
            return JsonResponse({'error': 'Admission not found'}, status=404)

        raw  = dict(request.data)
        data = {k: v[0] if isinstance(v, list) and len(v) == 1 else v for k, v in raw.items()}

        try:
            amount = Decimal(str(data.get('amount', 0)))
        except InvalidOperation:
            return JsonResponse({'error': 'Invalid amount'}, status=400)

        if amount <= 0:
            return JsonResponse({'error': 'Amount must be positive'}, status=400)

        adv_type      = data.get('type', 'advance')          # "advance" or "ip_advance"
        payment_mode  = data.get('payment_mode', 'Cash')
        remarks       = data.get('remarks', '')
        employee_id   = request.headers.get('auth-user-id', 'system')
        bill_number   = _next_bill_number(ip_number)
        paid_date     = datetime.now()

        # Build the payment entry
        entry = {
            'bill_number':   bill_number,
            'amount':        float(amount),
            'payment_mode':  payment_mode,
            'remarks':       remarks,
            'type':          adv_type,
            'paid_date':     paid_date.isoformat(),
            'created_by':    employee_id,
            'advance_status': 'Not Paid',   # default; can be updated later
        }

        # Append to advance_payments list
        payments = adm.advance_payments or []
        payments.append(entry)
        adm.advance_payments = payments

        # Update running totals
        total = sum(Decimal(str(p['amount'])) for p in payments)
        adm.total_advance = total

        adv_total    = sum(Decimal(str(p['amount'])) for p in payments if p.get('type') == 'advance')
        ip_adv_total = sum(Decimal(str(p['amount'])) for p in payments if p.get('type') == 'ip_advance')
        adm.advance    = adv_total    if adv_total    > 0 else None
        adm.ip_advance = ip_adv_total if ip_adv_total > 0 else None

        adm.is_advanceActive = True
        if hasattr(adm, 'lastmodified_by'):
            adm.lastmodified_by = employee_id
        adm.save()

        # Build bill data for print
        try:
            patient = Patient.objects.get(uhid=adm.uhid)
            ps      = PatientSerializer(patient).data
            patient_name = f"{ps.get('salutation','')} {ps.get('firstName','')} {ps.get('lastName','')}".strip()
            room_no = adm.roomNo
        except Exception:
            patient_name = adm.uhid
            room_no      = adm.roomNo

        bill_data = {
            'bill_number':      bill_number,
            'ip_number':        adm.ipNumber,
            'uhid':             adm.uhid,
            'patient_name':     patient_name,
            'room_no':          room_no,
            'bill_date':        paid_date.strftime('%d/%m/%Y:%H:%M:%S'),
            'amount':           float(amount),
            'payment_mode':     payment_mode,
            'remarks':          remarks,
            'type':             adv_type,
            'total_advance':    float(adm.total_advance or 0),
            'created_by':       employee_id,
        }

        result = _enrich(_admission_to_dict(adm))
        return JsonResponse({
            'message': 'Advance added successfully!',
            'data':    result,
            'bill':    bill_data,
        }, status=201)

    except Exception as e:
        import traceback; print(traceback.format_exc())
        return JsonResponse({'error': str(e)}, status=500)


@api_view(['PUT'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def update_advance_finance(request, ip_number):
    """
    PUT /admission/<ip_number>/finance/
    Update creditLimit, or correct advance / ip_advance totals directly.
    Body: { creditLimit?, advance?, ip_advance? }
    """
    try:
        try:
            adm = Admission.objects.get(ipNumber=ip_number, is_admissionActive=True)
        except Admission.DoesNotExist:
            return JsonResponse({'error': 'Admission not found'}, status=404)

        raw  = dict(request.data)
        data = {k: v[0] if isinstance(v, list) and len(v) == 1 else v for k, v in raw.items()}
        employee_id = request.headers.get('auth-user-id', 'system')

        for field in ('creditLimit', 'advance', 'ip_advance'):
            if field in data and data[field] not in (None, ''):
                try:
                    setattr(adm, field, Decimal(str(data[field])))
                except InvalidOperation:
                    pass

        # Recalculate total_advance from advance_payments (source of truth)
        payments = adm.advance_payments or []
        if payments:
            adm.total_advance = sum(Decimal(str(p['amount'])) for p in payments)
        if hasattr(adm, 'lastmodified_by'):
            adm.lastmodified_by = employee_id
        adm.save()

        return JsonResponse({'message': 'Finance updated successfully!', 'data': _enrich(_admission_to_dict(adm))})
    except Exception as e:
        import traceback; print(traceback.format_exc())
        return JsonResponse({'error': str(e)}, status=500)


# ──────────────────────────────────────────────────────────────────────────────
# Advance search / list  (used for the bottom table in IP Advance page)
# ──────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def list_advances(request):
    """
    GET /advances/?from_date=&to_date=&uhid=&ip_number=
    Returns a flat list of advance payment entries across all admissions.
    """
    try:
        from_date_str = request.GET.get('from_date', '')
        to_date_str   = request.GET.get('to_date', '')
        uhid_filter   = request.GET.get('uhid', '').strip()
        ip_filter     = request.GET.get('ip_number', '').strip()

        qs = Admission.objects.filter(is_admissionActive=True)
        if uhid_filter:
            qs = qs.filter(uhid__icontains=uhid_filter)
        if ip_filter:
            qs = qs.filter(ipNumber__icontains=ip_filter)

        from_date = None
        to_date   = None
        if from_date_str:
            try:
                from_date = datetime.strptime(from_date_str, '%Y-%m-%d').date()
            except ValueError:
                pass
        if to_date_str:
            try:
                to_date = datetime.strptime(to_date_str, '%Y-%m-%d').date()
            except ValueError:
                pass

        rows = []
        for adm in qs:
            payments = adm.advance_payments or []
            try:
                patient = Patient.objects.get(uhid=adm.uhid)
                ps = PatientSerializer(patient).data
                patient_name = f"{ps.get('firstName', '')} {ps.get('lastName', '')}".strip()
            except Exception:
                patient_name = adm.uhid

            for p in payments:
                paid_date_str = p.get('paid_date', '')
                if from_date or to_date:
                    try:
                        pd = datetime.fromisoformat(paid_date_str).date()
                        if from_date and pd < from_date:
                            continue
                        if to_date and pd > to_date:
                            continue
                    except Exception:
                        pass

                rows.append({
                    'bill_date':        paid_date_str[:10] if paid_date_str else '',
                    'bill_number':      p.get('bill_number', ''),
                    'payment_mode':     p.get('payment_mode', ''),
                    'advance_reference': p.get('remarks', ''),
                    'advance_status':   p.get('advance_status', 'Not Paid'),
                    'uhid':             adm.uhid,
                    'patient':          patient_name,
                    'description':      p.get('type', ''),
                    'advance_amount':   p.get('amount', 0),
                    'balance_amount':   float(adm.total_advance or 0),
                    'ip_number':        adm.ipNumber,
                    'room_no':          adm.roomNo,
                })

        return JsonResponse(rows, safe=False)
    except Exception as e:
        import traceback; print(traceback.format_exc())
        return JsonResponse({'error': str(e)}, status=500)