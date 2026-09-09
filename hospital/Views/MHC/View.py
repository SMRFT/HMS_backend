import datetime
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from django.utils import timezone
from datetime import datetime, timedelta
from pyauth.auth import HasRoleAndDataPermission
import traceback

from .models import MasterHealthcheckup
from .serializer import MasterHealthcheckupSerializer
from ..dbcollection import MHC_Package as MHC_Package_Collection, MHC_Source as MHC_Source_Collection


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def mhc_get_package(request):
    """
    GET: Returns all active MHC packages from MongoDB (hospital_MHC_Package)
    Only returns documents where is_active = True
    Returns package_name and package_fee for dropdown usage
    """
    try:
        packages = list(
            MHC_Package_Collection.find(
                {'is_active': True},
                {'_id': 0, 'package_name': 1, 'package_fee': 1}
            )
        )
        return Response({'packages': packages}, status=status.HTTP_200_OK)
    except Exception as e:
        traceback.print_exc()
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
# @permission_classes([HasRoleAndDataPermission])
def mhc_source(request):
    """
    GET: Returns all active MHC sources from MongoDB (hospital_MHC_Source)
    Only returns documents where is_active = True
    """
    try:
        sources = list(
            MHC_Source_Collection.find(
                {'is_active': True},
                {'_id': 0, 'source': 1}
            )
        )
        return Response({'sources': sources}, status=status.HTTP_200_OK)
    except Exception as e:
        traceback.print_exc()
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET', 'POST', 'PUT', 'PATCH'])
@permission_classes([HasRoleAndDataPermission])
def mhc_save_details(request):
    """
    GET:         Returns all saved MHC patient details
    POST/PUT:    Saves a new MHC patient record OR updates existing record if 'id' or '_id' provided
    """
    if request.method == 'GET':
        try:
            queryset = MasterHealthcheckup.objects.all().order_by('-created_date')
            serializer = MasterHealthcheckupSerializer(queryset, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            traceback.print_exc()
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    # Check if updating existing record
    mhc_no = request.data.get('mhc_no')
    record_id = request.data.get('id') or request.data.get('_id')
    
    if mhc_no is not None or record_id or request.method in ['PUT', 'PATCH']:
        if mhc_no is None and not record_id:
            return Response({'error': 'mhc_no or Record ID is required for update'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            instance = None

            # 1. Primary lookup using mhc_no
            if mhc_no is not None:
                try:
                    instance = MasterHealthcheckup.objects.filter(mhc_no=int(mhc_no)).first()
                except Exception:
                    pass

            # 2. Fallback lookup using record_id
            if not instance and record_id:
                try:
                    instance = MasterHealthcheckup.objects.get(id=str(record_id))
                except Exception:
                    pass

            if not instance:
                return Response({'error': 'Record not found'}, status=status.HTTP_404_NOT_FOUND)

            data = request.data.copy()
            employee_id = data.get('auth-user-id')
            data['lastmodified_by'] = employee_id

            # Strip description if empty/whitespace
            if 'description' in data and not str(data.get('description', '')).strip():
                data.pop('description', None)

            # Store telecaller_id + telecaller_date only when description is provided (e.g. from followup page)
            if 'description' in data and str(data['description']).strip():
                telecaller_id = data.get('telecaller_id') or employee_id
                if telecaller_id:
                    data['telecaller_id'] = telecaller_id
                    data['telecaller_date'] = timezone.now()
            else:
                data.pop('telecaller_id', None)
                data.pop('telecaller_date', None)

            serializer = MasterHealthcheckupSerializer(instance, data=data, partial=True)
            if serializer.is_valid():
                update_dict = {
                    k: v for k, v in serializer.validated_data.items()
                    if k not in ['id', '_id', 'created_by', 'created_date']
                }
                update_dict['lastmodified_by'] = employee_id
                update_dict['lastmodified_date'] = timezone.now()

                # Update data using mhc_no as primary update key
                if instance.mhc_no is not None:
                    MasterHealthcheckup.objects.filter(mhc_no=instance.mhc_no).update(**update_dict)
                    updated_instance = MasterHealthcheckup.objects.filter(mhc_no=instance.mhc_no).first()
                else:
                    MasterHealthcheckup.objects.filter(id=str(instance.id)).update(**update_dict)
                    updated_instance = MasterHealthcheckup.objects.filter(id=str(instance.id)).first()

                if updated_instance:
                    return Response(MasterHealthcheckupSerializer(updated_instance).data, status=status.HTTP_200_OK)
                return Response({'message': 'Master Health Checkup updated successfully'}, status=status.HTTP_200_OK)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except MasterHealthcheckup.DoesNotExist:
            return Response({'error': 'Record not found'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            traceback.print_exc()
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    # POST - save new MHC details
    try:
        data = request.data.copy()
        employee_id = data.get("auth-user-id")

        # 1. Store created_by and created_date
        data['created_by'] = employee_id
        data['created_date'] = timezone.now()

        # 3. Only store description if it has a value, and store telecaller info only if description exists
        if not data.get('description', '').strip():
            data.pop('description', None)
            data.pop('telecaller_id', None)
            data.pop('telecaller_date', None)
        else:
            data['telecaller_id'] = employee_id
            data['telecaller_date'] = timezone.now()

        serializer = MasterHealthcheckupSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        traceback.print_exc()
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)




@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def mhc_report(request):
    """
    GET: Returns MHC patient records filtered by from_date and to_date.
    Query params:
        from_date  - YYYY-MM-DD  (defaults to today)
        to_date    - YYYY-MM-DD  (defaults to today)
    """
    try:
        today_str = timezone.now().date().isoformat()
        from_date_str = request.query_params.get('from_date', today_str)
        to_date_str   = request.query_params.get('to_date',   today_str)

        from_dt = datetime.strptime(from_date_str, '%Y-%m-%d').replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        to_dt = datetime.strptime(to_date_str, '%Y-%m-%d').replace(
            hour=23, minute=59, second=59, microsecond=999999
        )

        queryset = MasterHealthcheckup.objects.filter(
            created_date__gte=from_dt,
            created_date__lte=to_dt,
        ).order_by('-created_date')

        serializer = MasterHealthcheckupSerializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    except ValueError as ve:
        return Response({'error': f'Invalid date format: {ve}'}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        traceback.print_exc()
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def mhc_dashboard(request):
    """
    GET: Returns month-wise aggregated dashboard data.
    Query params:
        from_date - YYYY-MM-DD (defaults to first day of current year)
        to_date   - YYYY-MM-DD (defaults to today)

    Returns:
        monthly_summary  : [{month, patient_count, total_revenue}]
        category_revenue : [{month, MHC, Others, total}]
        fee_breakdown    : [{month, package_fee, doctor_fee, add_tests, pharmacy, ip, total}]
        grand_totals     : summary of all columns
    """
    try:
        today = timezone.now().date()
        default_from = today.replace(month=1, day=1).isoformat()
        from_date_str = request.query_params.get('from_date', default_from)
        to_date_str   = request.query_params.get('to_date', today.isoformat())

        from_dt = datetime.strptime(from_date_str, '%Y-%m-%d').replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        to_dt = datetime.strptime(to_date_str, '%Y-%m-%d').replace(
            hour=23, minute=59, second=59, microsecond=999999
        )

        records = MasterHealthcheckup.objects.filter(
            created_date__gte=from_dt,
            created_date__lte=to_dt,
        ).values(
            'created_date', 'package', 'package_category',
            'package_fee', 'doctor_fee', 'add_tests', 'pharmacy', 'ip', 'total_fees'
        )

        # --- Aggregate by month key (e.g. "Jan-2026") ---
        from collections import defaultdict

        monthly_patients  = defaultdict(int)
        monthly_total     = defaultdict(float)
        category_rev      = defaultdict(lambda: {'MHC': 0.0, 'Others': 0.0})
        category_patients = defaultdict(lambda: {'MHC': 0, 'Others': 0})
        fee_rev           = defaultdict(lambda: {
            'package_fee': 0.0, 'doctor_fee': 0.0,
            'add_tests': 0.0, 'pharmacy': 0.0, 'ip': 0.0
        })
        package_patients  = defaultdict(int)
        package_revenue   = defaultdict(float)
        package_matrix_dict = defaultdict(lambda: {'category': 'Others', 'months': defaultdict(int)})
        month_order       = []  # preserves sorted order

        for rec in records:
            dt = rec['created_date']
            # Handle both datetime and date objects
            if hasattr(dt, 'strftime'):
                mkey = dt.strftime('%b-%Y')
            else:
                mkey = 'Unknown'

            if mkey not in month_order:
                month_order.append(mkey)

            # Convert safely: handles Decimal128 (BSON), Python Decimal, int, float, None
            def toF(v):
                if v is None:
                    return 0.0
                try:
                    return float(str(v))
                except (TypeError, ValueError):
                    return 0.0


            monthly_patients[mkey] += 1
            monthly_total[mkey]    += toF(rec['total_fees'])

            cat = rec.get('package_category') or 'Others'
            if cat not in ('MHC', 'Others'):
                cat = 'Others'
            category_rev[mkey][cat]      += toF(rec['total_fees'])
            category_patients[mkey][cat] += 1

            pkg_name = rec.get('package') or 'Unspecified'
            package_patients[pkg_name] += 1
            package_revenue[pkg_name]  += toF(rec['total_fees'])
            package_matrix_dict[pkg_name]['category'] = cat
            package_matrix_dict[pkg_name]['months'][mkey] += 1

            fee_rev[mkey]['package_fee'] += toF(rec['package_fee'])
            fee_rev[mkey]['doctor_fee']  += toF(rec['doctor_fee'])
            fee_rev[mkey]['add_tests']   += toF(rec['add_tests'])
            fee_rev[mkey]['pharmacy']    += toF(rec['pharmacy'])
            fee_rev[mkey]['ip']          += toF(rec['ip'])

        # Sort months chronologically
        from datetime import datetime as dt_cls
        def month_sort_key(m):
            try:
                return dt_cls.strptime(m, '%b-%Y')
            except Exception:
                return dt_cls.min

        month_order_sorted = sorted(set(month_order), key=month_sort_key)

        r2 = lambda v: round(v, 2)

        monthly_summary = [
            {
                'month':          m,
                'patient_count':  monthly_patients[m],
                'total_revenue':  r2(monthly_total[m]),
            }
            for m in month_order_sorted
        ]

        category_revenue = [
            {
                'month':  m,
                'MHC':    r2(category_rev[m]['MHC']),
                'Others': r2(category_rev[m]['Others']),
                'total':  r2(category_rev[m]['MHC'] + category_rev[m]['Others']),
            }
            for m in month_order_sorted
        ]

        category_patients_list = [
            {
                'month':  m,
                'MHC':    category_patients[m]['MHC'],
                'Others': category_patients[m]['Others'],
                'total':  category_patients[m]['MHC'] + category_patients[m]['Others'],
            }
            for m in month_order_sorted
        ]

        fee_breakdown = [
            {
                'month':       m,
                'package_fee': r2(fee_rev[m]['package_fee']),
                'doctor_fee':  r2(fee_rev[m]['doctor_fee']),
                'add_tests':   r2(fee_rev[m]['add_tests']),
                'pharmacy':    r2(fee_rev[m]['pharmacy']),
                'ip':          r2(fee_rev[m]['ip']),
                'total':       r2(monthly_total[m]),
            }
            for m in month_order_sorted
        ]

        package_summary = [
            {
                'package':       pkg,
                'patient_count': package_patients[pkg],
                'total_revenue': r2(package_revenue[pkg]),
            }
            for pkg in package_patients
        ]

        package_matrix_list = [
            {
                'package':        pkg,
                'category':       pinfo['category'],
                'monthly_counts': {m: pinfo['months'][m] for m in month_order_sorted},
                'total_patients': sum(pinfo['months'].values())
            }
            for pkg, pinfo in package_matrix_dict.items()
        ]

        grand_totals = {
            'patient_count':       sum(monthly_patients.values()),
            'total_revenue':       r2(sum(monthly_total.values())),
            'MHC':                 r2(sum(category_rev[m]['MHC']      for m in month_order_sorted)),
            'Others':              r2(sum(category_rev[m]['Others']    for m in month_order_sorted)),
            'patients_MHC':        sum(category_patients[m]['MHC']    for m in month_order_sorted),
            'patients_Others':     sum(category_patients[m]['Others'] for m in month_order_sorted),
            'patients_total':      sum(monthly_patients.values()),
            'package_fee':         r2(sum(fee_rev[m]['package_fee']   for m in month_order_sorted)),
            'doctor_fee':          r2(sum(fee_rev[m]['doctor_fee']    for m in month_order_sorted)),
            'add_tests':           r2(sum(fee_rev[m]['add_tests']     for m in month_order_sorted)),
            'pharmacy':            r2(sum(fee_rev[m]['pharmacy']      for m in month_order_sorted)),
            'ip':                  r2(sum(fee_rev[m]['ip']            for m in month_order_sorted)),
            'pkg_patients_total':  sum(package_patients.values()),
            'pkg_revenue_total':   r2(sum(package_revenue.values())),
            'monthly_patient_totals': {m: monthly_patients[m] for m in month_order_sorted},
        }

        return Response({
            'monthly_summary':      monthly_summary,
            'category_patients':    category_patients_list,
            'category_revenue':     category_revenue,
            'fee_breakdown':        fee_breakdown,
            'package_summary':      package_summary,
            'package_matrix':       package_matrix_list,
            'months_list':          month_order_sorted,
            'grand_totals':         grand_totals,
        }, status=status.HTTP_200_OK)

    except ValueError as ve:
        return Response({'error': f'Invalid date format: {ve}'}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        traceback.print_exc()
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

