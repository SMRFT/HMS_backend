from decimal import Decimal, InvalidOperation
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt
from pyauth.auth import HasRoleAndDataPermission
from ..models import Admission, Room, Patient, InsuranceProvider
import traceback
import json
from datetime import datetime


# ──────────────────────────────────────────────────────────────────────────────
# IP Number Preview  →  GET /next-ip-number/
# ──────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def get_next_ip_number(request):
    try:
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

        return JsonResponse({"success": True, "next_ipNumber": f"{prefix}/{next_n:06d}"})
    except Exception as e:
        traceback.print_exc()
        return JsonResponse({"success": False, "error": str(e)}, status=500)
    

def parse_json_field(value):
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    if value is None:
        return []
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict):
                return [parsed]
        except Exception:
            return []
    return []

# --------------------------------------------------
# SEARCH ROOMS
# --------------------------------------------------
@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def search_rooms(request):

    try:

        result = []

        # ==================================================
        # STEP 1 — BUILD ADMISSION MAP
        # ==================================================
        admission_map = {}

        for admission in Admission.objects.all():

            if not admission.is_admissionActive:
                continue

            if admission.is_discharged:
                continue

            details = parse_json_field(admission.room_details)
            shifts  = parse_json_field(admission.roomShitingDetails)

            for entry in details + shifts:

                if not isinstance(entry, dict):
                    continue

                room_no = str(entry.get("roomNo", "")).strip()
                bed_no  = str(entry.get("bedNo", "")).strip()

                if not room_no or not bed_no:
                    continue

                admission_map[(room_no, bed_no)] = True


        # ==================================================
        # STEP 2 — FILTER ROOMS IN PYTHON (DJONGO SAFE)
        # ==================================================
        room_number_filter = request.GET.get("room_number")
        category_filter    = request.GET.get("room_category")
        block_filter       = request.GET.get("block")
        floor_filter       = request.GET.get("floor")

        for room in Room.objects.all():

            if not room.is_active:
                continue

            if room_number_filter:
                if room_number_filter.lower() not in room.room_number.lower():
                    continue

            if category_filter:
                if room.room_category != category_filter:
                    continue

            if block_filter:
                if room.block != block_filter:
                    continue

            if floor_filter:
                try:
                    if room.floor != int(floor_filter):
                        continue
                except:
                    continue


            # ==================================================
            # STEP 3 — BED STATUS
            # ==================================================
            beds = parse_json_field(room.beds)

            beds_data = []

            for bed in beds:

                if not isinstance(bed, dict):
                    continue

                bed_number = str(bed.get("bed_number", "")).strip()

                if not bed_number:
                    continue

                if room.room_blocked or room.room_status == "Blocked":

                    status = "Maintenance"

                else:

                    key = (str(room.room_number), bed_number)

                    if key in admission_map:
                        status = "Occupied"
                    else:
                        status = "Available"

                beds_data.append({
                    "bed_number": bed_number,
                    "status": status
                })


            result.append({
                "room_number": room.room_number,
                "room_type": room.room_type,
                "room_category": room.room_category,
                "block": room.block,
                "floor": room.floor,
                "beds": beds_data
            })


        return Response(result)

    except Exception as e:

        print("SEARCH ROOMS ERROR:", str(e))
        traceback.print_exc()

        return Response({"error": str(e)}, status=500)
    

# ──────────────────────────────────────────────────────────────────────────────
# Admissions List / Create  →  GET/POST /admission/
# ──────────────────────────────────────────────────────────────────────────────
@api_view(['GET', 'POST'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def admission_view(request):
    # ── GET ─────────────────────────────────────────────
    if request.method == 'GET':
        try:
            ip_filter = request.GET.get('ip_number', '').strip()

            if ip_filter and len(ip_filter) < 4:
                return JsonResponse({"error": "ip_number must be at least 4 chars"}, status=400)

            # ❗ FETCH ALL (DJONGO SAFE)
            admissions = list(Admission.objects.all())

            data = []

            for adm in admissions:

                # ✅ FILTER IN PYTHON (NOT DB)
                if not adm.is_admissionActive:
                    continue

                if ip_filter:
                    if ip_filter.lower() not in (adm.ipNumber or "").lower():
                        continue

                # ✅ SAFE JSON FIELD
                room_details = adm.room_details if isinstance(adm.room_details, list) else []
                current_room = room_details[0] if room_details else {}

                data.append({
                    "id": str(adm.pk),
                    "uhid": adm.uhid,
                    "ipNumber": adm.ipNumber,
                    "admissionDateTime": adm.admissionDateTime.isoformat() if adm.admissionDateTime else None,
                    "admittingDoctor": adm.admittingDoctor or "",
                    "consultingDoctor": adm.consultingDoctor or "",
                    "packageName": adm.packageName or "",
                    "roomNo": current_room.get("roomNo", ""),
                    "bedNo": current_room.get("bedNo", ""),
                    "reasonForAdmission": adm.reasonForAdmission or "",
                    "mlc_type": adm.mlc_type or "",
                    "mlc_remarks": adm.mlc_remarks or "",
                    "advance_payments": adm.advance_payments if isinstance(adm.advance_payments, list) else [],
                    "is_advanceActive": bool(adm.is_advanceActive),
                    "is_admissionActive": bool(adm.is_admissionActive),
                    "is_discharged": bool(adm.is_discharged),
                })

            return JsonResponse({
                "success": True,
                "data": data
            }, safe=False)

        except Exception as e:
            traceback.print_exc()
            return JsonResponse({"error": str(e)}, status=500)

    # ── POST ─────────────────────────────────────────────
    elif request.method == 'POST':
        try:
            data = {k: request.data.get(k) for k in request.data}

            uhid = str(data.get('uhid', '')).strip()
            if not uhid:
                return JsonResponse({"error": "UHID is required"}, status=400)

            # ✅ DJONGO SAFE FILTER
            existing = None
            for adm in Admission.objects.filter(uhid=uhid):
                if adm.is_admissionActive and not adm.is_discharged:
                    existing = adm
                    break

            if existing:
                return JsonResponse({
                    "error": f"Patient already has active admission. IP: {existing.ipNumber}",
                    "ipNumber": existing.ipNumber
                }, status=400)

            # ✅ SAFE DATETIME
            admission_dt = parse_datetime(str(data.get('admissionDateTime') or '')) or timezone.now()

            # ==================================================
            # ✅ SAFE IP NUMBER GENERATION (NO order_by)
            # ==================================================
            now_dt = datetime.now()
            fy = (now_dt.year - 2001) if now_dt.month < 4 else (now_dt.year - 2000)
            prefix = f"S{fy:03d}"

            max_num = 500000

            for adm in Admission.objects.all():
                ip = adm.ipNumber or ""
                if "/" in ip:
                    try:
                        p, n = ip.split("/")
                        if p == prefix:
                            max_num = max(max_num, int(n))
                    except:
                        continue

            next_n = max_num + 1
            ip_number = f"{prefix}/{next_n:06d}"

            # ==================================================
            # ROOM JSON
            # ==================================================
            room_details = [{
                "roomNo": str(data.get("roomNo") or ""),
                "bedNo": str(data.get("bedNo") or ""),
                "is_roomActive": True,
                "is_roomCleaned": False
            }]

            # ==================================================
            # CREATE (SAFE)
            # ==================================================
            adm = Admission.objects.create(
                uhid=uhid,
                ipNumber=ip_number,
                admissionDateTime=admission_dt,
                admittingDoctor=str(data.get('admittingDoctor') or ""),
                consultingDoctor=data.get('consultingDoctor') or None,
                packageName=data.get('packageName') or None,
                room_details=room_details,
                roomShitingDetails=[],
                advance_payments=[],
                reasonForAdmission=data.get('reasonForAdmission') or None,
                mlc_type=data.get('mlc_type') or None,
                mlc_remarks=data.get('mlc_remarks') or None,
                is_admissionActive=True,
                is_advanceActive=False,
                is_discharged=False,
            )

            return JsonResponse({
                "success": True,
                "message": "Admission created successfully",
                "data": {
                    "id": str(adm.pk),
                    "uhid": adm.uhid,
                    "ipNumber": adm.ipNumber
                }
            }, status=201)

        except Exception as e:
            traceback.print_exc()
            return JsonResponse({"success": False, "error": str(e)}, status=500)
        

# ──────────────────────────────────────────────────────────────────────────────
# Admission Detail  →  GET/PUT/DELETE /admission/<ip_number>/
# ──────────────────────────────────────────────────────────────────────────────

@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def admission_detail(request, ip_number):
    try:
        try:
            adm = Admission.objects.get(ipNumber=ip_number, is_admissionActive=True)
        except Admission.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Admission not found'}, status=404)

        employee_id = request.headers.get('auth-user-id', 'system')

        # Shared patient enrichment (inline, no helper)
        def _patient_block(uhid):
            pd = {}
            ins_name = ''
            try:
                pt = Patient.objects.get(uhid=uhid)
                if pt.company_code:
                    try:
                        prov = InsuranceProvider.objects.get(company_code=pt.company_code)
                        ins_name = prov.company_name
                    except InsuranceProvider.DoesNotExist:
                        ins_name = pt.company_code or ''
                pd = {
                    'salutation':           pt.salutation or '',
                    'firstName':            pt.firstName or '',
                    'lastName':             pt.lastName or '',
                    'age':                  pt.age,
                    'gender':               pt.gender or '',
                    'mobilePhone':          pt.mobilePhone or '',
                    'permanent_address':    pt.permanent_address or '',
                    'area':                 pt.area or '',
                    'zipcode':              pt.zipcode or '',
                    'city':                 pt.city or '',
                    'state':                pt.state or '',
                    'customer_type':        pt.customer_type or '',
                    'company_code':         pt.company_code or '',
                    'insuranceCompanyName': ins_name,
                }
            except Patient.DoesNotExist:
                pass
            return pd

        def _build_result(adm):
            room_details = adm.room_details if isinstance(adm.room_details, list) else []
            current_room = room_details[0] if room_details else {}
            return {
                'id':                  str(adm.pk),
                'uhid':                adm.uhid,
                'ipNumber':            adm.ipNumber,
                'admissionDateTime':   adm.admissionDateTime.isoformat() if adm.admissionDateTime else None,
                'admittingDoctor':     adm.admittingDoctor or '',
                'consultingDoctor':    adm.consultingDoctor or '',
                'packageName':         adm.packageName or '',
                'roomNo':              current_room.get('roomNo', ''),
                'bedNo':               current_room.get('bedNo', ''),
                'reasonForAdmission':  adm.reasonForAdmission or '',
                'mlc_type':            adm.mlc_type or '',
                'mlc_remarks':         adm.mlc_remarks or '',
                'advance_payments':    adm.advance_payments or [],
                'is_advanceActive':    adm.is_advanceActive,
                'is_admissionActive':  adm.is_admissionActive,
                'is_discharged':       adm.is_discharged,
                'created_date':        adm.created_date.isoformat() if hasattr(adm, 'created_date') and adm.created_date else None,
                'lastmodified_date':   adm.lastmodified_date.isoformat() if hasattr(adm, 'lastmodified_date') and adm.lastmodified_date else None,
                **_patient_block(adm.uhid),
            }

        # ── GET ───────────────────────────────────────────────────────────────
        if request.method == 'GET':
            return JsonResponse({"success": True, "data": _build_result(adm)})

        # ── PUT ───────────────────────────────────────────────────────────────
        elif request.method == 'PUT':
            raw  = dict(request.data)
            data = {k: v[0] if isinstance(v, list) and len(v) == 1 else v for k, v in raw.items()}

            # Update scalar fields
            for field in ('admittingDoctor', 'consultingDoctor', 'packageName',
                          'reasonForAdmission', 'mlc_type', 'mlc_remarks'):
                if field in data:
                    setattr(adm, field, data[field] or None)

            if 'admissionDateTime' in data and data['admissionDateTime']:
                try:
                    setattr(adm, 'admissionDateTime',
                            datetime.fromisoformat(data['admissionDateTime'].replace('Z', '+00:00')))
                except Exception:
                    pass

            # Update room_details JSONField when roomNo/bedNo change
            new_room = str(data.get('roomNo', '') or '')
            new_bed  = str(data.get('bedNo', '') or '')
            if new_room or new_bed:
                existing_details = adm.room_details if isinstance(adm.room_details, list) else []
                # Mark old room as inactive
                for entry in existing_details:
                    if isinstance(entry, dict):
                        entry['is_roomActive'] = False
                # Append new active room
                existing_details.append({
                    'roomNo':         new_room,
                    'bedNo':          new_bed,
                    'is_roomActive':  True,
                    'is_roomCleaned': False,
                })
                adm.room_details = existing_details

            mlc_doc_file = request.FILES.get('mlc_doc')
            if mlc_doc_file:
                adm.mlc_doc = mlc_doc_file.name

            if hasattr(adm, 'lastmodified_by'):
                adm.lastmodified_by = employee_id
            adm.save()

            return JsonResponse({
                'success': True,
                'message': 'Admission updated successfully!',
                'data': _build_result(adm)
            })

        # ── DELETE ────────────────────────────────────────────────────────────
        elif request.method == 'DELETE':
            raw  = dict(request.data)
            data = {k: v[0] if isinstance(v, list) and len(v) == 1 else v for k, v in raw.items()}

            adm.is_admissionActive = False
            if hasattr(adm, 'cancelled_by'):
                adm.cancelled_by = employee_id
            if hasattr(adm, 'cancellation_reason'):
                adm.cancellation_reason = data.get('cancellationReason', '')
            if hasattr(adm, 'lastmodified_by'):
                adm.lastmodified_by = employee_id
            adm.save()
            return JsonResponse({'success': True, 'message': 'Admission cancelled successfully'})

    except Exception as e:
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# ──────────────────────────────────────────────────────────────────────────────
# Advance  →  POST /admission/<ip_number>/add-advance/
# ──────────────────────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def add_advance(request, ip_number):
    try:
        try:
            adm = Admission.objects.get(ipNumber=ip_number, is_admissionActive=True)
        except Admission.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Admission not found'}, status=404)

        raw  = dict(request.data)
        data = {k: v[0] if isinstance(v, list) and len(v) == 1 else v for k, v in raw.items()}

        try:
            amount = Decimal(str(data.get('amount', 0)))
        except InvalidOperation:
            return JsonResponse({'success': False, 'error': 'Invalid amount'}, status=400)
        if amount <= 0:
            return JsonResponse({'success': False, 'error': 'Amount must be positive'}, status=400)

        adv_type     = data.get('type', 'advance')
        payment_mode = data.get('payment_mode', 'Cash')
        remarks      = data.get('remarks', '')
        employee_id  = request.headers.get('auth-user-id', 'system')
        paid_date    = datetime.now()

        # Generate bill number from Admission.advance_payments only — no collection
        now_dt  = datetime.now()
        prefix  = f"{str(now_dt.year)[2:]}{now_dt.month:02d}"
        max_seq = 0
        for a in Admission.objects.exclude(advance_payments=None).exclude(advance_payments=[]):
            for p in (a.advance_payments or []):
                bn = p.get('bill_number', '')
                if '/' in bn:
                    try:
                        seq = int(bn.split('/')[-1])
                        if seq > max_seq:
                            max_seq = seq
                    except ValueError:
                        pass
        bill_number = f"{prefix}/{max_seq + 1:06d}"

        entry = {
            'bill_number':    bill_number,
            'amount':         float(amount),
            'payment_mode':   payment_mode,
            'remarks':        remarks,
            'type':           adv_type,
            'paid_date':      paid_date.isoformat(),
            'created_by':     employee_id,
            'advance_status': 'Not Paid',
        }

        payments = adm.advance_payments if isinstance(adm.advance_payments, list) else []
        payments.append(entry)
        adm.advance_payments = payments

        total        = sum(Decimal(str(p['amount'])) for p in payments)
        adv_total    = sum(Decimal(str(p['amount'])) for p in payments if p.get('type') == 'advance')
        ip_adv_total = sum(Decimal(str(p['amount'])) for p in payments if p.get('type') == 'ip_advance')

        adm.total_advance    = total
        adm.advance          = adv_total    if adv_total    > 0 else None
        adm.ip_advance       = ip_adv_total if ip_adv_total > 0 else None
        adm.is_advanceActive = True

        if hasattr(adm, 'lastmodified_by'):
            adm.lastmodified_by = employee_id
        adm.save()

        # Patient name for bill
        patient_name = adm.uhid
        try:
            pt = Patient.objects.get(uhid=adm.uhid)
            patient_name = f"{pt.salutation or ''} {pt.firstName or ''} {pt.lastName or ''}".strip()
        except Patient.DoesNotExist:
            pass

        # roomNo from room_details
        room_details = adm.room_details if isinstance(adm.room_details, list) else []
        current_room = next((r for r in reversed(room_details) if isinstance(r, dict) and r.get('is_roomActive')), {})
        room_no = current_room.get('roomNo', '')

        bill_data = {
            'bill_number':   bill_number,
            'ip_number':     adm.ipNumber,
            'uhid':          adm.uhid,
            'patient_name':  patient_name,
            'room_no':       room_no,
            'bill_date':     paid_date.strftime('%d/%m/%Y:%H:%M:%S'),
            'amount':        float(amount),
            'payment_mode':  payment_mode,
            'remarks':       remarks,
            'type':          adv_type,
            'total_advance': float(adm.total_advance or 0),
            'created_by':    employee_id,
        }

        # Build enriched result inline
        patient_data = {}
        insurance_company_name = ''
        try:
            pt = Patient.objects.get(uhid=adm.uhid)
            if pt.company_code:
                try:
                    prov = InsuranceProvider.objects.get(company_code=pt.company_code)
                    insurance_company_name = prov.company_name
                except InsuranceProvider.DoesNotExist:
                    insurance_company_name = pt.company_code or ''
            patient_data = {
                'salutation':           pt.salutation or '',
                'firstName':            pt.firstName or '',
                'lastName':             pt.lastName or '',
                'age':                  pt.age,
                'gender':               pt.gender or '',
                'mobilePhone':          pt.mobilePhone or '',
                'customer_type':        pt.customer_type or '',
                'company_code':         pt.company_code or '',
                'insuranceCompanyName': insurance_company_name,
            }
        except Patient.DoesNotExist:
            pass

        result = {
            'id':                  str(adm.pk),
            'uhid':                adm.uhid,
            'ipNumber':            adm.ipNumber,
            'admissionDateTime':   adm.admissionDateTime.isoformat() if adm.admissionDateTime else None,
            'admittingDoctor':     adm.admittingDoctor or '',
            'consultingDoctor':    adm.consultingDoctor or '',
            'roomNo':              room_no,
            'bedNo':               current_room.get('bedNo', ''),
            'advance':             float(adm.advance) if adm.advance is not None else None,
            'ip_advance':          float(adm.ip_advance) if adm.ip_advance is not None else None,
            'total_advance':       float(adm.total_advance) if adm.total_advance is not None else None,
            'advance_payments':    adm.advance_payments or [],
            'is_advanceActive':    adm.is_advanceActive,
            **patient_data,
        }

        return JsonResponse({
            'success': True,
            'message': 'Advance added!',
            'data':    result,
            'bill':    bill_data
        }, status=201)

    except Exception as e:
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# ──────────────────────────────────────────────────────────────────────────────
# Finance Update  →  PUT /admission/<ip_number>/finance/
# ──────────────────────────────────────────────────────────────────────────────

@api_view(['PUT'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def update_advance_finance(request, ip_number):
    try:
        try:
            adm = Admission.objects.get(ipNumber=ip_number, is_admissionActive=True)
        except Admission.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Admission not found'}, status=404)

        raw  = dict(request.data)
        data = {k: v[0] if isinstance(v, list) and len(v) == 1 else v for k, v in raw.items()}
        employee_id = request.headers.get('auth-user-id', 'system')

        for field in ('creditLimit', 'advance', 'ip_advance'):
            if field in data and data[field] not in (None, ''):
                try:
                    setattr(adm, field, Decimal(str(data[field])))
                except InvalidOperation:
                    pass

        payments = adm.advance_payments if isinstance(adm.advance_payments, list) else []
        if payments:
            adm.total_advance = sum(Decimal(str(p['amount'])) for p in payments)

        if hasattr(adm, 'lastmodified_by'):
            adm.lastmodified_by = employee_id
        adm.save()

        # Inline enriched result
        patient_data = {}
        insurance_company_name = ''
        try:
            pt = Patient.objects.get(uhid=adm.uhid)
            if pt.company_code:
                try:
                    prov = InsuranceProvider.objects.get(company_code=pt.company_code)
                    insurance_company_name = prov.company_name
                except InsuranceProvider.DoesNotExist:
                    insurance_company_name = pt.company_code or ''
            patient_data = {
                'salutation':           pt.salutation or '',
                'firstName':            pt.firstName or '',
                'lastName':             pt.lastName or '',
                'age':                  pt.age,
                'gender':               pt.gender or '',
                'mobilePhone':          pt.mobilePhone or '',
                'customer_type':        pt.customer_type or '',
                'company_code':         pt.company_code or '',
                'insuranceCompanyName': insurance_company_name,
            }
        except Patient.DoesNotExist:
            pass

        result = {
            'id':              str(adm.pk),
            'uhid':            adm.uhid,
            'ipNumber':        adm.ipNumber,
            'advance':         float(adm.advance) if adm.advance is not None else None,
            'ip_advance':      float(adm.ip_advance) if adm.ip_advance is not None else None,
            'total_advance':   float(adm.total_advance) if adm.total_advance is not None else None,
            'creditLimit':     float(adm.creditLimit) if adm.creditLimit is not None else None,
            'advance_payments': adm.advance_payments or [],
            **patient_data,
        }

        return JsonResponse({'success': True, 'message': 'Finance updated!', 'data': result})

    except Exception as e:
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# ──────────────────────────────────────────────────────────────────────────────
# Advance List  →  GET /advances/
# ──────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def list_advances(request):
    try:
        from_date_str = request.GET.get('from_date', '').strip()
        to_date_str   = request.GET.get('to_date', '').strip()
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

        # Bulk-fetch patients
        uhids    = list(qs.values_list('uhid', flat=True))
        patients = {p.uhid: p for p in Patient.objects.filter(uhid__in=uhids)}

        rows = []
        for adm in qs:
            payments = adm.advance_payments if isinstance(adm.advance_payments, list) else []
            pt = patients.get(adm.uhid)
            patient_name = f"{pt.firstName or ''} {pt.lastName or ''}".strip() if pt else adm.uhid

            room_details = adm.room_details if isinstance(adm.room_details, list) else []
            current_room = next((r for r in reversed(room_details) if isinstance(r, dict) and r.get('is_roomActive')), {})

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
                    'bill_date':         paid_date_str[:10] if paid_date_str else '',
                    'bill_number':       p.get('bill_number', ''),
                    'payment_mode':      p.get('payment_mode', ''),
                    'advance_reference': p.get('remarks', ''),
                    'advance_status':    p.get('advance_status', 'Not Paid'),
                    'uhid':              adm.uhid,
                    'patient':           patient_name,
                    'description':       p.get('type', ''),
                    'advance_amount':    p.get('amount', 0),
                    'balance_amount':    float(adm.total_advance or 0),
                    'ip_number':         adm.ipNumber,
                    'room_no':           current_room.get('roomNo', ''),
                })

        return JsonResponse({"success": True, "data": rows}, safe=False)

    except Exception as e:
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': str(e)}, status=500)