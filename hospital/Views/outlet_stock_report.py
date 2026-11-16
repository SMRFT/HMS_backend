import json
import re
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from pyauth.auth import HasRoleAndDataPermission
from .dbcollection import hms_db, pharmacy_stock_collection, pharmacy_item_collection


@api_view(["GET"])
@permission_classes([HasRoleAndDataPermission])
def outlet_wise_stock_report(request):
    """
    Returns Outlet-Wise Stock Listing formatted matching the Shanmuga Hospital stock report:
    SL NO, ITEMNAME, STOCK, MRP, SALES VALUE, PURCHASE VALUE.
    Supports filtering by outlet_code, category, search query, and stock_filter.
    """
    outlet_code = (request.query_params.get("outlet_code") or request.GET.get("outlet_code") or "OLET002").strip()
    search_query = (request.query_params.get("search") or request.GET.get("search") or "").strip()
    category_filter = (request.query_params.get("category") or request.GET.get("category") or "").strip()
    stock_filter = (request.query_params.get("stock_filter") or request.GET.get("stock_filter") or "in_stock").strip().lower()

    try:
        # 1. Match active stocks for outlet
        match_q = {}
        if outlet_code and outlet_code.upper() != "ALL":
            match_q["outlet_code"] = outlet_code

        pipeline = [
            {"$match": match_q},
            {"$project": {
                "item_id": 1,
                "batch_number": 1,
                "expiry_date": 1,
                "mrp": 1,
                "Selling_Price": 1,
                "grn_number": 1,
                "outlet_code": 1,
                "total_stock": {"$ifNull": ["$total_stock", 0]},
                "sold_quantity": {"$ifNull": ["$sold_quantity", 0]},
                "transferred_out_quantity": {"$ifNull": ["$transferred_out_quantity", 0]},
                "grn_return_quantity": {"$ifNull": ["$grn_return_quantity", 0]},
                "blocked_quantity": {"$ifNull": ["$blocked_quantity", 0]},
                "sales_return_quantity": {"$ifNull": ["$sales_return_quantity", 0]}
            }},
            {"$addFields": {
                "avail_stock": {
                    "$subtract": [
                        "$total_stock",
                        {
                            "$subtract": [
                                {
                                    "$add": [
                                        "$sold_quantity",
                                        "$transferred_out_quantity",
                                        "$grn_return_quantity",
                                        "$blocked_quantity"
                                    ]
                                },
                                "$sales_return_quantity"
                            ]
                        }
                    ]
                }
            }}
        ]

        if stock_filter == "in_stock":
            pipeline.append({"$match": {"avail_stock": {"$gt": 0}}})
        elif stock_filter == "zero_stock":
            pipeline.append({"$match": {"avail_stock": {"$lte": 0}}})

        stocks = list(pharmacy_stock_collection.aggregate(pipeline))

        # Collect unique batch numbers and item IDs
        active_batches = set()
        item_ids = set()
        for s in stocks:
            b = str(s.get("batch_number") or "").strip()
            if b:
                active_batches.add(b)
            iid = s.get("item_id")
            if iid:
                item_ids.add(iid)

        # 2. Build GRN batch pricing lookup (batch -> purchase_cost, selling_price, mrp)
        batch_info = {}
        if active_batches:
            grn_cursor = hms_db["hospital_grn"].find(
                {"items": {"$exists": True, "$ne": []}},
                {"items": 1, "grn_number": 1}
            )
            for g in grn_cursor:
                raw_items = g.get("items", [])
                if isinstance(raw_items, str):
                    try:
                        raw_items = json.loads(raw_items)
                    except Exception:
                        raw_items = []
                for it in raw_items:
                    if not isinstance(it, dict):
                        continue
                    b = str(it.get("batch") or it.get("batch_number") or "").strip()
                    if b and b in active_batches and b not in batch_info:
                        pc = it.get("purchase_cost") or it.get("purchase_cost_display")
                        if pc:
                            try:
                                pc = float(pc)
                            except (ValueError, TypeError):
                                pc = 0.0
                        else:
                            up = float(it.get("unit_price") or it.get("rate") or 0.0)
                            tax = float(it.get("purchase_tax_rate") or it.get("tax_percentage") or 0.0)
                            pc = round(up * (1 + tax / 100), 4)

                        sp = float(it.get("selling_price") or it.get("Selling_Price") or 0.0)
                        mrp = float(it.get("mrp") or 0.0)
                        batch_info[b] = {
                            "purchase_cost": pc,
                            "selling_price": sp,
                            "mrp": mrp
                        }

        # 3. Item Master Map (item_name, category)
        items_map = {}
        if item_ids:
            for it in pharmacy_item_collection.find({"item_id": {"$in": list(item_ids)}}):
                items_map[it.get("item_id")] = it

        # Category mapping helper
        cat_map = {}
        try:
            for c in hms_db["hospital_pharmacycategory"].find():
                cat_id = c.get("category_id") or c.get("id") or c.get("_id")
                if cat_id:
                    cat_map[str(cat_id)] = c.get("category_name", str(cat_id))
                    cat_map[cat_id] = c.get("category_name", str(cat_id))
        except Exception:
            pass

        # 4. Item-level Aggregation
        item_rollup = {}
        for s in stocks:
            iid = s.get("item_id")
            it_meta = items_map.get(iid, {})
            iname = str(it_meta.get("item_name") or f"Item {iid}").strip()
            cat_id = it_meta.get("category")
            cat_name = cat_map.get(str(cat_id)) or cat_map.get(cat_id) or str(cat_id or "General")

            bno = str(s.get("batch_number") or "").strip()
            qty = float(s.get("avail_stock") or 0.0)

            b_data = batch_info.get(bno, {})
            mrp = float(s.get("mrp") or b_data.get("mrp") or it_meta.get("mrp") or 0.0)
            sp = float(s.get("Selling_Price") or b_data.get("selling_price") or mrp)
            pc = float(b_data.get("purchase_cost") or it_meta.get("purchase_rate") or (mrp * 0.7))

            exp_str = ""
            exp_val = s.get("expiry_date")
            if exp_val:
                exp_str = str(exp_val)[:10]

            if iid not in item_rollup:
                item_rollup[iid] = {
                    "item_id": iid,
                    "item_name": iname,
                    "category": cat_name,
                    "stock": 0.0,
                    "mrp": mrp,
                    "sales_value": 0.0,
                    "purchase_value": 0.0,
                    "batches": []
                }

            item_rollup[iid]["stock"] += qty
            item_rollup[iid]["mrp"] = max(item_rollup[iid]["mrp"], mrp)
            item_rollup[iid]["sales_value"] += round(qty * sp, 2)
            item_rollup[iid]["purchase_value"] += round(qty * pc, 2)
            item_rollup[iid]["batches"].append({
                "batch_number": bno,
                "expiry_date": exp_str,
                "stock": int(qty) if qty.is_integer() else round(qty, 2),
                "mrp": round(mrp, 2),
                "selling_price": round(sp, 2),
                "purchase_cost": round(pc, 2),
                "sales_value": round(qty * sp, 2),
                "purchase_value": round(qty * pc, 2)
            })

        # 5. Apply Category and Search Filters
        records = []
        tot_stock_units = 0.0
        tot_sales_value = 0.0
        tot_purchase_value = 0.0

        for it in item_rollup.values():
            # Category filter
            if category_filter and category_filter.lower() != "all":
                if str(it.get("category", "")).lower() != category_filter.lower():
                    continue

            # Search filter
            if search_query:
                q = search_query.lower()
                matches_item = q in it["item_name"].lower() or q in str(it["item_id"]).lower()
                matches_batch = any(q in b["batch_number"].lower() for b in it["batches"])
                if not (matches_item or matches_batch):
                    continue

            tot_stock_units += it["stock"]
            tot_sales_value += it["sales_value"]
            tot_purchase_value += it["purchase_value"]
            records.append(it)

        # Sort alphabetically by Item Name matching Shanmuga standard listing
        records.sort(key=lambda x: str(x.get("item_name") or "").strip().upper())

        # Format rows with SL NO
        formatted_data = []
        for idx, r in enumerate(records, 1):
            stk_val = r["stock"]
            formatted_data.append({
                "sl_no": idx,
                "item_id": r["item_id"],
                "item_name": r["item_name"],
                "category": r["category"],
                "stock": int(stk_val) if stk_val.is_integer() else round(stk_val, 2),
                "mrp": round(r["mrp"], 2),
                "sales_value": round(r["sales_value"], 2),
                "purchase_value": round(r["purchase_value"], 2),
                "batches": r["batches"]
            })

        # Fetch outlet name for display header
        outlet_name = "PHARMACY"
        try:
            o_doc = hms_db["hospital_outlets"].find_one({"outlet_code": outlet_code})
            if o_doc and o_doc.get("outlet_name"):
                outlet_name = o_doc.get("outlet_name")
        except Exception:
            pass

        return Response({
            "success": True,
            "outlet_code": outlet_code,
            "outlet_name": outlet_name,
            "summary": {
                "total_items": len(formatted_data),
                "total_stock_units": int(tot_stock_units) if tot_stock_units.is_integer() else round(tot_stock_units, 2),
                "total_sales_value": round(tot_sales_value, 2),
                "total_purchase_value": round(tot_purchase_value, 2)
            },
            "data": formatted_data
        }, status=status.HTTP_200_OK)

    except Exception as e:
        import traceback
        print(f"Error in outlet_wise_stock_report: {e}")
        print(traceback.format_exc())
        return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
