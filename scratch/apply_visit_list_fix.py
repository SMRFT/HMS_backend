import re

with open('d:/Parthi/HMS/HMS_backend/hospital/views.py', 'r', encoding='utf-8') as f:
    content = f.read()

start_marker = "@api_view(['GET'])\n@csrf_exempt\n@permission_classes([HasRoleAndDataPermission])\ndef patient_visit_list(request):"
if start_marker not in content:
    # Try CRLF
    start_marker = start_marker.replace('\n', '\r\n')

end_marker = "# QR Registration Views"

new_function = '''@api_view(['GET'])
@csrf_exempt
@permission_classes([HasRoleAndDataPermission])
def patient_visit_list(request):
    client = None
    try:
        from_date_str = request.GET.get('fromDate')
        to_date_str = request.GET.get('toDate')
        doctor_id = request.GET.get('doctorId')

        today = timezone.localdate()

        if from_date_str:
            from_date = datetime.strptime(from_date_str, '%Y-%m-%d').date()
        else:
            from_date = today

        if to_date_str:
            to_date = datetime.strptime(to_date_str, '%Y-%m-%d').date()
        else:
            to_date = today

        start_naive = datetime.combine(from_date, time.min)
        end_naive = datetime.combine(to_date, time.max)

        if timezone.is_naive(start_naive):
            start_dt = timezone.make_aware(start_naive)
        else:
            start_dt = start_naive

        if timezone.is_naive(end_naive):
            end_dt = timezone.make_aware(end_naive)
        else:
            end_dt = end_naive

        mongo_host = os.getenv("GLOBAL_DB_HOST")
        if not mongo_host:
            return Response({"error": "Database configuration missing"}, status=500)

        client = MongoClient(mongo_host, serverSelectionTimeoutMS=5000)
        hms_db = client['HMS']
        global_db = client['Global']

        billing_coll = hms_db['hospital_billing']
        patient_coll = hms_db['hospital_patient']
        refund_coll = hms_db['hospital_refund']
        diag_coll = global_db['backend_diagnostics_profile']

        bill_query = {'billed_date': {'$gte': start_dt, '$lte': end_dt}}
        if doctor_id:
            d_str = str(doctor_id).strip()
            if d_str.isdigit():
                bill_query['doctor_id'] = {'$in': [d_str, int(d_str)]}
            else:
                bill_query['doctor_id'] = d_str

        bills = list(billing_coll.find(bill_query).sort('billed_date', -1))

        all_emp_ids = set()
        bill_numbers = []
        patient_ids = []
        uhids = []

        for b in bills:
            pid = b.get('patient_id')
            if pid is not None:
                if isinstance(pid, int):
                    patient_ids.append(pid)
                elif isinstance(pid, str) and pid.isdigit():
                    patient_ids.append(int(pid))
            uh = b.get('uhid')
            if uh:
                uhids.append(str(uh).strip())

            if b.get('bill_number'):
                bill_numbers.append(b['bill_number'])
            if b.get('doctor_id'):
                all_emp_ids.add(str(b['doctor_id']).strip())
            if b.get('created_by'):
                all_emp_ids.add(str(b['created_by']).strip())
            for h in (b.get('edit_history') or []):
                if h.get('user'):
                    all_emp_ids.add(str(h.get('user')).strip())
                changes = h.get('changes', {})
                if 'doctor' in changes and isinstance(changes['doctor'], dict):
                    old_d = changes['doctor'].get('old')
                    new_d = changes['doctor'].get('new')
                    if old_d: all_emp_ids.add(str(old_d).strip())
                    if new_d: all_emp_ids.add(str(new_d).strip())

        # Batch fetch patients in chunks of 100 to maximize index performance
        patient_map = {}
        pids_list = list(set(patient_ids))
        uhs_list = list(set(uhids))

        for i in range(0, len(pids_list), 100):
            chunk = pids_list[i:i+100]
            for p in patient_coll.find({'id': {'$in': chunk}}):
                if p.get('id') is not None:
                    patient_map[p['id']] = p
                    patient_map[str(p['id'])] = p
                if p.get('uhid'):
                    patient_map[str(p['uhid']).strip()] = p

        missing_uhs = [u for u in uhs_list if u not in patient_map]
        for i in range(0, len(missing_uhs), 100):
            chunk = missing_uhs[i:i+100]
            for p in patient_coll.find({'uhid': {'$in': chunk}}):
                if p.get('id') is not None:
                    patient_map[p['id']] = p
                    patient_map[str(p['id'])] = p
                if p.get('uhid'):
                    patient_map[str(p['uhid']).strip()] = p

        # Batch fetch employee names
        emp_map = {}
        if all_emp_ids:
            try:
                for doc in diag_coll.find({"employeeId": {"$in": list(all_emp_ids)}}, {"employeeId": 1, "employeeName": 1}):
                    if doc.get("employeeId") and doc.get("employeeName"):
                        emp_map[str(doc.get("employeeId")).strip()] = doc.get("employeeName")
            except Exception as ex:
                print(f"Error fetching emp map: {ex}")

        # Batch fetch refunds
        refunds_by_bill = {}
        if bill_numbers:
            try:
                for r in refund_coll.find({'bill_no': {'$in': bill_numbers}}):
                    bno = r.get('bill_no')
                    if bno:
                        refunds_by_bill.setdefault(bno, []).append(r)
            except Exception as ref_err:
                print(f"Error batch fetching refunds: {ref_err}")

        data = []
        for bill in bills:
            p = None
            if bill.get('patient_id') is not None:
                p = patient_map.get(bill.get('patient_id')) or patient_map.get(str(bill.get('patient_id')))
            if not p and bill.get('uhid'):
                p = patient_map.get(str(bill.get('uhid')).strip())

            if not p:
                continue

            p_created = p.get('created_date')
            if p_created and hasattr(p_created, 'tzinfo') and timezone.is_naive(p_created):
                p_created = timezone.make_aware(p_created)
            elif p_created and isinstance(p_created, str):
                try:
                    p_created = datetime.fromisoformat(p_created)
                    if timezone.is_naive(p_created):
                        p_created = timezone.make_aware(p_created)
                except Exception:
                    pass

            if p_created and start_dt:
                visit_type = "New" if p_created >= start_dt else "Review"
            else:
                visit_type = "Review"

            full_name = f"{p.get('salutation') or ''} {p.get('firstName') or ''} {p.get('lastName') or ''}".strip()
            doc_id_val = str(bill.get('doctor_id') or '').strip()
            resolved_doc_name = emp_map.get(doc_id_val) or p.get('doctorName') or bill.get('doctor_id')

            address_parts = [
                p.get('permanent_address'),
                p.get('area'),
                p.get('city'),
                p.get('district'),
                p.get('state'),
                p.get('zipcode')
            ]
            full_address = ", ".join([str(val) for val in address_parts if val]).strip()

            refunds = refunds_by_bill.get(bill.get('bill_number'), [])
            refund_data = []
            total_refunded = 0
            for r in refunds:
                amt = r.get('refund_amount', 0)
                if hasattr(amt, 'to_decimal'):
                    amt = amt.to_decimal()
                try:
                    total_refunded += float(amt)
                except Exception:
                    pass

                ref_dt_str = ''
                ref_dt = r.get('refund_date')
                if ref_dt:
                    if hasattr(ref_dt, 'tzinfo') and timezone.is_naive(ref_dt):
                        ref_dt = timezone.make_aware(ref_dt)
                    ref_dt_str = timezone.localtime(ref_dt).strftime("%d-%m-%Y %I:%M %p")

                refund_data.append({
                    "refund_bill_no": r.get('refund_bill_no'),
                    "amount": str(r.get('refund_amount', 0)),
                    "status": r.get('status'),
                    "reason": r.get('remarks') or '',
                    "date": ref_dt_str
                })

            formatted_history = []
            for h in (bill.get('edit_history') or []):
                raw_user = str(h.get('user', '')).strip()
                resolved_user = emp_map.get(raw_user, raw_user)

                changes = h.get('changes', {})
                formatted_changes = {}
                if isinstance(changes, dict):
                    for f_key, f_val in changes.items():
                        if f_key == 'doctor' and isinstance(f_val, dict):
                            old_id = str(f_val.get('old', '')).strip()
                            new_id = str(f_val.get('new', '')).strip()
                            formatted_changes['doctor'] = {
                                'old': emp_map.get(old_id, old_id),
                                'new': emp_map.get(new_id, new_id)
                            }
                        else:
                            formatted_changes[f_key] = f_val

                h_date = h.get('date')
                if isinstance(h_date, datetime):
                    if timezone.is_naive(h_date):
                        h_date = timezone.make_aware(h_date)
                    h_date = timezone.localtime(h_date).strftime("%d-%m-%Y %I:%M %p")

                reason_val = h.get('reason', '') or ''
                if not reason_val and isinstance(h.get('changes'), dict):
                    reason_val = h.get('changes', {}).get('refund', {}).get('reason', '')

                formatted_history.append({
                    'date': h_date,
                    'user': resolved_user,
                    'reason': reason_val,
                    'changes': formatted_changes
                })

            gender_val = str(p.get('gender') or '')
            g_type = p.get('guardian_type')
            if not g_type or (gender_val.upper().startswith('M') and g_type == 'W/o'):
                g_type = 'S/o'
            elif not g_type:
                g_type = 'D/o' if gender_val.upper().startswith('F') else 'S/o'
            g_name = p.get('guardian_name') or p.get('spouse_name') or ''
            perm_addr = p.get('permanent_address') or ''
            area_val = p.get('area') or ''
            city_val = p.get('city') or ''
            dist_val = p.get('district') or ''

            billed_dt_str = ''
            b_dt = bill.get('billed_date')
            if b_dt:
                if hasattr(b_dt, 'tzinfo') and timezone.is_naive(b_dt):
                    b_dt = timezone.make_aware(b_dt)
                billed_dt_str = timezone.localtime(b_dt).strftime("%d-%m-%Y %I:%M %p")

            data.append({
                "uhid": p.get('uhid'),
                "patientName": full_name,
                "age": p.get('age'),
                "gender": p.get('gender'),
                "mobile": p.get('mobilePhone'),
                "doctor": bill.get('doctor_id'),
                "doctorName": resolved_doc_name,
                "spouseName": p.get('spouse_name') or '',
                "guardianType": g_type,
                "guardianName": g_name,
                "permanentAddress": perm_addr,
                "area": area_val,
                "city": city_val,
                "district": dist_val,
                "address": full_address,
                "visitType": visit_type,
                "billNumber": bill.get('bill_number'),
                "registrationFee": str(bill.get('registration_fee') or 0),
                "consultingFee": str(bill.get('consulting_fee') or 0),
                "billAmount": str(bill.get('total_fees') or 0),
                "paymentStatus": bill.get('payment_status'),
                "paymentMethod": bill.get('payment_method') or 'Cash',
                "date": billed_dt_str,
                "created_by": str(bill.get('created_by') or ''),
                "preparedBy": emp_map.get(str(bill.get('created_by') or '').strip()) or str(bill.get('created_by') or 'Staff'),
                "editHistory": formatted_history,
                "refunds": refund_data,
                "totalRefunded": str(total_refunded)
            })

        return Response(data)

    except Exception as e:
        print(f"Error in visit list: {e}")
        return Response({"error": str(e)}, status=500)
    finally:
        if client:
            client.close()

'''

start_idx = content.find(start_marker)
end_idx = content.find(end_marker)

print(f"start_idx: {start_idx}, end_idx: {end_idx}")

if start_idx != -1 and end_idx != -1:
    content = content[:start_idx] + new_function + "\n\n" + content[end_idx:]
    with open('d:/Parthi/HMS/HMS_backend/hospital/views.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print("Successfully replaced patient_visit_list in hospital/views.py!")
else:
    print("Could not find markers!")
