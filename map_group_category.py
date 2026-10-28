import os
import sys
import datetime
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
django.setup()

from hospital.Views.dbcollection import hms_db

def run_migration():
    print("=== STARTING GROUP & CATEGORY MIGRATION & PROPER MAPPING ===")

    # 1. HOSPITAL_GROUP: Sync group_name and groupName
    print("\n--- 1. Synchronizing hospital_group (group_name <-> groupName) ---")
    groups_updated = 0
    for g in hms_db['hospital_group'].find():
        updates = {}
        gname = g.get('group_name') or g.get('groupName')
        if not g.get('group_name') and gname:
            updates['group_name'] = gname
        if not g.get('groupName') and gname:
            updates['groupName'] = gname
        if updates:
            hms_db['hospital_group'].update_one({'_id': g['_id']}, {'$set': updates})
            groups_updated += 1
    print(f"Updated {groups_updated} groups in hospital_group.")

    # 2. VENDING MACHINE CATEGORIES: Rename CAT00003..CAT00057 (branch SHB001) to VMC00003..VMC00057
    print("\n--- 2. Renaming Vending Machine categories to VMC prefix ---")
    vm_cats = list(hms_db['hospital_category'].find({'branch_code': 'SHB001'}))
    vm_cat_id_map = {}
    for c in vm_cats:
        old_id = c.get('category_id')
        if old_id and old_id.startswith('CAT'):
            new_id = old_id.replace('CAT', 'VMC', 1)
            vm_cat_id_map[old_id] = new_id
            cname = c.get('category_name') or c.get('categoryName')
            hms_db['hospital_category'].update_one(
                {'_id': c['_id']},
                {'$set': {
                    'category_id': new_id,
                    'group': 'GRP00004', # Vending Machine group
                    'category_name': cname,
                    'categoryName': cname
                }}
            )
    print(f"Renamed {len(vm_cat_id_map)} Vending Machine categories from CAT to VMC and set group='GRP00004'.")

    # Update Vending Machine Sales to use new VMC category IDs
    vm_sales_updated = 0
    for old_id, new_id in vm_cat_id_map.items():
        res = hms_db['hospital_vendingmachinesale'].update_many(
            {'category_id': old_id},
            {'$set': {'category_id': new_id}}
        )
        vm_sales_updated += res.modified_count
    print(f"Updated {vm_sales_updated} records in hospital_vendingmachinesale to new VMC category IDs.")

    # 3. HOSPITAL_CATEGORY: Sync category_name and categoryName for genuine hospital categories
    print("\n--- 3. Synchronizing hospital_category (category_name <-> categoryName) ---")
    cats_updated = 0
    for c in hms_db['hospital_category'].find():
        updates = {}
        cname = c.get('category_name') or c.get('categoryName')
        if not c.get('category_name') and cname:
            updates['category_name'] = cname
        if not c.get('categoryName') and cname:
            updates['categoryName'] = cname
        if updates:
            hms_db['hospital_category'].update_one({'_id': c['_id']}, {'$set': updates})
            cats_updated += 1
    print(f"Synchronized names for {cats_updated} categories.")

    # Fix CAT00174 (CLOTH) group to GRP00036 (CLOTH)
    hms_db['hospital_category'].update_many(
        {'category_id': 'CAT00174'},
        {'$set': {'group': 'GRP00036'}}
    )
    print("Set CAT00174 (CLOTH) group to GRP00036.")

    # 4. REGISTER 12 ESSENTIAL HOSPITAL CATEGORIES
    print("\n--- 4. Registering/Ensuring Essential Hospital Categories in hospital_category ---")
    essential_categories = [
        {
            'category_id': 'CAT00015',
            'category_name': 'LAB REAGENTS',
            'categoryName': 'LAB REAGENTS',
            'group': 'GRP00015',
            'group_type': 'GRPT00002',
            'branch_code': 'SHB005',
            'outlet_code': 'system',
            'hospital_code': 'SH001',
            'is_active': True,
            'created_by': 'system',
            'created_date': datetime.datetime.now()
        },
        {
            'category_id': 'CAT00013',
            'category_name': 'CONTROLS & STANDARDS',
            'categoryName': 'CONTROLS & STANDARDS',
            'group': 'GRP00015',
            'group_type': 'GRPT00002',
            'branch_code': 'SHB005',
            'outlet_code': 'system',
            'hospital_code': 'SH001',
            'is_active': True,
            'created_by': 'system',
            'created_date': datetime.datetime.now()
        },
        {
            'category_id': 'CAT00205',
            'category_name': 'LAB SOLUTIONS',
            'categoryName': 'LAB SOLUTIONS',
            'group': 'GRP00015',
            'group_type': 'GRPT00002',
            'branch_code': 'SHB005',
            'outlet_code': 'system',
            'hospital_code': 'SH001',
            'is_active': True,
            'created_by': 'system',
            'created_date': datetime.datetime.now()
        },
        {
            'category_id': 'CAT00288',
            'category_name': 'CATH LAB ITEMS',
            'categoryName': 'CATH LAB ITEMS',
            'group': 'GRP00054',
            'group_type': 'GRPT00002',
            'branch_code': 'SHB005',
            'outlet_code': 'system',
            'hospital_code': 'SH001',
            'is_active': True,
            'created_by': 'system',
            'created_date': datetime.datetime.now()
        },
        {
            'category_id': 'CAT00300',
            'category_name': 'PLUMBING & SANITARY',
            'categoryName': 'PLUMBING & SANITARY',
            'group': 'GRP00057',
            'group_type': 'GRPT00002',
            'branch_code': 'SHB005',
            'outlet_code': 'system',
            'hospital_code': 'SH001',
            'is_active': True,
            'created_by': 'system',
            'created_date': datetime.datetime.now()
        },
        {
            'category_id': 'CAT00121',
            'category_name': 'ELECTRICAL APPLIANCES',
            'categoryName': 'ELECTRICAL APPLIANCES',
            'group': 'GRP00057',
            'group_type': 'GRPT00002',
            'branch_code': 'SHB005',
            'outlet_code': 'system',
            'hospital_code': 'SH001',
            'is_active': True,
            'created_by': 'system',
            'created_date': datetime.datetime.now()
        },
        {
            'category_id': 'CAT00234',
            'category_name': 'DENTAL CONSUMABLES',
            'categoryName': 'DENTAL CONSUMABLES',
            'group': 'GRP00047',
            'group_type': 'GRPT00002',
            'branch_code': 'SHB005',
            'outlet_code': 'system',
            'hospital_code': 'SH001',
            'is_active': True,
            'created_by': 'system',
            'created_date': datetime.datetime.now()
        },
        {
            'category_id': 'CAT00168',
            'category_name': 'DIALYSIS CONSUMABLES',
            'categoryName': 'DIALYSIS CONSUMABLES',
            'group': 'GRP00034',
            'group_type': 'GRPT00002',
            'branch_code': 'SHB005',
            'outlet_code': 'system',
            'hospital_code': 'SH001',
            'is_active': True,
            'created_by': 'system',
            'created_date': datetime.datetime.now()
        },
        {
            'category_id': 'CAT00173',
            'category_name': 'DIALYSIS FLUIDS',
            'categoryName': 'DIALYSIS FLUIDS',
            'group': 'GRP00034',
            'group_type': 'GRPT00002',
            'branch_code': 'SHB005',
            'outlet_code': 'system',
            'hospital_code': 'SH001',
            'is_active': True,
            'created_by': 'system',
            'created_date': datetime.datetime.now()
        },
        {
            'category_id': 'CAT00186',
            'category_name': 'USG PAPERS & ROLLS',
            'categoryName': 'USG PAPERS & ROLLS',
            'group': 'GRP00035',
            'group_type': 'GRPT00002',
            'branch_code': 'SHB005',
            'outlet_code': 'system',
            'hospital_code': 'SH001',
            'is_active': True,
            'created_by': 'system',
            'created_date': datetime.datetime.now()
        },
        {
            'category_id': 'CAT00230',
            'category_name': 'ECG & CT FILMS',
            'categoryName': 'ECG & CT FILMS',
            'group': 'GRP00035',
            'group_type': 'GRPT00002',
            'branch_code': 'SHB005',
            'outlet_code': 'system',
            'hospital_code': 'SH001',
            'is_active': True,
            'created_by': 'system',
            'created_date': datetime.datetime.now()
        },
        {
            'category_id': 'CAT00318',
            'category_name': 'ROBOTIC INSTRUMENTS',
            'categoryName': 'ROBOTIC INSTRUMENTS',
            'group': 'GRP00074',
            'group_type': 'GRPT00002',
            'branch_code': 'SHB005',
            'outlet_code': 'system',
            'hospital_code': 'SH001',
            'is_active': True,
            'created_by': 'system',
            'created_date': datetime.datetime.now()
        }
    ]

    for cat in essential_categories:
        existing = hms_db['hospital_category'].find_one({'category_id': cat['category_id'], 'branch_code': 'SHB005'})
        if existing:
            hms_db['hospital_category'].update_one(
                {'_id': existing['_id']},
                {'$set': {
                    'category_name': cat['category_name'],
                    'categoryName': cat['categoryName'],
                    'group': cat['group'],
                    'group_type': cat['group_type'],
                    'is_active': True
                }}
            )
            print(f"Updated essential category: {cat['category_id']} ({cat['category_name']})")
        else:
            hms_db['hospital_category'].insert_one(cat)
            print(f"Inserted essential category: {cat['category_id']} ({cat['category_name']})")

    # 5. FIX MISMATCHED ITEM RECORDS in hospital_itemmaster
    print("\n--- 5. Harmonizing item records in hospital_itemmaster ---")
    # Fix the 2 cloth cover items in GRP00028 (STATIONERY) to use CAT00157 (COVER ITEM) instead of CAT00174 (CLOTH)
    res1 = hms_db['hospital_itemmaster'].update_many(
        {'category': 'CAT00174', 'group': 'GRP00028'},
        {'$set': {'category': 'CAT00157'}}
    )
    print(f"Updated {res1.modified_count} stationery envelope covers from CAT00174 to CAT00157.")

    # Fix battery items in GRP00031 (ELECTRICAL GOODS) that had CAT00178 (pharmacy .SPRAY) to CAT00224 (TAB/BATTERY)
    res2 = hms_db['hospital_itemmaster'].update_many(
        {'category': 'CAT00178', 'group': 'GRP00031'},
        {'$set': {'category': 'CAT00224'}}
    )
    print(f"Updated {res2.modified_count} electrical battery items from CAT00178 to CAT00224.")

    # Fix A4 sheet paper that had CAT00142 (OINEMENT) in GRP00028 (STATIONERY) to CAT00197 (PAPER ITEMS)
    res3 = hms_db['hospital_itemmaster'].update_many(
        {'itemName': {'$regex': 'A4 SHEET', '$options': 'i'}, 'category': 'CAT00142', 'group': 'GRP00028'},
        {'$set': {'category': 'CAT00197'}}
    )
    print(f"Updated {res3.modified_count} A4 sheet stationery item to CAT00197.")

    # Fix ANT CHALK that had CAT00208 (SYRUP) in GRP00032 (HOUSE KEEPING) to CAT00172 (LIQUID/CHEMICAL ITEMS)
    res4 = hms_db['hospital_itemmaster'].update_many(
        {'itemName': {'$regex': 'ANT CHALK', '$options': 'i'}, 'category': 'CAT00208', 'group': 'GRP00032'},
        {'$set': {'category': 'CAT00172'}}
    )
    print(f"Updated {res4.modified_count} ANT CHALK item to CAT00172.")

    # Fix LIQUID GUM 150ML in GRP00028 (STATIONERY) that had CAT00143 (INJECTION) to CAT00044 (FEVISTICK)
    res5 = hms_db['hospital_itemmaster'].update_many(
        {'itemName': {'$regex': 'LIQUID GUM', '$options': 'i'}, 'category': 'CAT00143', 'group': 'GRP00028'},
        {'$set': {'category': 'CAT00044'}}
    )
    print(f"Updated {res5.modified_count} LIQUID GUM item to CAT00044.")

    # Fix ID CARD CLIP in GRP00028 (STATIONERY) that had CAT00071 (GENERAL ITEM) to CAT00051 (CLIP)
    res6 = hms_db['hospital_itemmaster'].update_many(
        {'itemName': {'$regex': 'ID CARD CLIP', '$options': 'i'}, 'category': 'CAT00071', 'group': 'GRP00028'},
        {'$set': {'category': 'CAT00051'}}
    )
    print(f"Updated {res6.modified_count} ID CARD CLIP item to CAT00051.")

    # Fix HOUSE KEEPING GLOVES in GRP00032 (HOUSE KEEPING) that had CAT00071 (GENERAL ITEM) to CAT00183 (GLOVES)
    res7 = hms_db['hospital_itemmaster'].update_many(
        {'itemName': {'$regex': 'HOUSE KEEPING.*GLOVES', '$options': 'i'}, 'category': 'CAT00071', 'group': 'GRP00032'},
        {'$set': {'category': 'CAT00183'}}
    )
    print(f"Updated {res7.modified_count} HOUSE KEEPING GLOVES item to CAT00183.")

    # Fix ORIGAMI HAND WASH in GRP00015 (LAB REAGENTS) that had CAT00172 (LIQUID ITEMS): set group to GRP00032 (HOUSE KEEPING)
    res8 = hms_db['hospital_itemmaster'].update_many(
        {'itemName': {'$regex': 'ORIGAMI.*HAND WASH', '$options': 'i'}, 'category': 'CAT00172', 'group': 'GRP00015'},
        {'$set': {'group': 'GRP00032'}}
    )
    print(f"Updated {res8.modified_count} HAND WASH item group to GRP00032.")

    # Fix remaining 20 mismatched items
    # Plumbing fixtures with CAT00106 -> CAT00239
    hms_db['hospital_itemmaster'].update_many(
        {'item_id': {'$in': ['ITM26270065085', 'ITM26270065107', 'ITM26270065108', 'ITM26270065111']}},
        {'$set': {'category': 'CAT00239'}}
    )
    # DUSTER & TC BOOK in Stationery
    hms_db['hospital_itemmaster'].update_one({'item_id': 'ITM26270065136'}, {'$set': {'category': 'CAT00039'}})
    hms_db['hospital_itemmaster'].update_one({'item_id': 'ITM26270065727'}, {'$set': {'category': 'CAT00056'}})
    # Cath Lab items incorrectly marked
    hms_db['hospital_itemmaster'].update_one({'item_id': 'ITM26270065458'}, {'$set': {'category': 'CAT00288'}})
    hms_db['hospital_itemmaster'].update_one({'item_id': 'ITM26270065824'}, {'$set': {'category': 'CAT00288'}})
    hms_db['hospital_itemmaster'].update_one({'item_id': 'ITM26270065884'}, {'$set': {'category': 'CAT00288'}})
    # Light and sockets in Electrical Goods
    hms_db['hospital_itemmaster'].update_one({'item_id': 'ITM26270071462'}, {'$set': {'category': 'CAT00231'}})
    hms_db['hospital_itemmaster'].update_one({'item_id': 'ITM26270071632'}, {'$set': {'category': 'CAT00241'}})
    hms_db['hospital_itemmaster'].update_one({'item_id': 'ITM26270071633'}, {'$set': {'category': 'CAT00241'}})
    # Electrical items with IP Pharmacy CAT00293 or General CAT00071 -> CAT00199
    hms_db['hospital_itemmaster'].update_many(
        {'item_id': {'$in': ['ITM26270064982', 'ITM26270065573', 'ITM26270071382', 'ITM26270071465', 'ITM26270071467']}},
        {'$set': {'category': 'CAT00199'}}
    )
    # Robotic Da Vinci Console
    hms_db['hospital_itemmaster'].update_one({'item_id': 'ITM26270065607'}, {'$set': {'group': 'GRP00074', 'category': 'CAT00318'}})
    # Dental Ultrasonic Scaler
    hms_db['hospital_itemmaster'].update_one({'item_id': 'ITM26270071908'}, {'$set': {'group': 'GRP00047', 'category': 'CAT00234'}})
    # Ligasure surgical consumable in General Items
    hms_db['hospital_itemmaster'].update_one({'item_id': 'ITM26270071458'}, {'$set': {'group': 'GRP00029', 'category': 'CAT00071'}})
    print("Harmonized 20 specific mismatched items.")


    # 6. VERIFY FINAL ALIGNMENT
    print("\n--- 6. VERIFYING FINAL ALIGNMENT ---")
    cat_to_grp = {c.get('category_id'): c.get('group') for c in hms_db['hospital_category'].find() if c.get('category_id')}
    
    total_items = 0
    matched_items = 0
    unmatched_items = 0
    missing_cat_items = 0

    for it in hms_db['hospital_itemmaster'].find({'is_active': True}):
        total_items += 1
        c_id = it.get('category')
        g_id = it.get('group')
        if not c_id:
            continue
        if c_id not in cat_to_grp:
            missing_cat_items += 1
        elif cat_to_grp[c_id] == g_id:
            matched_items += 1
        else:
            unmatched_items += 1

    print(f"Total active items: {total_items}")
    print(f"Perfectly matched items: {matched_items} ({matched_items/total_items*100:.1f}%)")
    print(f"Unmatched items remaining: {unmatched_items}")
    print(f"Missing category items: {missing_cat_items}")
    print("\n=== MIGRATION COMPLETED SUCCESSFULLY ===")

if __name__ == '__main__':
    run_migration()
