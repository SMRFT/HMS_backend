file_path = r'd:\Parthi\HMS\HMS_backend\hospital\views.py'

with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

target = '''            data.append({
                "uhid": p.uhid,
                "patientName": full_name,
                "age": p.age,
                "gender": p.gender,
                "mobile": p.mobilePhone,
                "doctor": bill.doctor_id, 
                "doctorName": resolved_doc_name,
                "spouseName": p.spouse_name or '',
                "address": full_address,
                "visitType": visit_type,'''

replacement = '''            g_type = getattr(p, 'guardian_type', None) or ('D/o' if (p.gender and str(p.gender).upper().startswith('F')) else 'S/o')
            g_name = getattr(p, 'guardian_name', None) or getattr(p, 'spouse_name', '') or ''
            perm_addr = getattr(p, 'permanent_address', '') or ''
            area_val = getattr(p, 'area', '') or ''
            city_val = getattr(p, 'city', '') or ''
            dist_val = getattr(p, 'district', '') or ''

            data.append({
                "uhid": p.uhid,
                "patientName": full_name,
                "age": p.age,
                "gender": p.gender,
                "mobile": p.mobilePhone,
                "doctor": bill.doctor_id, 
                "doctorName": resolved_doc_name,
                "spouseName": p.spouse_name or '',
                "guardianType": g_type,
                "guardianName": g_name,
                "permanentAddress": perm_addr,
                "area": area_val,
                "city": city_val,
                "district": dist_val,
                "address": full_address,
                "visitType": visit_type,'''

if target in content:
    content = content.replace(target, replacement)
    print("SUCCESS: Target replaced in views.py")
else:
    content = content.replace(target.replace('\n', '\r\n'), replacement.replace('\n', '\r\n'))
    print("SUCCESS (CRLF): Target replaced in views.py")

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
print("SUCCESS: Written views.py")

