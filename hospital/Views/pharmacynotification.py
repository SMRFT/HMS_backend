from django.http import JsonResponse
from django.utils import timezone
from datetime import timedelta, datetime
import logging
from .mongo_utils import get_hms_db

logger = logging.getLogger(__name__)


def pharmacy_notifications(request):
    try:
        today = timezone.now().date()
        days_30 = today + timedelta(days=30)
        days_90 = today + timedelta(days=90)

        hospital_code = (
            request.GET.get("hospital_code") or
            request.headers.get("auth-hospital-code") or
            request.headers.get("hospital-code")
        )
        branch_code = (
            request.GET.get("branch_code") or
            request.headers.get("auth-branch-code") or
            request.headers.get("Branch-Code")
        )
        outlet_code = (
            request.GET.get("outlet_code") or
            request.headers.get("auth-outlet-code") or
            request.headers.get("outlet-code") or
            ""
        ).strip()

        _, db = get_hms_db()

        outlet_map = {
            "OLET001": "IP Pharmacy",
            "OLET002": "OP Pharmacy",
            "OLET003": "Main Store",
        }
        try:
            for o in db.hospital_outlet.find({}, {"outlet_code": 1, "outlet_name": 1, "_id": 0}):
                if o.get("outlet_code") and o.get("outlet_name"):
                    outlet_map[o["outlet_code"]] = o["outlet_name"]
        except Exception:
            pass

        stock_filter = {}
        if hospital_code and hospital_code != "system":
            stock_filter["hospital_code"] = hospital_code
        if branch_code and branch_code != "system":
            stock_filter["branch_code"] = branch_code

        # If user is in specific outlet (OLET001 - IP Pharmacy or OLET002 - OP Pharmacy)
        if outlet_code in ("OLET001", "OLET002"):
            stock_filter["outlet_code"] = outlet_code

        # Projection to fetch only required fields
        stock_projection = {
            "stock_id": 1,
            "item_id": 1,
            "batch_number": 1,
            "expiry_date": 1,
            "total_stock": 1,
            "sold_quantity": 1,
            "transferred_out_quantity": 1,
            "grn_return_quantity": 1,
            "blocked_quantity": 1,
            "sales_return_quantity": 1,
            "outlet_code": 1,
            "_id": 0,
        }

        stocks = list(db["hospital_pharmacystock"].find(stock_filter, stock_projection))

        item_ids = list({s.get("item_id") for s in stocks if s.get("item_id") is not None})

        # Fetch item details in one batch query with projection
        items_map = {}
        if item_ids:
            items_cursor = db["hospital_pharmacyitem"].find(
                {"item_id": {"$in": item_ids}},
                {"item_id": 1, "item_name": 1, "reorder_level": 1, "_id": 0}
            )
            for it in items_cursor:
                items_map[it.get("item_id")] = {
                    "name": it.get("item_name") or "Unknown",
                    "reorder_level": float(it.get("reorder_level") or 0),
                }

        expiry_data = []
        low_stock_map = {}

        # -----------------------------
        # Expiry + Stock Calculations
        # -----------------------------
        for stock in stocks:
            total_stock = float(stock.get("total_stock") or 0)
            sold_quantity = float(stock.get("sold_quantity") or 0)
            transferred_out_quantity = float(stock.get("transferred_out_quantity") or 0)
            grn_return_quantity = float(stock.get("grn_return_quantity") or 0)
            blocked_quantity = float(stock.get("blocked_quantity") or 0)
            sales_return_quantity = float(stock.get("sales_return_quantity") or 0)

            available = (
                total_stock
                - sold_quantity
                - transferred_out_quantity
                - grn_return_quantity
                - blocked_quantity
                + sales_return_quantity
            )

            if available <= 0:
                continue

            item_id = stock.get("item_id")
            s_out = str(stock.get("outlet_code") or "").strip()
            s_out_name = outlet_map.get(s_out, "OP Pharmacy" if s_out == "OLET002" else ("IP Pharmacy" if s_out == "OLET001" else s_out or "Pharmacy"))

            # -----------------------------
            # Expiry Alerts
            # -----------------------------
            raw_expiry = stock.get("expiry_date")
            if raw_expiry:
                expiry_date = None
                if isinstance(raw_expiry, str):
                    try:
                        expiry_date = datetime.strptime(raw_expiry[:10], "%Y-%m-%d").date()
                    except Exception:
                        pass
                elif hasattr(raw_expiry, "date"):
                    expiry_date = raw_expiry.date()
                elif isinstance(raw_expiry, datetime):
                    expiry_date = raw_expiry.date()

                if expiry_date and isinstance(expiry_date, type(today)) and today <= expiry_date <= days_90:
                    days_left = (expiry_date - today).days
                    urgency = "critical" if expiry_date <= days_30 else "warning"

                    expiry_data.append({
                        "stock_id": stock.get("stock_id"),
                        "item_id": item_id,
                        "item_name": items_map.get(item_id, {}).get("name", "Unknown"),
                        "batch_number": stock.get("batch_number"),
                        "expiry_date": expiry_date.strftime("%d %b %Y"),
                        "days_left": days_left,
                        "available": available,
                        "urgency": urgency,
                        "outlet_code": s_out,
                        "outlet_name": s_out_name,
                    })

            # -----------------------------
            # Low Stock Calculation (per item & outlet)
            # -----------------------------
            if item_id:
                key = (item_id, s_out) if outlet_code not in ("OLET001", "OLET002") else item_id
                low_stock_map[key] = low_stock_map.get(key, 0) + available

        # Sort expiry alerts
        expiry_data.sort(key=lambda x: x["days_left"])

        # -----------------------------
        # Low Stock Alerts
        # -----------------------------
        low_stock_data = []
        for key, total_available in low_stock_map.items():
            if isinstance(key, tuple):
                item_id, s_out = key
            else:
                item_id, s_out = key, outlet_code

            item_info = items_map.get(item_id)
            if not item_info:
                continue

            reorder_level = item_info.get("reorder_level", 0)
            if reorder_level <= 0:
                continue

            if total_available < reorder_level:
                deficit = total_available - reorder_level
                s_out_name = outlet_map.get(s_out, "OP Pharmacy" if s_out == "OLET002" else ("IP Pharmacy" if s_out == "OLET001" else s_out or "Pharmacy"))
                low_stock_data.append({
                    "item_id": item_id,
                    "item_name": item_info.get("name"),
                    "available": total_available,
                    "reorder_level": reorder_level,
                    "deficit": deficit,
                    "urgency": "critical" if total_available < (reorder_level * 0.3) else "warning",
                    "outlet_code": s_out,
                    "outlet_name": s_out_name,
                })

        # Sort by deficit
        low_stock_data.sort(key=lambda x: x["deficit"])

        # Breakdown counts
        op_expiry_count = len([e for e in expiry_data if e.get("outlet_code") == "OLET002"])
        ip_expiry_count = len([e for e in expiry_data if e.get("outlet_code") == "OLET001"])
        op_low_count = len([l for l in low_stock_data if l.get("outlet_code") == "OLET002"])
        ip_low_count = len([l for l in low_stock_data if l.get("outlet_code") == "OLET001"])

        return JsonResponse({
            "success": True,
            "outlet_code": outlet_code or "ALL",
            "outlet_name": outlet_map.get(outlet_code, "All Outlets (Common)"),
            "expiry_alerts": expiry_data,
            "low_stock_alerts": low_stock_data,
            "counts": {
                "total": len(expiry_data) + len(low_stock_data),
                "op_total": op_expiry_count + op_low_count,
                "ip_total": ip_expiry_count + ip_low_count,
                "op_expiry": op_expiry_count,
                "ip_expiry": ip_expiry_count,
                "op_low_stock": op_low_count,
                "ip_low_stock": ip_low_count,
            },
            "total_count": len(expiry_data) + len(low_stock_data),
        })

    except Exception as e:
        logger.error("[pharmacy_notifications] %s", e, exc_info=True)
        return JsonResponse({
            "success": False,
            "error": str(e)
        }, status=500)
