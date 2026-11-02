import os
import json
import pymongo
from django.core.management.base import BaseCommand
from dotenv import load_dotenv

class Command(BaseCommand):
    help = "Backfill billTypeNo and nabh_code in hospital_investbilling for ward requests"

    def handle(self, *args, **options):
        load_dotenv(r'd:\Parthi\HMS\HMS_backend\.env')
        client = pymongo.MongoClient(os.getenv('GLOBAL_DB_HOST'))
        db = client['HMS']

        # 1. Build LAB NABH lookups
        nabh_records = list(db['hospital_lab_nabh_rate'].find({}, {'_id': 0, 'test_id': 1, 'nabh_code': 1, 'test_name': 1}))
        lab_map_by_id = {str(r.get('test_id', '')).strip(): str(r.get('nabh_code', '')).strip() for r in nabh_records if r.get('test_id') is not None}
        lab_map_by_name = {str(r.get('test_name', '')).strip().lower(): str(r.get('nabh_code', '')).strip() for r in nabh_records if r.get('test_name')}

        # 2. Build Radiology lookups by billTypeNo
        inv_prices = list(db['hospital_investigationprice'].find({}, {'_id': 0, 'billTypeNo': 1, 'Items': 1}))
        rad_lookup = {}
        for doc in inv_prices:
            btn = str(doc.get('billTypeNo', '')).strip().upper()
            if not btn:
                continue
            by_id = {}
            by_name = {}
            for itm in doc.get('Items', []):
                i_id = str(itm.get('item_id', '')).strip()
                i_name = str(itm.get('itemName', '')).strip().lower()
                n_code = ""
                for k, v in itm.items():
                    if isinstance(v, dict) and v.get('nabh_code'):
                        n_code = str(v.get('nabh_code')).strip()
                        if n_code:
                            break
                if i_id and n_code:
                    by_id[i_id] = n_code
                if i_name and n_code:
                    by_name[i_name] = n_code
            rad_lookup[btn] = {'by_id': by_id, 'by_name': by_name}

        # 3. Process ward request documents
        ward_docs = list(db['hospital_investbilling'].find({'is_ward_request': True}))
        self.stdout.write(f"Found {len(ward_docs)} ward requests to check/backfill.")

        updated_count = 0
        for doc in ward_docs:
            req_type = doc.get('ward_request_type', '').upper()
            bill_no = doc.get('investBillNo', '')
            
            raw_items = doc.get('item', [])
            if isinstance(raw_items, str):
                try:
                    items = json.loads(raw_items)
                except Exception:
                    items = []
            elif isinstance(raw_items, list):
                items = raw_items
            else:
                items = []

            if req_type == 'LAB':
                root_btn = doc.get('billTypeNo') or "LAB01"
                root_bt = doc.get('bill_type') or "62"
            else:
                parts = bill_no.split('/')
                if len(parts) >= 2 and parts[1]:
                    root_btn = parts[1]
                else:
                    root_btn = doc.get('billTypeNo') or "RAD"
                root_bt = doc.get('bill_type') or doc.get('billtype') or "81"

            enriched_items = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                item_btn = it.get('billTypeNo') or root_btn
                item_nabh = str(it.get('nabh_code') or '').strip()
                
                if req_type == 'LAB':
                    t_id = str(it.get('test_id', '')).strip()
                    t_name = str(it.get('itemName', '')).strip().lower()
                    if not item_nabh:
                        if t_id and t_id in lab_map_by_id:
                            item_nabh = lab_map_by_id[t_id]
                        elif t_name in lab_map_by_name:
                            item_nabh = lab_map_by_name[t_name]
                else:
                    i_id = str(it.get('item_id', '') or it.get('test_id', '')).strip()
                    i_name = str(it.get('itemName', '')).strip().lower()
                    btn_key = item_btn.upper()
                    if not item_nabh and btn_key in rad_lookup:
                        if i_id and i_id in rad_lookup[btn_key]['by_id']:
                            item_nabh = rad_lookup[btn_key]['by_id'][i_id]
                        elif i_name in rad_lookup[btn_key]['by_name']:
                            item_nabh = rad_lookup[btn_key]['by_name'][i_name]

                it['billTypeNo'] = item_btn
                it['nabh_code'] = item_nabh
                it['bill_type'] = it.get('bill_type') or it.pop('billtype', None) or root_bt
                it.pop('billtype', None)
                
                enriched_items.append(it)

            update_payload = {
                'bill_type': root_bt,
                'item': enriched_items
            }
            if not doc.get('finalPrice') and doc.get('total_amount'):
                update_payload['finalPrice'] = doc.get('total_amount')

            db['hospital_investbilling'].update_one(
                {'_id': doc['_id']},
                {
                    '$set': update_payload,
                    '$unset': {'selectedTests': '', 'billtype': '', 'billTypeNo': '', 'billTypeName': ''}
                }
            )
            updated_count += 1

        self.stdout.write(self.style.SUCCESS(f"Successfully processed {updated_count} ward request documents!"))

