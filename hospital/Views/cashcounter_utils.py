
@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
def get_shift_summary_report(request):
    try:
        data = request.data
        from_date = data.get("from_date")
        to_date = data.get("to_date")
        hospital_code = data.get("auth-hospital-code")
        branch_code = data.get("auth-branch-code")

        queryset = Cashcountershiftdetails.objects.filter(
            hospital_code=hospital_code,
            branch_code=branch_code
        )

        if from_date:
            queryset = queryset.filter(date__gte=from_date)
        if to_date:
            queryset = queryset.filter(date__lte=to_date)

        shifts = queryset.order_by("-date", "-StartingTime")
        
        # Fetch cashier names
        cashier_ids = list(set([s.CashierID for s in shifts]))
        cashier_name_map = {}
        try:
            client = MongoClient(os.getenv("GLOBAL_DB_HOST"))
            db = client['Global']
            profiles = list(db['backend_diagnostics_profile'].find(
                {"employeeId": {"$in": cashier_ids}},
                {"employeeId": 1, "employeeName": 1, "_id": 0}
            ))
            cashier_name_map = {p['employeeId']: p['employeeName'] for p in profiles}
            client.close()
        except:
            pass

        report_data = []
        for s in shifts:
            res = format_shift_response(s)
            res["User"] = cashier_name_map.get(s.CashierID, s.CashierID)
            # Format times for report display
            res["StartTime"] = s.StartingTime.strftime("%I.%M%p").lower() if s.StartingTime else ""
            res["EndTime"] = s.closingTime.strftime("%I.%M%p").lower() if s.closingTime else ""
            report_data.append(res)

        return Response({
            "success": True,
            "data": report_data
        })

    except Exception as e:
        return Response({"success": False, "message": str(e)}, status=500)


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_registration_bills(request):
    try:
        # ✅ AUTH DATA (Robust header check)
        hospital_code = request.data.get("auth-hospital-code") or request.META.get("HTTP_AUTH_HOSPITAL_CODE")
        branch_code = request.data.get("auth-branch-code") or request.META.get("HTTP_AUTH_BRANCH_CODE") or request.META.get("HTTP_BRANCH_CODE")

        # ================================
        # ✅ FILTER BILLING DATA
        # ================================
        from ..models import Billing
        
        filter_query = {
            "payment_status": "Pending"
        }

        if hospital_code is not None:
            filter_query["hospital_code"] = hospital_code

        if branch_code is not None:
            filter_query["branch_code"] = branch_code

        # Using ORM for Registration bills as they are natively in Django
        bills = Billing.objects.select_related('patient').filter(**filter_query).order_by('-billed_date')

        response_data = []

        # ================================
        # ✅ BUILD RESPONSE
        # ================================
        for index, bill in enumerate(bills, start=1):
            patient = bill.patient
            billed_date = bill.billed_date
            date_str = billed_date.strftime("%d-%m-%Y") if billed_date else None
            time_str = billed_date.strftime("%H:%M:%S") if billed_date else None

            response_data.append({
                "Sl No": index,
                "Date": date_str,
                "Time": time_str,
                "Bill No": bill.bill_number,
                "Bill Type": "Registration",
                "UHID No": patient.uhid if patient else None,
                "Patient": f"{patient.firstName} {patient.lastName}" if patient else None,
                "Ip Number": getattr(patient, "ip_number", None),
                "total_fees": convert_decimal(bill.total_fees),
                "payment_status": bill.payment_status
            })

        return Response({
            "status": True,
            "count": len(response_data),
            "data": response_data
        }, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({
            "status": False,
            "message": str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
