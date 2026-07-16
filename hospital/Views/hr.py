import os
import json
import datetime
from decimal import Decimal
from django.http import JsonResponse
from django.utils.dateparse import parse_date
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from rest_framework.decorators import permission_classes
from bson import Decimal128

from django.utils import timezone
from django.db.models import Q
from ..models import Internship, InternshipCertificateTemplate, CommunicationLog
from pyauth.auth import HasRoleAndDataPermission

def clean_smart_quotes(v):
    if v is None:
        return 0.0
    if isinstance(v, Decimal128):
        try:
            return float(v.to_decimal())
        except Exception:
            return 0.0
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        cleaned = (
            v.replace("\u201c", "")
             .replace("\u201d", "")
             .replace("\u2018", "")
             .replace("\u2019", "")
             .replace('"',      "")
             .replace("'",      "")
             .strip()
        )
        if not cleaned:
            return 0.0
        try:
            return float(cleaned)
        except (ValueError, TypeError):
            return 0.0
    return 0.0

def get_payments_list(payment_details):
    """
    Safely retrieve a Python list of dicts from payment_details.
    Handles standard lists, raw strings, and double JSON-serialized inputs defensively.
    """
    if not payment_details:
        return []
    if isinstance(payment_details, str):
        try:
            parsed = json.loads(payment_details)
            if isinstance(parsed, str):
                parsed = json.loads(parsed)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return payment_details if isinstance(payment_details, list) else []

def normalise_internship_decimals(intern_obj):
    intern_obj.fee_per_month = clean_smart_quotes(intern_obj.fee_per_month)
    intern_obj.hostel_fee_per_month = clean_smart_quotes(intern_obj.hostel_fee_per_month)
    intern_obj.discount_amount = clean_smart_quotes(intern_obj.discount_amount)
    intern_obj.total_fee = clean_smart_quotes(intern_obj.total_fee)

@api_view(['GET', 'POST'])
@permission_classes([HasRoleAndDataPermission])
def list_or_create_internships(request):
    if request.method == 'GET':
        try:
            branch_code = request.GET.get('auth-branch-code') or request.data.get('auth-branch-code') or 'system'
            hospital_code = request.GET.get('auth-hospital-code') or request.data.get('auth-hospital-code') or 'system'
            
            internships = Internship.objects.filter(is_active__in=[True])
            if hospital_code and hospital_code != 'system':
                internships = internships.filter(Q(hospital_code=hospital_code) | Q(hospital_code__isnull=True) | Q(hospital_code="") | Q(hospital_code="system"))
            if branch_code and branch_code != 'system':
                internships = internships.filter(Q(branch_code=branch_code) | Q(branch_code__isnull=True) | Q(branch_code="") | Q(branch_code="system"))
                
            internships = internships.order_by('-created_date')
            
            search_query = request.GET.get('search', '').strip()
            if search_query:
                internships = internships.filter(student_name__icontains=search_query) | internships.filter(college__icontains=search_query)
            
            # Date filters
            from_date = request.GET.get('from_date')
            to_date = request.GET.get('to_date')
            if from_date and from_date.strip():
                internships = internships.filter(start_date__gte=parse_date(from_date))
            if to_date and to_date.strip():
                internships = internships.filter(start_date__lte=parse_date(to_date))
                
            data = []
            for item in internships:
                payments = get_payments_list(item.payment_details)
                amount_paid = sum(clean_smart_quotes(p.get('amount', 0)) for p in payments)
                total_fee = clean_smart_quotes(item.total_fee)
                pending_amount = total_fee - amount_paid
                
                # Recalculate payment status dynamically
                if amount_paid == 0:
                    payment_status = "Pending"
                elif pending_amount <= 0:
                    payment_status = "Fully Paid"
                else:
                    payment_status = "Partially Paid"
                    
                email_count = CommunicationLog.objects.filter(
                    patient_id=str(item.intern_id),
                    type="Email",
                    status="Success",
                    template_name="internship_certificate"
                ).count()
                
                whatsapp_count = CommunicationLog.objects.filter(
                    patient_id=str(item.intern_id),
                    type="WhatsApp",
                    status="Success",
                    template_name="internship_certificate"
                ).count()
                    
                data.append({
                    "intern_id": item.intern_id,
                    "student_name": item.student_name,
                    "email": item.email or "",
                    "mobile_number": item.mobile_number or "",
                    "college": item.college,
                    "department": item.department,
                    "degree": item.degree,
                    "start_date": item.start_date.strftime('%Y-%m-%d') if item.start_date else "",
                    "end_date": item.end_date.strftime('%Y-%m-%d') if item.end_date else "",
                    "duration": item.duration,
                    "is_hosteller": item.is_hosteller,
                    "fee_per_month": clean_smart_quotes(item.fee_per_month),
                    "hostel_fee_per_month": clean_smart_quotes(item.hostel_fee_per_month),
                    "total_fee": total_fee,
                    "amount_paid": amount_paid,
                    "pending_amount": pending_amount,
                    "payment_status": payment_status,
                    "payment_details": payments,
                    "discount_amount": clean_smart_quotes(item.discount_amount),
                    "discount_remarks": item.discount_remarks or "",
                    "cert_template_id": item.cert_template_id,
                    "cert_description": item.cert_description or "",
                    "approved_by": item.approved_by or "",
                    "approved_at": item.approved_at.strftime('%Y-%m-%d %H:%M:%S') if item.approved_at else "",
                    "deleted_by": item.deleted_by or "",
                    "deleted_at": item.deleted_at.strftime('%Y-%m-%d %H:%M:%S') if item.deleted_at else "",
                    "email_count": email_count,
                    "whatsapp_count": whatsapp_count
                })
            return Response({"success": True, "data": data})
        except Exception as e:
            return Response({"success": False, "error": str(e)}, status=500)
            
    elif request.method == 'POST':
        try:
            data = request.data
            student_name = data.get("student_name")
            email = data.get("email")
            mobile_number = data.get("mobile_number")
            college = data.get("college")
            department = data.get("department")
            degree = data.get("degree")
            start_date_str = data.get("start_date")
            end_date_str = data.get("end_date")
            duration = data.get("duration", "")
            is_hosteller = data.get("is_hosteller", False)
            fee_per_month = clean_smart_quotes(data.get("fee_per_month", 3500.0))
            hostel_fee_per_month = clean_smart_quotes(data.get("hostel_fee_per_month", 0.0))
            discount_amount = clean_smart_quotes(data.get("discount_amount", 0.0))
            discount_remarks = data.get("discount_remarks", "")
            total_fee = clean_smart_quotes(data.get("total_fee", 0.0))
            
            # Parse dates
            start_date = parse_date(start_date_str) if start_date_str else None
            end_date = parse_date(end_date_str) if end_date_str else None
            
            if not student_name or not college or not start_date or not end_date:
                return Response({"success": False, "error": "Student Name, College, Start Date, and End Date are required"}, status=400)
                
            # Initial payment processing
            payment_details = []
            initial_amount = data.get("initial_amount")
            initial_method = data.get("initial_method", "CASH")
            initial_date = data.get("initial_date")
            
            if initial_amount is not None and str(initial_amount).strip():
                try:
                    amt = clean_smart_quotes(initial_amount)
                    if amt > 0:
                        payment_details.append({
                            "amount": amt,
                            "method": initial_method,
                            "date": initial_date or datetime.date.today().strftime('%Y-%m-%d')
                        })
                except ValueError:
                    pass
            
            # Recalculate status
            amount_paid = sum(clean_smart_quotes(p.get("amount", 0)) for p in payment_details)
            pending_amount = total_fee - amount_paid
            if amount_paid == 0:
                payment_status = "Pending"
            elif pending_amount <= 0:
                payment_status = "Fully Paid"
            else:
                payment_status = "Partially Paid"
                
            user_id = data.get('auth-user-id', 'system')
            branch_code = data.get('auth-branch-code', 'system')
            hospital_code = data.get('auth-hospital-code', 'system')

            intern = Internship(
                student_name=student_name,
                email=email,
                mobile_number=mobile_number,
                college=college,
                department=department,
                degree=degree,
                start_date=start_date,
                end_date=end_date,
                duration=duration,
                is_hosteller=is_hosteller,
                fee_per_month=fee_per_month,
                hostel_fee_per_month=hostel_fee_per_month,
                discount_amount=discount_amount,
                discount_remarks=discount_remarks,
                total_fee=total_fee,
                payment_status=payment_status,
                payment_details=payment_details,
                is_active=True,
                created_by=user_id,
                branch_code=branch_code,
                hospital_code=hospital_code
            )
            normalise_internship_decimals(intern)
            intern.save()
            
            return Response({"success": True, "intern_id": intern.intern_id, "message": "Intern registered successfully"})
        except Exception as e:
            return Response({"success": False, "error": str(e)}, status=500)


@api_view(['GET', 'POST', 'DELETE'])
@permission_classes([HasRoleAndDataPermission])
def detail_or_update_internship(request, pk):
    try:
        branch_code = request.data.get('auth-branch-code') or request.GET.get('auth-branch-code') or 'system'
        hospital_code = request.data.get('auth-hospital-code') or request.GET.get('auth-hospital-code') or 'system'
        
        queryset = Internship.objects.filter(intern_id=pk, is_active__in=[True])
        if hospital_code and hospital_code != 'system':
            queryset = queryset.filter(Q(hospital_code=hospital_code) | Q(hospital_code__isnull=True) | Q(hospital_code="") | Q(hospital_code="system"))
        if branch_code and branch_code != 'system':
            queryset = queryset.filter(Q(branch_code=branch_code) | Q(branch_code__isnull=True) | Q(branch_code="") | Q(branch_code="system"))
            
        intern = queryset.get()
    except (Internship.DoesNotExist, ValueError):
        return Response({"success": False, "error": "Intern not found"}, status=404)
        
    if request.method == 'GET':
        try:
            payments = get_payments_list(intern.payment_details)
            amount_paid = sum(clean_smart_quotes(p.get('amount', 0)) for p in payments)
            total_fee = clean_smart_quotes(intern.total_fee)
            pending_amount = total_fee - amount_paid
            
            if amount_paid == 0:
                payment_status = "Pending"
            elif pending_amount <= 0:
                payment_status = "Fully Paid"
            else:
                payment_status = "Partially Paid"
                
            email_count = CommunicationLog.objects.filter(
                patient_id=str(intern.intern_id),
                type="Email",
                status="Success",
                template_name="internship_certificate"
            ).count()
            
            whatsapp_count = CommunicationLog.objects.filter(
                patient_id=str(intern.intern_id),
                type="WhatsApp",
                status="Success",
                template_name="internship_certificate"
            ).count()
                
            data = {
                "intern_id": intern.intern_id,
                "student_name": intern.student_name,
                "email": intern.email or "",
                "mobile_number": intern.mobile_number or "",
                "college": intern.college,
                "department": intern.department,
                "degree": intern.degree,
                "start_date": intern.start_date.strftime('%Y-%m-%d') if intern.start_date else "",
                "end_date": intern.end_date.strftime('%Y-%m-%d') if intern.end_date else "",
                "duration": intern.duration,
                "is_hosteller": intern.is_hosteller,
                "fee_per_month": clean_smart_quotes(intern.fee_per_month),
                "hostel_fee_per_month": clean_smart_quotes(intern.hostel_fee_per_month),
                "total_fee": total_fee,
                "amount_paid": amount_paid,
                "pending_amount": pending_amount,
                "payment_status": payment_status,
                "payment_details": payments,
                "discount_amount": clean_smart_quotes(intern.discount_amount),
                "discount_remarks": intern.discount_remarks or "",
                "cert_template_id": intern.cert_template_id,
                "cert_description": intern.cert_description or "",
                "approved_by": intern.approved_by or "",
                "approved_at": intern.approved_at.strftime('%Y-%m-%d %H:%M:%S') if intern.approved_at else "",
                "deleted_by": intern.deleted_by or "",
                "deleted_at": intern.deleted_at.strftime('%Y-%m-%d %H:%M:%S') if intern.deleted_at else "",
                "email_count": email_count,
                "whatsapp_count": whatsapp_count
            }
            return Response({"success": True, "data": data})
        except Exception as e:
            return Response({"success": False, "error": str(e)}, status=500)
            
    elif request.method == 'POST': # Using POST for updates to avoid CORS/PUT issues
        try:
            data = request.data
            intern.student_name = data.get("student_name", intern.student_name)
            intern.email = data.get("email", intern.email)
            intern.mobile_number = data.get("mobile_number", intern.mobile_number)
            intern.college = data.get("college", intern.college)
            intern.department = data.get("department", intern.department)
            intern.degree = data.get("degree", intern.degree)
            
            if "start_date" in data:
                intern.start_date = parse_date(data.get("start_date"))
            if "end_date" in data:
                intern.end_date = parse_date(data.get("end_date"))
                
            intern.duration = data.get("duration", intern.duration)
            intern.is_hosteller = data.get("is_hosteller", intern.is_hosteller)
            intern.fee_per_month = clean_smart_quotes(data.get("fee_per_month", intern.fee_per_month))
            intern.hostel_fee_per_month = clean_smart_quotes(data.get("hostel_fee_per_month", intern.hostel_fee_per_month))
            intern.discount_amount = clean_smart_quotes(data.get("discount_amount", intern.discount_amount))
            intern.discount_remarks = data.get("discount_remarks", intern.discount_remarks)
            intern.total_fee = clean_smart_quotes(data.get("total_fee", intern.total_fee))
            
            # Recalculate status
            payments = get_payments_list(intern.payment_details)
            amount_paid = sum(clean_smart_quotes(p.get('amount', 0)) for p in payments)
            pending_amount = clean_smart_quotes(intern.total_fee) - amount_paid
            if amount_paid == 0:
                intern.payment_status = "Pending"
            elif pending_amount <= 0:
                intern.payment_status = "Fully Paid"
            else:
                intern.payment_status = "Partially Paid"
                
            user_id = data.get('auth-user-id', 'system')
            intern.lastmodified_by = user_id
            intern.lastmodified_date = timezone.now()
            
            normalise_internship_decimals(intern)
            intern.save()
            return Response({"success": True, "message": "Intern details updated successfully"})
        except Exception as e:
            return Response({"success": False, "error": str(e)}, status=500)
            
    elif request.method == 'DELETE': # Soft Delete!
        try:
            intern.is_active = False
            user_id = request.data.get('auth-user-id') or request.GET.get('auth-user-id') or 'system'
            intern.deleted_by = user_id
            intern.deleted_at = timezone.now()
            normalise_internship_decimals(intern)
            intern.save()
            return Response({"success": True, "message": "Intern record deleted successfully"})
        except Exception as e:
            return Response({"success": False, "error": str(e)}, status=500)


@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def add_payment(request, pk):
    try:
        branch_code = request.data.get('auth-branch-code') or request.GET.get('auth-branch-code') or 'system'
        hospital_code = request.data.get('auth-hospital-code') or request.GET.get('auth-hospital-code') or 'system'
        
        queryset = Internship.objects.filter(intern_id=pk, is_active__in=[True])
        if hospital_code and hospital_code != 'system':
            queryset = queryset.filter(Q(hospital_code=hospital_code) | Q(hospital_code__isnull=True) | Q(hospital_code="") | Q(hospital_code="system"))
        if branch_code and branch_code != 'system':
            queryset = queryset.filter(Q(branch_code=branch_code) | Q(branch_code__isnull=True) | Q(branch_code="") | Q(branch_code="system"))
            
        intern = queryset.get()
        amount = request.data.get("amount")
        method = request.data.get("method", "CASH")
        date_str = request.data.get("date") or datetime.date.today().strftime('%Y-%m-%d')
        
        if amount is None or not str(amount).strip():
            return Response({"success": False, "error": "Amount is required"}, status=400)
            
        payments = get_payments_list(intern.payment_details)
        payments.append({
            "amount": clean_smart_quotes(amount),
            "method": method,
            "date": date_str
        })
        intern.payment_details = payments
        
        # Recalculate status
        amount_paid = sum(clean_smart_quotes(p.get('amount', 0)) for p in payments)
        pending_amount = clean_smart_quotes(intern.total_fee) - amount_paid
        if amount_paid == 0:
            intern.payment_status = "Pending"
        elif pending_amount <= 0:
            intern.payment_status = "Fully Paid"
        else:
            intern.payment_status = "Partially Paid"
            
        user_id = request.data.get('auth-user-id', 'system')
        intern.lastmodified_by = user_id
        intern.lastmodified_date = timezone.now()
        
        normalise_internship_decimals(intern)
        intern.save()
        return Response({"success": True, "message": "Payment recorded successfully"})
    except (Internship.DoesNotExist, ValueError):
        return Response({"success": False, "error": "Intern not found"}, status=404)
    except Exception as e:
        return Response({"success": False, "error": str(e)}, status=500)


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_internship_autocomplete(request):
    try:
        branch_code = request.data.get('auth-branch-code') or request.GET.get('auth-branch-code') or 'system'
        hospital_code = request.data.get('auth-hospital-code') or request.GET.get('auth-hospital-code') or 'system'
        
        queryset = Internship.objects.filter(is_active__in=[True])
        if hospital_code and hospital_code != 'system':
            queryset = queryset.filter(Q(hospital_code=hospital_code) | Q(hospital_code__isnull=True) | Q(hospital_code="") | Q(hospital_code="system"))
        if branch_code and branch_code != 'system':
            queryset = queryset.filter(Q(branch_code=branch_code) | Q(branch_code__isnull=True) | Q(branch_code="") | Q(branch_code="system"))
            
        colleges = list(queryset.values_list('college', flat=True).distinct())
        departments = list(queryset.values_list('department', flat=True).distinct())
        degrees = list(queryset.values_list('degree', flat=True).distinct())
        
        # Remove empty/null values and sort
        colleges = sorted(list(set(c.strip() for c in colleges if c and c.strip())))
        departments = sorted(list(set(d.strip() for d in departments if d and d.strip())))
        degrees = sorted(list(set(d.strip() for d in degrees if d and d.strip())))
        
        return Response({
            "success": True,
            "colleges": colleges,
            "departments": departments,
            "degrees": degrees
        })
    except Exception as e:
        return Response({"success": False, "error": str(e)}, status=500)


from pymongo import MongoClient

@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def list_certificate_approvers(request):
    try:
        employee_id = request.GET.get('employee_id')
        if not employee_id:
            return Response({"success": True, "data": None}, status=status.HTTP_200_OK)
            
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        global_db = client['Global']
        profile_collection = global_db['backend_diagnostics_profile']
        designation_collection = global_db['backend_diagnostics_Designation']
        
        p = profile_collection.find_one(
            {"employeeId": str(employee_id)},
            {"employeeId": 1, "employeeName": 1, "designation": 1, "signatureFileId": 1, "_id": 0}
        )
        
        if not p:
            return Response({"success": False, "error": "Employee not found"}, status=404)
            
        desig_code = p.get("designation")
        designation_name = ""
        if desig_code:
            desig_doc = designation_collection.find_one({"Designation_code": desig_code}, {"designation": 1})
            if desig_doc:
                designation_name = desig_doc.get("designation", "")
                
        data = {
            "employeeId": p.get("employeeId"),
            "employeeName": p.get("employeeName"),
            "designation": designation_name,
            "hasSignature": bool(p.get("signatureFileId"))
        }
            
        return Response({"success": True, "data": data}, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET', 'POST'])
@permission_classes([HasRoleAndDataPermission])
def certificate_template_list_or_create(request):
    try:
        # Check if default standard template exists
        default_exists = InternshipCertificateTemplate.objects.filter(template_id=1).exists()
        if not default_exists:
            InternshipCertificateTemplate.objects.create(
                template_id=1,
                title="Standard Template",
                description="This is to certify that [Student Name] has successfully completed their internship in the department of [Department] from [Start Date] to [End Date]. During this period, their performance was [Performance]."
            )
            
        if request.method == 'GET':
            templates = InternshipCertificateTemplate.objects.filter(is_active__in=[True]).order_by('template_id')
            data = []
            for t in templates:
                data.append({
                    "template_id": t.template_id,
                    "title": t.title,
                    "description": t.description
                })
            return Response({"success": True, "data": data}, status=status.HTTP_200_OK)
            
        elif request.method == 'POST':
            title = request.data.get("title", "Certificate Template").strip()
            description = request.data.get("description", "").strip()
            if not description:
                return Response({"success": False, "error": "Description cannot be empty"}, status=400)
                
            template = InternshipCertificateTemplate.objects.create(
                title=title,
                description=description
            )
            return Response({
                "success": True,
                "message": "Template created successfully",
                "data": {
                    "template_id": template.template_id,
                    "title": template.title,
                    "description": template.description
                }
            }, status=status.HTTP_201_CREATED)
            
    except Exception as e:
        return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['PUT', 'DELETE'])
@permission_classes([HasRoleAndDataPermission])
def certificate_template_detail(request, template_id):
    try:
        template = InternshipCertificateTemplate.objects.get(template_id=template_id, is_active__in=[True])
        
        if request.method == 'PUT':
            title = request.data.get("title", template.title).strip()
            description = request.data.get("description", template.description).strip()
            if not description:
                return Response({"success": False, "error": "Description cannot be empty"}, status=400)
            template.title = title
            template.description = description
            template.save()
            return Response({
                "success": True,
                "message": "Template updated successfully",
                "data": {
                    "template_id": template.template_id,
                    "title": template.title,
                    "description": template.description
                }
            })
            
        elif request.method == 'DELETE':
            template.is_active = False
            template.save()
            return Response({"success": True, "message": "Template deleted successfully"})
            
    except InternshipCertificateTemplate.DoesNotExist:
        return Response({"success": False, "error": "Template not found"}, status=404)
    except Exception as e:
        return Response({"success": False, "error": str(e)}, status=500)


@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def approve_internship_certificate(request, pk):
    try:
        branch_code = request.data.get('auth-branch-code') or request.GET.get('auth-branch-code') or 'system'
        hospital_code = request.data.get('auth-hospital-code') or request.GET.get('auth-hospital-code') or 'system'
        
        queryset = Internship.objects.filter(intern_id=pk, is_active__in=[True])
        if hospital_code and hospital_code != 'system':
            queryset = queryset.filter(Q(hospital_code=hospital_code) | Q(hospital_code__isnull=True) | Q(hospital_code="") | Q(hospital_code="system"))
        if branch_code and branch_code != 'system':
            queryset = queryset.filter(Q(branch_code=branch_code) | Q(branch_code__isnull=True) | Q(branch_code="") | Q(branch_code="system"))
            
        intern = queryset.get()
        cert_template_id = request.data.get("cert_template_id")
        cert_description = request.data.get("cert_description")
        is_approve = request.data.get("is_approve", False)
        
        intern.cert_template_id = int(cert_template_id) if cert_template_id is not None else 1
        if cert_description is not None:
            intern.cert_description = cert_description
            
        if is_approve:
            approved_by = request.data.get('auth-user-id') or (request.user.username if request.user and request.user.is_authenticated else 'system')
            intern.approved_by = approved_by
            intern.approved_at = timezone.now()
            message = "Certificate approved successfully"
        else:
            message = "Certificate saved successfully"
            
        normalise_internship_decimals(intern)
        intern.save()
        return Response({
            "success": True, 
            "message": message,
            "data": {
                "approved_by": intern.approved_by or "",
                "approved_at": intern.approved_at.strftime('%Y-%m-%d %H:%M:%S') if intern.approved_at else "",
                "cert_description": intern.cert_description or "",
                "cert_template_id": intern.cert_template_id
            }
        })
    except (Internship.DoesNotExist, ValueError):
        return Response({"success": False, "error": "Intern not found"}, status=404)
    except Exception as e:
        return Response({"success": False, "error": str(e)}, status=500)
