import sys

code_to_append = """

from ..models import CrashCartItem, CrashCartDailyCheck

@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_crash_cart_items(request):
    try:
        items = CrashCartItem.objects.all().order_by('box_category', 'id')
        data = [
            {
                "id": item.id,
                "box_category": item.box_category,
                "drug_name": item.drug_name,
                "required_stock": item.required_stock,
            }
            for item in items
        ]
        return Response({"success": True, "data": data})
    except Exception as e:
        return Response({"success": False, "error": str(e)}, status=500)

@api_view(["POST"])
@permission_classes([HasRoleAndDataPermission])
def save_crash_cart_daily_check(request):
    try:
        data = request.data
        date_str = data.get("date")
        nursing_station = data.get("nursing_station")
        checks = data.get("checks", [])
        checked_by = data.get("auth-employee-name", "Nurse")

        if not date_str or not nursing_station:
            return Response({"success": False, "error": "Date and Nursing Station are required."}, status=400)

        date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()

        for check in checks:
            item_id = check.get("item_id")
            expiry_date = check.get("expiry_date")
            is_checked = check.get("is_checked", False)

            item = CrashCartItem.objects.filter(id=item_id).first()
            if not item:
                continue

            obj, created = CrashCartDailyCheck.objects.update_or_create(
                date=date_obj,
                nursing_station=nursing_station,
                item=item,
                defaults={
                    "expiry_date": expiry_date,
                    "is_checked": is_checked,
                    "checked_by": checked_by,
                }
            )

        return Response({"success": True, "message": "Daily check saved successfully."})
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return Response({"success": False, "error": str(e)}, status=500)

@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def get_crash_cart_monthly_report(request):
    try:
        month = int(request.GET.get("month"))
        year = int(request.GET.get("year"))
        nursing_station = request.GET.get("nursing_station")

        if not month or not year or not nursing_station:
            return Response({"success": False, "error": "Month, Year, and Nursing Station are required."}, status=400)

        # Get all items
        items = CrashCartItem.objects.all().order_by('box_category', 'id')
        
        # Get all checks for the given month and year
        import calendar
        _, last_day = calendar.monthrange(year, month)
        start_date = datetime(year, month, 1).date()
        end_date = datetime(year, month, last_day).date()

        checks = CrashCartDailyCheck.objects.filter(
            nursing_station=nursing_station,
            date__gte=start_date,
            date__lte=end_date,
        )

        # Create a dictionary mapping (item_id, day) -> check
        checks_map = {}
        for check in checks:
            checks_map[(check.item_id, check.date.day)] = {
                "is_checked": check.is_checked,
                "expiry_date": check.expiry_date,
                "checked_by": check.checked_by
            }

        report_data = []
        for item in items:
            item_row = {
                "id": item.id,
                "box_category": item.box_category,
                "drug_name": item.drug_name,
                "required_stock": item.required_stock,
                "days": {}
            }
            
            # Populate days
            latest_expiry = ""
            for day in range(1, last_day + 1):
                check = checks_map.get((item.id, day))
                if check:
                    item_row["days"][day] = check["is_checked"]
                    if check["expiry_date"]:
                        latest_expiry = check["expiry_date"]
                else:
                    item_row["days"][day] = False

            item_row["expiry_date"] = latest_expiry # take the most recently noted expiry
            report_data.append(item_row)

        return Response({"success": True, "data": report_data})
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return Response({"success": False, "error": str(e)}, status=500)
"""

with open("hospital/Views/NursingStation.py", "a") as f:
    f.write(code_to_append)

print("Appended views successfully")
