from django.http import JsonResponse
from django.utils import timezone
from datetime import timedelta
from pymongo import MongoClient

from ..models import PharmacyStock, PharmacyItem


def pharmacy_notifications(request):
    try:
        today = timezone.now().date()
        days_30 = today + timedelta(days=30)
        days_90 = today + timedelta(days=90)

        # Get all stock records
        stocks = PharmacyStock.objects.all()

        expiry_data = []
        low_stock_map = {}

        # Get all item ids
        item_ids = list(
            set(
                [
                    stock.item_id
                    for stock in stocks
                    if stock.item_id is not None
                ]
            )
        )

        # Fetch item details
        items = PharmacyItem.objects.filter(item_id__in=item_ids)

        items_map = {}
        for item in items:
            items_map[item.item_id] = {
                "name": item.item_name,
                "reorder_level": item.reorder_level or 0,
            }

        # -----------------------------
        # Expiry + Stock Calculations
        # -----------------------------
        for stock in stocks:

            total_stock = stock.total_stock or 0
            sold_quantity = stock.sold_quantity or 0
            transferred_out_quantity = stock.transferred_out_quantity or 0
            grn_return_quantity = stock.grn_return_quantity or 0
            blocked_quantity = stock.blocked_quantity or 0
            sales_return_quantity = stock.sales_return_quantity or 0

            available = (
                total_stock
                - sold_quantity
                - transferred_out_quantity
                - grn_return_quantity
                - blocked_quantity
                + sales_return_quantity
            )

            # Skip zero/negative stock
            if available <= 0:
                continue

            # -----------------------------
            # Expiry Alerts
            # -----------------------------
            from datetime import datetime

            if stock.expiry_date:

                expiry_date = stock.expiry_date

                # If string -> convert to date
                if isinstance(expiry_date, str):

                    try:
                        expiry_date = datetime.strptime(
                            expiry_date[:10],
                            "%Y-%m-%d"
                        ).date()

                    except Exception:
                        continue

                # If datetime -> convert to date
                elif hasattr(expiry_date, "date"):

                    expiry_date = expiry_date.date()

                # Ensure valid date object
                if not isinstance(expiry_date, type(today)):
                    continue

                if today <= expiry_date <= days_90:

                    days_left = (expiry_date - today).days

                    urgency = (
                        "critical"
                        if expiry_date <= days_30
                        else "warning"
                    )

                    expiry_data.append({
                        "stock_id": stock.stock_id,
                        "item_id": stock.item_id,
                        "item_name": items_map.get(
                            stock.item_id,
                            {}
                        ).get("name", "Unknown"),
                        "batch_number": stock.batch_number,
                        "expiry_date": expiry_date.strftime("%d %b %Y"),
                        "days_left": days_left,
                        "available": available,
                        "urgency": urgency,
                    })

            # -----------------------------
            # Low Stock Calculation
            # -----------------------------
            if stock.item_id not in low_stock_map:
                low_stock_map[stock.item_id] = 0

            low_stock_map[stock.item_id] += available

        # Sort expiry alerts
        expiry_data = sorted(
            expiry_data,
            key=lambda x: x["days_left"]
        )

        # -----------------------------
        # Low Stock Alerts
        # -----------------------------
        low_stock_data = []

        for item_id, total_available in low_stock_map.items():

            item_info = items_map.get(item_id)

            if not item_info:
                continue

            reorder_level = item_info.get("reorder_level", 0)

            if reorder_level <= 0:
                continue

            if total_available < reorder_level:

                deficit = total_available - reorder_level

                low_stock_data.append({
                    "item_id": item_id,
                    "item_name": item_info.get("name"),
                    "available": total_available,
                    "reorder_level": reorder_level,
                    "deficit": deficit,
                    "urgency": (
                        "critical"
                        if total_available < (reorder_level * 0.3)
                        else "warning"
                    ),
                })

        # Sort by deficit
        low_stock_data = sorted(
            low_stock_data,
            key=lambda x: x["deficit"]
        )

        return JsonResponse({
            "success": True,
            "expiry_alerts": expiry_data,
            "low_stock_alerts": low_stock_data,
            "total_count": (
                len(expiry_data)
                + len(low_stock_data)
            ),
        })

    except Exception as e:
        return JsonResponse({
            "success": False,
            "error": str(e)
        }, status=500)