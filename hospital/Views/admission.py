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

        max_num = 500000
        for adm in Admission.objects.all():
            ip = adm.ipNumber or ""
            if "/" in ip:
                try:
                    p, n = ip.split("/")
                    if p == prefix:
                        max_num = max(max_num, int(n))
                except Exception:
                    continue

        return JsonResponse({"success": True, "next_ipNumber": f"{prefix}/{max_num + 1:06d}"})
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


# ──────────────────────────────────────────────────────────────────────────────
# SEARCH ROOMS  →  GET /search-rooms/
# ──────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def search_rooms(request):
    try:
        result = []

        # ─────────────────────────────────────────────
        # STEP 1 — BUILD BED STATUS MAP FROM ADMISSION
        # ─────────────────────────────────────────────
        # Key: (room_no, bed_no)
        # Value:
        #   Occupied
        #   Available
        #   Available - Not Cleaned
        # ─────────────────────────────────────────────
        admission_map = {}

        for admission in Admission.objects.all():

            if not admission.is_admitted:
                continue

            if admission.is_discharged:
                continue

            # Original room entries
            details = parse_json_field(admission.room_details)

            for entry in details:
                if not isinstance(entry, dict):
                    continue

                room_no = str(entry.get("roomNo", "")).strip()
                bed_no = str(entry.get("bedNo", "")).strip()

                if not room_no or not bed_no:
                    continue

                is_room_active = bool(entry.get("is_roomActive", False))
                is_room_cleaned = bool(entry.get("is_roomCleaned", False))

                key = (room_no, bed_no)

                # true + false => Occupied
                if is_room_active and not is_room_cleaned:
                    admission_map[key] = "Occupied"

                # false + true => Available
                elif not is_room_active and is_room_cleaned:
                    admission_map[key] = "Available"

                # false + false => Available - Not Cleaned
                elif not is_room_active and not is_room_cleaned:
                    admission_map[key] = "Available - Not Cleaned"

            # Shifted room entries
            shifts = parse_json_field(admission.roomShitingDetails)

            for shift in shifts:
                if not isinstance(shift, dict):
                    continue

                room_no = str(shift.get("newRoomNo", "")).strip()
                bed_no = str(shift.get("newBedNo", "")).strip()

                if not room_no or not bed_no:
                    continue

                is_room_active = bool(shift.get("is_roomActive", False))
                is_room_cleaned = bool(shift.get("is_roomCleaned", False))

                key = (room_no, bed_no)

                # true + false => Occupied
                if is_room_active and not is_room_cleaned:
                    admission_map[key] = "Occupied"

                # false + true => Available
                elif not is_room_active and is_room_cleaned:
                    admission_map[key] = "Available"

                # false + false => Available - Not Cleaned
                elif not is_room_active and not is_room_cleaned:
                    admission_map[key] = "Available - Not Cleaned"

        # ─────────────────────────────────────────────
        # STEP 2 — APPLY ROOM FILTERS
        # ─────────────────────────────────────────────
        room_number_filter = request.GET.get("room_number")
        category_filter = request.GET.get("room_category")
        block_filter = request.GET.get("block")
        floor_filter = request.GET.get("floor")

        for room in Room.objects.all():

            if not room.is_active:
                continue

            if room_number_filter:
                if room_number_filter.lower() not in str(room.room_number).lower():
                    continue

            if category_filter:
                if str(room.room_category) != str(category_filter):
                    continue

            if block_filter:
                if str(room.block) != str(block_filter):
                    continue

            if floor_filter:
                try:
                    if int(room.floor) != int(floor_filter):
                        continue
                except Exception:
                    continue

            # ─────────────────────────────────────────
            # STEP 3 — BUILD BED STATUS FOR ROOM
            # ─────────────────────────────────────────
            beds = parse_json_field(room.beds)
            beds_data = []

            for bed in beds:
                if not isinstance(bed, dict):
                    continue

                bed_number = str(bed.get("bed_number", "")).strip()

                if not bed_number:
                    continue

                # Room itself blocked
                if room.room_blocked or str(room.room_status).lower() == "blocked":
                    status = "Maintenance"

                else:
                    key = (str(room.room_number).strip(), bed_number)

                    # Default if no admission entry exists
                    status = admission_map.get(key, "Available")

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
                "beds": beds_data,
            })

        return Response(result, status=200)

    except Exception as e:
        print("SEARCH ROOMS ERROR:", str(e))
        traceback.print_exc()
        return Response(
            {
                "error": str(e)
            },
            status=500
        )


# ──────────────────────────────────────────────────────────────────────────────
# Admissions List / Create  →  GET/POST /admission/
# ──────────────────────────────────────────────────────────────────────────────

@api_view(['GET', 'POST'])
@permission_classes([HasRoleAndDataPermission])
@csrf_exempt
def admission_view(request):

    # ── GET ─────────────────────────────────────────────────────────────────
    if request.method == 'GET':
        try:
            # ── Date filters (from frontend filter bar) ────────────────────
            from_date_str = request.GET.get('from_date', '').strip()
            to_date_str   = request.GET.get('to_date',   '').strip()
            status_filter = request.GET.get('status', '').strip()   # 'Admitted' | 'Discharged' | ''
            doctor_filter = request.GET.get('admitting_doctor', '').strip()

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

            # ── Bulk-fetch patients for name/contact enrichment ────────────
            # Collect all UHIDs from admissions first
            all_admissions = list(Admission.objects.all())

            uhids = list({adm.uhid for adm in all_admissions if adm.uhid})
            patient_map = {p.uhid: p for p in Patient.objects.filter(uhid__in=uhids)}

            # Insurance lookup cache
            insurance_cache = {}

            def get_insurance_name(company_code):
                if not company_code:
                    return ''
                if company_code not in insurance_cache:
                    try:
                        prov = InsuranceProvider.objects.get(company_code=company_code)
                        insurance_cache[company_code] = prov.company_name
                    except InsuranceProvider.DoesNotExist:
                        insurance_cache[company_code] = company_code
                return insurance_cache[company_code]

            data = []

            for adm in all_admissions:

                # ── Status filter ──────────────────────────────────────────
                if status_filter == 'Admitted':
                    if not (adm.is_admitted and not adm.is_discharged):
                        continue
                elif status_filter == 'Discharged':
                    if not adm.is_discharged:
                        continue
                # If status_filter is empty / 'All' → include all records

                # ── Date filter on admissionDateTime ───────────────────────
                if from_date or to_date:
                    adm_date = None
                    if adm.admissionDateTime:
                        try:
                            adm_date = adm.admissionDateTime.date()
                        except Exception:
                            pass
                    if adm_date:
                        if from_date and adm_date < from_date:
                            continue
                        if to_date and adm_date > to_date:
                            continue
                    else:
                        # No datetime — skip when date filter is active
                        continue

                # ── Doctor filter ──────────────────────────────────────────
                if doctor_filter and doctor_filter.lower() not in (adm.admittingDoctor or '').lower():
                    continue

                # ── Room from room_details (most-recent active room) ───────
                room_details = adm.room_details if isinstance(adm.room_details, list) else []
                # Try to get the currently active room; fall back to last entry
                current_room = next(
                    (r for r in reversed(room_details) if isinstance(r, dict) and r.get('is_roomActive')),
                    room_details[0] if room_details else {}
                )

                # ── Patient enrichment ─────────────────────────────────────
                pt = patient_map.get(adm.uhid)
                salutation  = (pt.salutation  or '') if pt else ''
                first_name  = (pt.firstName   or '') if pt else ''
                last_name   = (pt.lastName    or '') if pt else ''
                age         = pt.age               if pt else None
                gender      = (pt.gender      or '') if pt else ''
                mobile      = (pt.mobilePhone or '') if pt else ''
                address     = (pt.permanent_address or '') if pt else ''
                area        = (pt.area        or '') if pt else ''
                zipcode     = (pt.zipcode     or '') if pt else ''
                city        = (pt.city        or '') if pt else ''
                state       = (pt.state       or '') if pt else ''
                customer_type = (pt.customer_type or '') if pt else ''
                company_code  = (pt.company_code  or '') if pt else ''
                insurance_name = get_insurance_name(company_code) if pt else ''

                data.append({
                    # Core admission fields
                    "id":                  str(adm.pk),
                    "uhid":                adm.uhid or '',
                    "ipNumber":            adm.ipNumber or '',
                    "admissionDateTime":   adm.admissionDateTime.isoformat() if adm.admissionDateTime else None,
                    "admittingDoctor":     adm.admittingDoctor or '',
                    "consultingDoctor":    adm.consultingDoctor or '',
                    "packageName":         adm.packageName or '',
                    "roomNo":              current_room.get("roomNo", ''),
                    "bedNo":               current_room.get("bedNo", ''),
                    "reasonForAdmission":  adm.reasonForAdmission or '',
                    "mlc_type":            adm.mlc_type or '',
                    "mlc_remarks":         adm.mlc_remarks or '',
                    "advance_payments":    adm.advance_payments if isinstance(adm.advance_payments, list) else [],
                    "is_advanceActive":    bool(adm.is_advanceActive),
                    "is_admissionActive":  bool(adm.is_admissionActive),
                    "is_discharged":       bool(adm.is_discharged),
                    "is_admitted":         bool(adm.is_admitted),
                    # Patient details (enriched)
                    "salutation":          salutation,
                    "firstName":           first_name,
                    "lastName":            last_name,
                    "age":                 age,
                    "gender":              gender,
                    "mobilePhone":         mobile,
                    "permanent_address":   address,
                    "area":                area,
                    "zipcode":             zipcode,
                    "city":                city,
                    "state":               state,
                    "customerType":        customer_type,
                    "insuranceCompanyName": insurance_name,
                    "company_code":        company_code,
                    "ipserial_number":     adm.ipserial_number,
                })

            return JsonResponse({"success": True, "data": data}, safe=False)

        except Exception as e:
            traceback.print_exc()
            return JsonResponse({"error": str(e)}, status=500)

    # ── POST ─────────────────────────────────────────────────────────────────
    elif request.method == 'POST':
        try:
            data = {k: request.data.get(k) for k in request.data}

            uhid = str(data.get('uhid', '')).strip()
            if not uhid:
                return JsonResponse({"error": "UHID is required"}, status=400)

            # Check existing active admission
            existing = None
            for adm in Admission.objects.filter(uhid=uhid):
                if adm.is_admitted and not adm.is_discharged:
                    existing = adm
                    break

            if existing:
                return JsonResponse({
                    "error": f"Patient already has active admission. IP: {existing.ipNumber}",
                    "ipNumber": existing.ipNumber
                }, status=400)

            admission_dt = parse_datetime(str(data.get('admissionDateTime') or '')) or timezone.now()

            # Safe IP number generation
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
                    except Exception:
                        continue
            ip_number = f"{prefix}/{max_num + 1:06d}"

            room_details = [{
                "roomNo":        str(data.get("roomNo") or ""),
                "bedNo":         str(data.get("bedNo") or ""),
                "is_roomActive": True,
                "is_roomCleaned": False,
            }]

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
                is_admitted=True,
            )

            return JsonResponse({
                "success": True,
                "message": "Admission created successfully",
                "data": {
                    "id":       str(adm.pk),
                    "uhid":     adm.uhid,
                    "ipNumber": adm.ipNumber,
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
def admission_detail(request, ipNumber):

    try:
        # ─────────────────────────────────────────────
        # GET ADMISSION (SAFE)
        # ─────────────────────────────────────────────
        adm = None
        try:
            adm = Admission.objects.get(pk=ipNumber)
        except Admission.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Admission not found'}, status=404)

        # Avoid inactive admission
        if not adm.is_admitted:
            return JsonResponse({'success': False, 'error': 'Admission inactive'}, status=404)

        employee_id = request.headers.get('auth-user-id', 'system')

        # ─────────────────────────────────────────────
        # SAFE JSON CLEAN
        # ─────────────────────────────────────────────
        def safe_list(val):
            return val if isinstance(val, list) else []

        def clean_room_details(details):
            details = safe_list(details)
            clean = []

            for item in details:
                if isinstance(item, dict):
                    clean.append({
                        "roomNo": str(item.get("roomNo", "")),
                        "bedNo": str(item.get("bedNo", "")),
                        "is_roomActive": bool(item.get("is_roomActive", False)),
                        "is_roomCleaned": bool(item.get("is_roomCleaned", False)),
                    })
            return clean

        # ─────────────────────────────────────────────
        # PATIENT BLOCK
        # ─────────────────────────────────────────────
        def _patient_block(uhid):
            try:
                pt = Patient.objects.get(uhid=uhid)

                ins_name = ''
                if pt.company_code:
                    try:
                        prov = InsuranceProvider.objects.get(company_code=pt.company_code)
                        ins_name = prov.company_name
                    except:
                        ins_name = pt.company_code or ''

                return {
                    'salutation': pt.salutation or '',
                    'firstName': pt.firstName or '',
                    'lastName': pt.lastName or '',
                    'age': pt.age,
                    'gender': pt.gender or '',
                    'mobilePhone': pt.mobilePhone or '',
                    'city': pt.city or '',
                    'state': pt.state or '',
                    'insuranceCompanyName': ins_name,
                }
            except:
                return {}

        # ─────────────────────────────────────────────
        # BUILD RESPONSE
        # ─────────────────────────────────────────────
        def _build_result(adm):

            room_details = clean_room_details(adm.room_details)

            current_room = {}
            for r in reversed(room_details):
                if r.get("is_roomActive"):
                    current_room = r
                    break

            return {
                'ipNumber': adm.ipNumber,
                'uhid': adm.uhid,
                'admissionDateTime': adm.admissionDateTime.isoformat() if adm.admissionDateTime else None,
                'admittingDoctor': adm.admittingDoctor or '',
                'consultingDoctor': adm.consultingDoctor or '',
                'roomNo': current_room.get("roomNo", ""),
                'bedNo': current_room.get("bedNo", ""),
                'reasonForAdmission': adm.reasonForAdmission or '',
                'mlc_type': adm.mlc_type or '',
                'mlc_remarks': adm.mlc_remarks or '',
                'advance_payments': safe_list(adm.advance_payments),
                'is_admitted': adm.is_admitted,
                'is_discharged': adm.is_discharged,
                'ipserial_number': adm.ipserial_number,
                **_patient_block(adm.uhid),
            }

        # ─────────────────────────────────────────────
        # GET
        # ─────────────────────────────────────────────
        if request.method == 'GET':
            return JsonResponse({"success": True, "data": _build_result(adm)})

        # ─────────────────────────────────────────────
        # PUT
        # ─────────────────────────────────────────────
        elif request.method == 'PUT':

            data = request.data

            def get_val(v):
                return v[0] if isinstance(v, list) else v

            # SIMPLE FIELDS
            fields = [
                'admittingDoctor',
                'consultingDoctor',
                'packageName',
                'reasonForAdmission',
                'mlc_type',
                'mlc_remarks'
            ]

            for f in fields:
                if f in data:
                    val = get_val(data.get(f))
                    setattr(adm, f, str(val) if val else "")

            # ROOM UPDATE
            new_room = str(get_val(data.get("roomNo", "")) or "")
            new_bed  = str(get_val(data.get("bedNo", "")) or "")

            if new_room or new_bed:

                cleaned = clean_room_details(adm.room_details)

                # if already exists, update the latest/current room entry
                if cleaned:

                    current_room = None

                    # find active room first
                    for room in reversed(cleaned):
                        if room.get("is_roomActive"):
                            current_room = room
                            break

                    # if no active room, use last item
                    if not current_room:
                        current_room = cleaned[-1]

                    current_room["roomNo"] = new_room
                    current_room["bedNo"] = new_bed
                    current_room["is_roomActive"] = True

                    # preserve existing cleaned status if present
                    current_room["is_roomCleaned"] = bool(
                        current_room.get("is_roomCleaned", False)
                    )

                else:
                    # first room entry if array empty
                    cleaned = [{
                        "roomNo": new_room,
                        "bedNo": new_bed,
                        "is_roomActive": True,
                        "is_roomCleaned": False,
                    }]

                adm.room_details = cleaned

            # FILE
            if 'mlc_doc' in request.FILES:
                adm.mlc_doc = str(request.FILES['mlc_doc'].name)

            # NORMALIZE JSON
            adm.room_details = safe_list(adm.room_details)
            adm.roomShitingDetails = safe_list(adm.roomShitingDetails)
            adm.advance_payments = safe_list(adm.advance_payments)

            # AUDIT
            if hasattr(adm, 'lastmodified_by'):
                adm.lastmodified_by = str(employee_id)

            # SAVE (IMPORTANT)
            adm.save()

            return JsonResponse({
                "success": True,
                "message": "Updated successfully",
                "data": _build_result(adm)
            })

        # ─────────────────────────────────────────────
        # DELETE (SOFT DELETE SAFE)
        # ─────────────────────────────────────────────
        elif request.method == 'DELETE':

            data = request.data

            adm.is_admissionActive = False
            adm.is_admitted = False

            # ─────────────────────────────────────────────
            # Update room_details when admission cancelled
            # ─────────────────────────────────────────────
            cleaned_rooms = []

            if isinstance(adm.room_details, list):
                for room in adm.room_details:
                    if isinstance(room, dict):
                        cleaned_rooms.append({
                            "roomNo": str(room.get("roomNo", "")),
                            "bedNo": str(room.get("bedNo", "")),
                            "is_roomActive": False,   # deactivate room
                            "is_roomCleaned": True    # mark cleaned
                        })

            adm.room_details = cleaned_rooms

            # ─────────────────────────────────────────────
            # Audit / cancellation details
            # ─────────────────────────────────────────────
            if hasattr(adm, 'cancelled_by'):
                adm.cancelled_by = employee_id

            if hasattr(adm, 'cancellation_reason'):
                adm.cancellation_reason = data.get("cancellationReason", "")

            if hasattr(adm, 'lastmodified_by'):
                adm.lastmodified_by = employee_id

            # Safe normalize for Djongo
            adm.room_details = adm.room_details if isinstance(adm.room_details, list) else []
            adm.roomShitingDetails = adm.roomShitingDetails if isinstance(adm.roomShitingDetails, list) else []
            adm.advance_payments = adm.advance_payments if isinstance(adm.advance_payments, list) else []

            adm.save()

            return JsonResponse({
                "success": True,
                "message": "Admission cancelled successfully"
            })
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
            adm = Admission.objects.get(ipNumber=ip_number, is_admitted=True)
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

        now_dt  = datetime.now()
        prefix  = f"{str(now_dt.year)[2:]}{now_dt.month:02d}"
        max_seq = 0
        for a in Admission.objects.all():
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

        room_details = adm.room_details if isinstance(adm.room_details, list) else []
        current_room = next((r for r in reversed(room_details) if isinstance(r, dict) and r.get('is_roomActive')), {})
        room_no = current_room.get('roomNo', '')

        return JsonResponse({
            'success': True,
            'message': 'Advance added!',
            'data': {
                'id':             str(adm.pk),
                'uhid':           adm.uhid,
                'ipNumber':       adm.ipNumber,
                'total_advance':  float(adm.total_advance or 0),
                'advance_payments': adm.advance_payments or [],
                'is_advanceActive': adm.is_advanceActive,
                'roomNo':         room_no,
                'bedNo':          current_room.get('bedNo', ''),
            },
            'bill': {
                'bill_number':   bill_number,
                'ip_number':     adm.ipNumber,
                'uhid':          adm.uhid,
                'room_no':       room_no,
                'bill_date':     paid_date.strftime('%d/%m/%Y:%H:%M:%S'),
                'amount':        float(amount),
                'payment_mode':  payment_mode,
                'remarks':       remarks,
                'type':          adv_type,
                'total_advance': float(adm.total_advance or 0),
            }
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
            adm = Admission.objects.get(ipNumber=ip_number, is_admitted=True)
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

        return JsonResponse({'success': True, 'message': 'Finance updated!', 'data': {
            'id':              str(adm.pk),
            'uhid':            adm.uhid,
            'ipNumber':        adm.ipNumber,
            'advance':         float(adm.advance) if adm.advance is not None else None,
            'ip_advance':      float(adm.ip_advance) if adm.ip_advance is not None else None,
            'total_advance':   float(adm.total_advance) if adm.total_advance is not None else None,
            'creditLimit':     float(adm.creditLimit) if adm.creditLimit is not None else None,
            'advance_payments': adm.advance_payments or [],
        }})

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
        to_date_str   = request.GET.get('to_date',   '').strip()
        uhid_filter   = request.GET.get('uhid',       '').strip()
        ip_filter     = request.GET.get('ip_number',  '').strip()

        qs = Admission.objects.filter(is_admitted=True)
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
    
