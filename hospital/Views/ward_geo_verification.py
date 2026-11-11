import json
import base64
import os
import re
from datetime import datetime
from bson import ObjectId
import gridfs
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from django.http import HttpResponse, Http404

from hospital.Views.dbcollection import hms_db

def _now():
    return datetime.utcnow()

def _get_gridfs():
    return gridfs.GridFS(hms_db)


def _generate_thumbnail(image_bytes, max_size=(320, 240)):
    """Creates a compressed lightweight base64 thumbnail from image bytes."""
    if not image_bytes:
        return ""
    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(image_bytes))
        img.thumbnail(max_size, Image.Resampling.LANCZOS)
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=75, optimize=True)
        encoded = base64.b64encode(buf.getvalue()).decode('utf-8')
        return f"data:image/jpeg;base64,{encoded}"
    except Exception as e:
        print("Thumbnail generation error:", e)
        return ""

@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def ward_geo_verification_view(request):
    """
    POST: Save new geo-tagged bedside verification record for an IP patient.
          Accepts JSON or multipart/form-data:
          - ip_number (required)
          - uhid
          - patient_name
          - room_no
          - bed_no
          - doctor_name
          - latitude (float)
          - longitude (float)
          - accuracy (float)
          - location_address (string)
          - image (base64 data URL string or uploaded file)
          - notes (optional)

    GET: Retrieve geo verification records.
         Query params:
         - ?ip_number=... (filter by IP number)
         - ?uhid=...
    """
    collection = hms_db['hospital_ward_geo_verification']
    fs = _get_gridfs()

    if request.method == 'GET':
        query = {}
        ip_number = request.GET.get('ip_number') or request.GET.get('ip_no') or request.GET.get('ip')
        if ip_number:
            query['ip_number'] = str(ip_number).strip()

        uhid = request.GET.get('uhid')
        if uhid:
            query['uhid'] = str(uhid).strip()

        cursor = collection.find(query).sort('created_date', -1)
        records = []
        for doc in cursor:
            d = dict(doc)
            d['_id'] = str(d['_id'])
            if 'image_file_id' in d and d['image_file_id']:
                d['image_file_id'] = str(d['image_file_id'])
                d['photo_url'] = f"/_b_a_c_k_e_n_d/HMS/ward-geo-verification/photo/{d['image_file_id']}/"
            if isinstance(d.get('created_date'), datetime):
                d['created_date'] = d['created_date'].isoformat()
            records.append(d)

        return Response({
            "success": True,
            "count": len(records),
            "data": records
        }, status=status.HTTP_200_OK)

    elif request.method == 'POST':
        data = request.data or {}
        ip_number = str(data.get('ip_number') or data.get('ip_no') or data.get('ip') or '').strip()
        if not ip_number:
            return Response({"success": False, "error": "IP Number (ip_number) is required"}, status=status.HTTP_400_BAD_REQUEST)

        uhid = str(data.get('uhid') or '').strip()
        patient_name = str(data.get('patient_name') or data.get('name') or '').strip()
        room_no = str(data.get('room_no') or '').strip()
        bed_no = str(data.get('bed_no') or '').strip()
        doctor_name = str(data.get('doctor_name') or '').strip()
        location_address = str(data.get('location_address') or '').strip()
        notes = str(data.get('notes') or '').strip()

        try:
            latitude = float(data.get('latitude')) if data.get('latitude') is not None else None
            longitude = float(data.get('longitude')) if data.get('longitude') is not None else None
        except (ValueError, TypeError):
            latitude, longitude = None, None

        try:
            accuracy = float(data.get('accuracy')) if data.get('accuracy') is not None else None
        except (ValueError, TypeError):
            accuracy = None

        # Image processing: can be file upload in request.FILES or base64 string
        image_file_id = None
        thumbnail_base64 = ""
        image_file = request.FILES.get('image') or request.FILES.get('photo')

        if image_file:
            safe_ip = re.sub(r'[^a-zA-Z0-9_\-]', '_', ip_number)
            filename = f"geotag_{safe_ip}_{int(datetime.utcnow().timestamp())}.jpg"
            image_bytes = image_file.read()
            image_file_id = fs.put(image_bytes, filename=filename, content_type='image/jpeg')
            thumbnail_base64 = _generate_thumbnail(image_bytes)
        else:
            base64_str = data.get('image') or data.get('photo') or data.get('image_base64') or ''
            if base64_str and ',' in base64_str:
                header, encoded = base64_str.split(',', 1)
                try:
                    image_bytes = base64.b64decode(encoded)
                    safe_ip = re.sub(r'[^a-zA-Z0-9_\-]', '_', ip_number)
                    filename = f"geotag_{safe_ip}_{int(datetime.utcnow().timestamp())}.jpg"
                    image_file_id = fs.put(image_bytes, filename=filename, content_type='image/jpeg')
                    thumbnail_base64 = _generate_thumbnail(image_bytes)
                except Exception as e:
                    print("Error decoding base64 image:", e)

        current_user = request.headers.get('auth-user-id') or data.get('created_by') or 'system'
        outlet_code = request.headers.get('outlet-code') or data.get('outlet_code') or 'OLET003'
        branch_code = request.headers.get('branch-code') or data.get('branch_code') or 'SHB001'
        hospital_code = request.headers.get('hospital-code') or data.get('hospital_code') or 'SH001'
        now = _now()

        doc = {
            'ip_number': ip_number,
            'uhid': uhid,
            'patient_name': patient_name,
            'room_no': room_no,
            'bed_no': bed_no,
            'doctor_name': doctor_name,
            'latitude': latitude,
            'longitude': longitude,
            'accuracy': accuracy,
            'location_address': location_address,
            'image_file_id': image_file_id,
            'thumbnail_base64': thumbnail_base64,
            'notes': notes,
            'created_by': current_user,
            'outlet_code': outlet_code,
            'branch_code': branch_code,
            'hospital_code': hospital_code,
            'created_date': now
        }

        insert_res = collection.insert_one(doc)
        doc['_id'] = str(insert_res.inserted_id)
        if image_file_id:
            doc['image_file_id'] = str(image_file_id)
            doc['photo_url'] = f"/_b_a_c_k_e_n_d/HMS/ward-geo-verification/photo/{doc['image_file_id']}/"
        doc['created_date'] = now.isoformat()

        return Response({
            "success": True,
            "message": "Geo-tagged bedside verification recorded successfully",
            "data": doc
        }, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([AllowAny])
def stream_geo_photo(request, file_id):
    """
    Streams the geo verification image from GridFS.
    """
    fs = _get_gridfs()
    try:
        oid = ObjectId(file_id)
        grid_out = fs.get(oid)
        response = HttpResponse(grid_out.read(), content_type=grid_out.content_type or 'image/jpeg')
        response['Content-Disposition'] = f'inline; filename="{grid_out.filename}"'
        response['Cache-Control'] = 'public, max-age=86400'
        return response
    except Exception:
        raise Http404("Photo not found")
