PAGE_MAPPING = {
    r'^/_b_a_c_k_e_n_d/HMS/create/?(\?.*)?$': 'HMS-P-AIN',
    '/_b_a_c_k_e_n_d/HMS/patients/register/': 'HMS-P-AIN',
    r'^/_b_a_c_k_e_n_d/HMS/get-reference-doctors/?(\?.*)?$': 'HMS-P-AIN',
    r'^/_b_a_c_k_e_n_d/HMS/patient-registration-stats/?(\?.*)?$': 'HMS-P-AIN',
    '/_b_a_c_k_e_n_d/HMS/get-last-uhid/': 'HMS-P-AIN',
    r'^/_b_a_c_k_e_n_d/HMS/insurance-providers/?(\?.*)?$': 'HMS-P-AIN',



    
    r'^/_b_a_c_k_e_n_d/HMS/get-sidebar-mapping/?(\?.*)?$': 'HMS-P-SB',
    # ==================== WARD REQUEST ====================
    r'^/_b_a_c_k_e_n_d/HMS/save_medicine_ward_request/?(\?.*)?$': 'HMS-P-WR',
    r'^/_b_a_c_k_e_n_d/HMS/update_medicine_ward_request/?(\?.*)?$': 'HMS-P-WR',
    r'^/_b_a_c_k_e_n_d/HMS/get_medicine_ward_requests/?(\?.*)?$': 'HMS-P-WR',


    # ==================== DIET ====================
    r'^/_b_a_c_k_e_n_d/HMS/get_diet_orders/?(\?.*)?$': 'HMS-P-DO',
    r'^/_b_a_c_k_e_n_d/HMS/get_all_diet_orders/?(\?.*)?$': 'HMS-P-DO',
    r'^/_b_a_c_k_e_n_d/HMS/get_diet_master/?(\?.*)?$': 'HMS-P-DO',
    r'^/_b_a_c_k_e_n_d/HMS/save_diet_master/?(\?.*)?$': 'HMS-P-DO',
    r'^/_b_a_c_k_e_n_d/HMS/save_diet_order/?(\?.*)?$': 'HMS-P-DO',
    r'^/_b_a_c_k_e_n_d/HMS/update_diet_status/?(\?.*)?$': 'HMS-P-DO',
    r'^/_b_a_c_k_e_n_d/HMS/save_diet_extra_master/?(\?.*)?$': 'HMS-P-DO',
    r'^/_b_a_c_k_e_n_d/HMS/get_diet_extra_master/?(\?.*)?$': 'HMS-P-DO',
    r'^/_b_a_c_k_e_n_d/HMS/update_diet_extra_master/?(\?.*)?$': 'HMS-P-DO',
    

    


    # ==================== ROOMS ====================
    r'^/_b_a_c_k_e_n_d/HMS/block/?(\?.*)?$': 'HMS-P-BLK',
    r'^/_b_a_c_k_e_n_d/HMS/block/[0-9]+/?(\?.*)?$': 'HMS-P-BLKD',

    r'^/_b_a_c_k_e_n_d/HMS/room-category/?(\?.*)?$': 'HMS-P-RCAT',
    r'^/_b_a_c_k_e_n_d/HMS/room-category/[^/]+/?(\?.*)?$': 'HMS-P-RCATD',

    r'^/_b_a_c_k_e_n_d/HMS/room/?(\?.*)?$': 'HMS-P-RM',
    r'^/_b_a_c_k_e_n_d/HMS/room/[^/]+/?(\?.*)?$': 'HMS-P-RMD',

    r'^/_b_a_c_k_e_n_d/HMS/nursingstation/?(\?.*)?$': 'HMS-P-NS',
    r'^/_b_a_c_k_e_n_d/HMS/nursingstation/[^/]+/?(\?.*)?$': 'HMS-P-NSD',

    r'^/_b_a_c_k_e_n_d/HMS/roomservice-description/?(\?.*)?$': 'HMS-P-RSD',
    r'^/_b_a_c_k_e_n_d/HMS/roomservice-description/[^/]+/?(\?.*)?$': 'HMS-P-RSDD',

    r'^/_b_a_c_k_e_n_d/HMS/room-kititems/?(\?.*)?$': 'HMS-P-RKIT',
    r'^/_b_a_c_k_e_n_d/HMS/room-kititems/[^/]+/?(\?.*)?$': 'HMS-P-RKITD',

    r'^/_b_a_c_k_e_n_d/HMS/room-enquiry/?(\?.*)?$': 'HMS-P-RENQ',
    r'^/_b_a_c_k_e_n_d/HMS/update-room-cleaned/?(\?.*)?$': 'HMS-P-RCLN',
    r'^/_b_a_c_k_e_n_d/HMS/book-room/?(\?.*)?$': 'HMS-P-BROOM',

    r'^/_b_a_c_k_e_n_d/HMS/get_active_admission/?(\?.*)?$': 'HMS-P-GADM',
    r'^/_b_a_c_k_e_n_d/HMS/room-shifting/?(\?.*)?$': 'HMS-P-RSHFT',
    r'^/_b_a_c_k_e_n_d/HMS/room-shifting/.+/update/?(\?.*)?$': 'HMS-P-RSHFTD',

    # ==================== ADMISSION ====================
    r'^/_b_a_c_k_e_n_d/HMS/autoipNumber/?(\?.*)?$': 'HMS-P-AIN',
    r'^/_b_a_c_k_e_n_d/HMS/admission-list/?(\?.*)?$': 'HMS-P-ADML',
    r'^/_b_a_c_k_e_n_d/HMS/admission-detail/.+/?(\?.*)?$': 'HMS-P-ADMD',
    r'^/_b_a_c_k_e_n_d/HMS/admission-room-search/?(\?.*)?$': 'HMS-P-SRM',
    r'^/_b_a_c_k_e_n_d/HMS/admission-advance/.+/?(\?.*)?$': 'HMS-P-AA',

    # ==================== INVENTORY ====================
    r'^/_b_a_c_k_e_n_d/HMS/pharmacy-category/?(\?.*)?$': 'HMS-P-PC',
    r'^/_b_a_c_k_e_n_d/HMS/pharmacy-category/[^/]+/?(\?.*)?$': 'HMS-P-PCD',

    r'^/_b_a_c_k_e_n_d/HMS/chemical-composition/?(\?.*)?$': 'HMS-P-CC',
    r'^/_b_a_c_k_e_n_d/HMS/chemical-composition/[^/]+/?(\?.*)?$': 'HMS-P-CCD',

    r'^/_b_a_c_k_e_n_d/HMS/vendors/?$': 'HMS-P-VND',
    r'^/_b_a_c_k_e_n_d/HMS/vendors/[0-9]+/?(\?.*)?$': 'HMS-P-VNDD',

    r'^/_b_a_c_k_e_n_d/HMS/pharmacy-items/?(\?.*)?$': 'HMS-P-PI',
    r'^/_b_a_c_k_e_n_d/HMS/pharmacy-items/[^/]+/?(\?.*)?$': 'HMS-P-PID',

    '/_b_a_c_k_e_n_d/HMS/grn/': 'HMS-P-GRN',
    r'^/_b_a_c_k_e_n_d/HMS/grn(?:/[^/]+)+/$': 'HMS-P-GRNA',

    r'^/_b_a_c_k_e_n_d/HMS/pharmacy_stock_history/?(\?.*)?$': 'HMS-P-GRN',

    # ==================== PHARMACY STOCK ====================
    r'^/_b_a_c_k_e_n_d/HMS/ip-pharmacy-stock/?(\?.*)?$': 'HMS-P-IPPS',
    r'^/_b_a_c_k_e_n_d/HMS/ip-pharmacy-stock/[^/]+/?(\?.*)?$': 'HMS-P-IPPSD',
    r'^/_b_a_c_k_e_n_d/HMS/op-pharmacy-stock/?(\?.*)?$': 'HMS-P-OPPS',
    r'^/_b_a_c_k_e_n_d/HMS/op-pharmacy-stock/[^/]+/?(\?.*)?$': 'HMS-P-OPPSD',

    # ==================== GRN ====================
    r'^/_b_a_c_k_e_n_d/HMS/ip-grn/?(\?.*)?$': 'HMS-P-IPGRN',
    r'^/_b_a_c_k_e_n_d/HMS/ip-grn/[^/]+/?(\?.*)?$': 'HMS-P-IPGRND',
    r'^/_b_a_c_k_e_n_d/HMS/op-grn/?(\?.*)?$': 'HMS-P-OPGRN',
    r'^/_b_a_c_k_e_n_d/HMS/op-grn/[^/]+/?(\?.*)?$': 'HMS-P-OPGRND',


    # ==================== DISCHARGE ====================
    r'^/_b_a_c_k_e_n_d/HMS/search-admissions/?(\?.*)?$': 'HMS-P-SADM',
    r'^/_b_a_c_k_e_n_d/HMS/discharge/?(\?.*)?$': 'HMS-P-DIS',
    r'^/_b_a_c_k_e_n_d/HMS/search-discharge-patient/?(\?.*)?$': 'HMS-P-SADM',
    '^/_b_a_c_k_e_n_d/HMS/create_dialysis_discharge_summary/': 'HMS-P-CDDS',
    r'^/_b_a_c_k_e_n_d/HMS/Print_dialysis_dischargesummary/?(\?.*)?$': 'HMS-P-PDDS',

    # ==================== NURSING ====================
    r'^/_b_a_c_k_e_n_d/HMS/admission-by-uhid/[^/]+/?(\?.*)?$': 'HMS-P-AUHID',
    r'^/_b_a_c_k_e_n_d/HMS/admission-by-ip/[^/]+/?(\?.*)?$': 'HMS-P-AIP',

     #Investigation Billing:
    r'^/_b_a_c_k_e_n_d/HMS/op-patient(?:/[^/]+)+/$': 'HMS-API-UHID',                 
    r'^/_b_a_c_k_e_n_d/HMS/ip-patient(?:/[^/]+)+/$': 'HMS-P-IB',                 
    '/_b_a_c_k_e_n_d/HMS/doctor_list/': 'HMS-P-IB',                 
    '/_b_a_c_k_e_n_d/HMS/bill-types/': 'HMS-P-IB',                 
    '/_b_a_c_k_e_n_d/HMS/packages/': 'HMS-API-PACK',                 
    r'^/_b_a_c_k_e_n_d/HMS/package-items/?(\?.*)?$': 'HMS-P-IB',                 
    r'^/_b_a_c_k_e_n_d/HMS/investigation-items/?(\?.*)?$': 'HMS-P-IB',       
    '/_b_a_c_k_e_n_d/HMS/investBilling/': 'HMS-P-IB',                 
    r'^/_b_a_c_k_e_n_d/HMS/investBillingGet/?(\?.*)?$': 'HMS-P-IB',                 
    '/_b_a_c_k_e_n_d/HMS/estimateBilling/': 'HMS-P-IB',                 
    r'^/_b_a_c_k_e_n_d/HMS/get-estimate-billings/?(\?.*)?$': 'HMS-P-IB',                 
    '/_b_a_c_k_e_n_d/HMS/delete-bill/': 'HMS-P-IB',       

    #Investigation Reports (RD):
    r'^/_b_a_c_k_e_n_d/HMS/investigations/?(\?.*)?$': 'HMS-API-RD',                
    '/_b_a_c_k_e_n_d/HMS/scan-reports/': 'HMS-API-RD',                 
    r'^/_b_a_c_k_e_n_d/HMS/scan_reports/?(\?.*)?$': 'HMS-API-RD',                 
    r'^/_b_a_c_k_e_n_d/HMS/scan_reports(?:/[^/]+)+/$': 'HMS-API-RD',                 
    r'^/_b_a_c_k_e_n_d/HMS/scan-reports/approve(?:/[^/]+)+/$': 'HMS-API-RDA',                 
    r'^/_b_a_c_k_e_n_d/HMS/scan-reports/delete(?:/[^/]+)+/$': 'HMS-API-RDD',  
    r'^/_b_a_c_k_e_n_d/HMS/scan-reports/edit(?:/[^/]+)+/$': 'HMS-API-RDE',  
    r'^/_b_a_c_k_e_n_d/HMS/employee-signature/?(\?.*)?$': 'HMS-API-RD',  

    #Summary:    
    r'^/_b_a_c_k_e_n_d/HMS/summaries/?(\?.*)?$': 'HMS-P-SUM',                  
    '/_b_a_c_k_e_n_d/HMS/summary-type/': 'HMS-P-SUM',                  
    '/_b_a_c_k_e_n_d/HMS/summaries/create/': 'HMS-P-SUM',                  
    r'^/_b_a_c_k_e_n_d/HMS/approve-summary(?:/[^/]+)+/$': 'HMS-P-SUMA',                  
    r'^/_b_a_c_k_e_n_d/HMS/delete-summary(?:/[^/]+)+/$': 'HMS-P-SUMD',                  
    r'^/_b_a_c_k_e_n_d/HMS/get-editsummary(?:/[^/]+)+/$': 'HMS-P-SUM',                  
    r'^/_b_a_c_k_e_n_d/HMS/update-summary(?:/[^/]+)+/$': 'HMS-P-SUME',                  
    r'^/_b_a_c_k_e_n_d/HMS/patient-investigations(?:/[^/]+)+/$': 'HMS-P-SUM', 
    r'^/_b_a_c_k_e_n_d/HMS/get-printsummary(?:/[^/]+)+/$': 'HMS-P-SUM',                  

    #Doctor Master: 
    '/_b_a_c_k_e_n_d/HMS/doctor_list_diagnostics/': 'HMS-API-DLD',                  
    '/_b_a_c_k_e_n_d/HMS/doctor_schedule/': 'HMS-P-DRM',                  
    r'^/_b_a_c_k_e_n_d/HMS/doctor_schedule_upsert(?:/[^/]+)+/$': 'HMS-P-DRM',   
    r'^/_b_a_c_k_e_n_d/HMS/doctor-report/?.*': 'HMS-API-DLD',   

    #Package Master:
    '/_b_a_c_k_e_n_d/HMS/investigation-prices/': 'HMS-P-IPKG',                  
    '/_b_a_c_k_e_n_d/HMS/lab-items/': 'HMS-P-IPKG',                  
    '/_b_a_c_k_e_n_d/HMS/departments/': 'HMS-P-IPKG',                  
    '/_b_a_c_k_e_n_d/HMS/packages_crud/': 'HMS-P-IPKG',                  
    '/_b_a_c_k_e_n_d/HMS/packages/create/': 'HMS-P-IPKG',                  
    r'^/_b_a_c_k_e_n_d/HMS/bill-types(?:/[^/]+)+/$': 'HMS-P-IPKG',                  
    r'^/_b_a_c_k_e_n_d/HMS/bill-types/update(?:/[^/]+)+/$': 'HMS-P-IPKGE',                  
    r'^/_b_a_c_k_e_n_d/HMS/bill-types/delete(?:/[^/]+)+/$': 'HMS-P-IPKGD',     

    #Bill Type Master:
    '/_b_a_c_k_e_n_d/HMS/bill-types_get/': 'HMS-P-BT',                  
    '/_b_a_c_k_e_n_d/HMS/bill-types/create/': 'HMS-P-BT',                  
    '/_b_a_c_k_e_n_d/HMS/investigation-price/patch-bill-type/': 'HMS-P-BT',       
    r'^/_b_a_c_k_e_n_d/HMS/bill-types_get/?(\?.*)?$': 'HMS-P-BT',                  
    r'^/_b_a_c_k_e_n_d/HMS/bill-types/update(?:/[^/]+)+/$': 'HMS-P-BTE',                  
    r'^/_b_a_c_k_e_n_d/HMS/bill-types/delete(?:/[^/]+)+/$': 'HMS-P-BTD',                  

    #Investigation Prices:
    '/_b_a_c_k_e_n_d/HMS/investigation-prices_get/': 'HMS-P-IP',                  
    '/_b_a_c_k_e_n_d/HMS/investigation-prices/create/': 'HMS-P-IP',                        
    r'^/_b_a_c_k_e_n_d/HMS/investigation-prices/update(?:/[^/]+)+/$': 'HMS-P-IPE',                  
    r'^/_b_a_c_k_e_n_d/HMS/investigation-prices/delete(?:/[^/]+)+/$': 'HMS-P-IPD',  

    #Report:
    r'^/_b_a_c_k_e_n_d/HMS/dept-budr/?(\?.*)?$': 'HMS-P-DBUDR',   

    #Velavan Items:
    '/_b_a_c_k_e_n_d/HMS/velavan_items/list/': 'HMS-P-VI',               
    '/_b_a_c_k_e_n_d/HMS/velavan_create_item/': 'HMS-P-VI',               
    '/_b_a_c_k_e_n_d/HMS/velavan_get_items/': 'HMS-P-VI',               
    r'^/_b_a_c_k_e_n_d/HMS/velavan_update_item(?:/[^/]+)+/$': 'HMS-P-VIE',               
    r'^/_b_a_c_k_e_n_d/HMS/velavan_delete_item(?:/[^/]+)+/$': 'HMS-P-VID',               

    #Velavan Vendors:
    '/_b_a_c_k_e_n_d/HMS/velavan_vendors/list/': 'HMS-P-VV', 
    '/_b_a_c_k_e_n_d/HMS/velavan_create_vendor/': 'HMS-P-VV',               
    '/_b_a_c_k_e_n_d/HMS/velavan_get_vendors/': 'HMS-P-VV',               
    r'^/_b_a_c_k_e_n_d/HMS/velavan_update_vendor(?:/[^/]+)+/$': 'HMS-P-VVE',               
    r'^/_b_a_c_k_e_n_d/HMS/velavan_delete_vendor(?:/[^/]+)+/$': 'HMS-P-VVD',  

    #Velavan Invoices:
    '/_b_a_c_k_e_n_d/HMS/velavan/invoices/': 'HMS-P-VIN',        
    r'^/_b_a_c_k_e_n_d/HMS/velavan/invoices/list/?(\?.*)?$': 'HMS-P-VINR',        
    r'^/_b_a_c_k_e_n_d/HMS/velavan/previous-purchases/?(\?.*)?$': 'HMS-P-VINR',  
    r'^/_b_a_c_k_e_n_d/HMS/velavan/invoices/update(?:/[^/]+)+/$': 'HMS-P-VINE',     
    r'^/_b_a_c_k_e_n_d/HMS/velavan/invoices/approve(?:/[^/]+)+/$': 'HMS-P-VINA',     

    #OT Master:
    '/_b_a_c_k_e_n_d/HMS/create_ot/': 'HMS-P-OTM',               
    '/_b_a_c_k_e_n_d/HMS/list_ots/': 'HMS-P-OTM',                  
    r'^/_b_a_c_k_e_n_d/HMS/update_ot(?:/[^/]+)+/$': 'HMS-P-OTME',               
    r'^/_b_a_c_k_e_n_d/HMS/delete_ot(?:/[^/]+)+/$': 'HMS-P-OTMD',  

    #Anesthesia Master:
    '/_b_a_c_k_e_n_d/HMS/create_anes/': 'HMS-P-AM',               
    '/_b_a_c_k_e_n_d/HMS/list_anes/': 'HMS-P-AM',                  
    r'^/_b_a_c_k_e_n_d/HMS/update_anes(?:/[^/]+)+/$': 'HMS-P-AME',               
    r'^/_b_a_c_k_e_n_d/HMS/delete_anes(?:/[^/]+)+/$': 'HMS-P-AMD', 

    #Surgery Schedule:
    '/_b_a_c_k_e_n_d/HMS/create_surgery_schedule/': 'HMS-P-OTSS',               
    r'^/_b_a_c_k_e_n_d/HMS/list_surgery_schedules/?(\?.*)?$': 'HMS-P-OTSS',                
    '/_b_a_c_k_e_n_d/HMS/get_surgery_schedule/': 'HMS-P-OTSS',                
    '/_b_a_c_k_e_n_d/HMS/update_surgery_schedule/': 'HMS-P-OTSSU',                
    '/_b_a_c_k_e_n_d/HMS/cancel_surgery_schedule/': 'HMS-P-OTSSD',                
    '/_b_a_c_k_e_n_d/HMS/update_schedule_status/': 'HMS-P-OTSSA',                
    '/_b_a_c_k_e_n_d/HMS/list_diagnosis/': 'HMS-P-OTSS',                
    r'^/_b_a_c_k_e_n_d/HMS/get_ot_medicine_ward_requests/?(\?.*)?$': 'HMS-P-OTMB',                
    r'^/_b_a_c_k_e_n_d/HMS/update_ot_medicine_ward_request/?(\?.*)?$': 'HMS-P-OTMBE',                
    r'^/_b_a_c_k_e_n_d/HMS/delete_ot_medicine_ward_request/?(\?.*)?$': 'HMS-P-OTMBD',                
    r'^/_b_a_c_k_e_n_d/HMS/get_ippharmacy_stock/?(\?.*)?$': 'HMS-P-OTMB',  
    '/_b_a_c_k_e_n_d/HMS/save_ot_medicine_ward_request/': 'HMS-P-OTMB',    

    #Assets Management:
    '/_b_a_c_k_e_n_d/HMS/item-master/': 'HMS-API-IT',
    '/_b_a_c_k_e_n_d/HMS/item-master/price-history/': 'HMS-API-IT',
    '/_b_a_c_k_e_n_d/HMS/item-master/.*/': 'HMS-API-IT',
    '/_b_a_c_k_e_n_d/HMS/department-master/': 'HMS-API-IT',
    '/_b_a_c_k_e_n_d/HMS/department-master/.*/': 'HMS-API-IT',
    '/_b_a_c_k_e_n_d/HMS/group-master/': 'HMS-API-IT',
    '/_b_a_c_k_e_n_d/HMS/group-master/.*/': 'HMS-API-IT',
    '/_b_a_c_k_e_n_d/HMS/category-master/': 'HMS-API-IT',
    '/_b_a_c_k_e_n_d/HMS/category-master/.*/': 'HMS-API-IT',
    '/_b_a_c_k_e_n_d/HMS/group-type-master/': 'HMS-API-IT',
    '/_b_a_c_k_e_n_d/HMS/group-type-master/.*/': 'HMS-API-IT',

    # Stores GRN:
    '/_b_a_c_k_e_n_d/HMS/stores-grn/': 'HMS-P-SGRN',
    '/_b_a_c_k_e_n_d/HMS/stores-grn/.*/': 'HMS-P-SGRN',

    # Stores Intent:
    '/_b_a_c_k_e_n_d/HMS/stores-intent/': 'HMS-API-SINTENT',
    '/_b_a_c_k_e_n_d/HMS/stores-intent/create/': 'HMS-API-SINTENT',
    '/_b_a_c_k_e_n_d/HMS/stores-intent/update/.*/': 'HMS-API-SINTENT',
    '/_b_a_c_k_e_n_d/HMS/stores-intent/delete/.*/': 'HMS-API-SINTENTA',
    
    # Stores Assets Management:
    '/_b_a_c_k_e_n_d/HMS/stores-assets-management/': 'HMS-API-SAM',               
    r'^/_b_a_c_k_e_n_d/HMS/stores-assets-management/[^/]+/?(\?.*)?$': 'HMS-API-SAM',
    '/_b_a_c_k_e_n_d/HMS/stores-assets-management/.*/': 'HMS-API-SAM',

    # Stores Assets Maintenance:
    '/_b_a_c_k_e_n_d/HMS/stores-assets-maintenance/': 'HMS-API-SAMT',               
    r'^/_b_a_c_k_e_n_d/HMS/stores-assets-maintenance/[^/]+/?(\?.*)?$': 'HMS-API-SAMT',
    '/_b_a_c_k_e_n_d/HMS/stores-assets-maintenance/.*/': 'HMS-API-SAMT',

    #Recycle Assets Management:
    '/_b_a_c_k_e_n_d/HMS/recycle_asset/': 'HMS-API-SRM',               
    r'^/_b_a_c_k_e_n_d/HMS/recycle_asset/[^/]+/?(\?.*)?$': 'HMS-API-SRM',               
    '/_b_a_c_k_e_n_d/HMS/recycle_asset/.*/': 'HMS-API-SRM',   



    # PHARMACY 
         r'^/_b_a_c_k_e_n_d/HMS/patient_details/[^/]+/?(\?.*)?$': 'HMS-P-PPD',  
        '/_b_a_c_k_e_n_d/HMS/get_pharmacy_stock/': 'HMS-P-PGS',
        '/_b_a_c_k_e_n_d/HMS/save_pharmacy_bill/': 'HMS-P-PSOPB',
        '/_b_a_c_k_e_n_d/HMS/get_pharmacy_BillType/': 'HMS-P-PGPBT',
        '/_b_a_c_k_e_n_d/HMS/get_estimate_bills/': 'HMS-P-PGEB',
        '/_b_a_c_k_e_n_d/HMS/get_last_billed_uhid/': 'HMS-P-PGLBU',
        '/_b_a_c_k_e_n_d/HMS/cashcounter_pending_bills/': 'HMS-P-CCOPPB',

         '/_b_a_c_k_e_n_d/HMS/collect_oppharmacy_payment/': 'HMS-P-PCOPP',
         '/_b_a_c_k_e_n_d/HMS/pharmacy_deletebill/': 'HMS-P-POPPDB',
         '/_b_a_c_k_e_n_d/HMS/pharmacy_medicinechart/': 'HMS-P-PMC',
         '/_b_a_c_k_e_n_d/HMS/substitute_medicine/': 'HMS-P-PSM',
         '/_b_a_c_k_e_n_d/HMS/convert_to_bill/': 'HMS-P-PCB',
         '/_b_a_c_k_e_n_d/HMS/finalize_bill/': 'HMS-P-PFB',
         r'^/_b_a_c_k_e_n_d/HMS/searchby_ip/?(\?.*)?$': 'HMS-P-PSIP',
         '/_b_a_c_k_e_n_d/HMS/ipadvance_bills/': 'HMS-P-CCC',
          '/_b_a_c_k_e_n_d/HMS/pharmacy_view_bills/': 'HMS-P-PHVSB',

         r'/_b_a_c_k_e_n_d/HMS/admissionstatus/?(\?.*)?$': 'HMS-P-POPUAS',
         '/_b_a_c_k_e_n_d/HMS/salesreturn_get_patientdetails/': 'HMS-P-SRGPD',
         '/_b_a_c_k_e_n_d/HMS/get_salesreturn_billdetails/': 'HMS-P-SRBD',
         '/_b_a_c_k_e_n_d/HMS/OP_salesreturn_billdetails/': 'HMS-P-OPSRBD',
          '/_b_a_c_k_e_n_d/HMS/get_salesreturn_details/': 'HMS-P-OPGSRD',

        # Central cah counter

        '/_b_a_c_k_e_n_d/HMS/get_active_shift/'         : 'HMS-P-CCGAS',
        '/_b_a_c_k_e_n_d/HMS/cash_counter_shiftdetails/': 'HMS-P-CCSTSD',
  
        '/_b_a_c_k_e_n_d/HMS/cash_counter/': 'HMS-P-CCC',
        '/_b_a_c_k_e_n_d/HMS/cash_counter_manager/': 'HMS-P-CCC',
  
        '/_b_a_c_k_e_n_d/HMS/get_active_account_heads/': 'HMS-P-CCGAH',
        '/_b_a_c_k_e_n_d/HMS/post_receipt_payments/': 'HMS-P-CCMBPB',
        '/_b_a_c_k_e_n_d/HMS/get_receipt_payments/': 'HMS-P-CCMBPB',
        '/_b_a_c_k_e_n_d/HMS/get_mainblock_pendingbills/': 'HMS-P-CCMBPB',
        '/_b_a_c_k_e_n_d/HMS/update_mainblock_pendingbills/': 'HMS-P-CCUPB',
         
        '/_b_a_c_k_e_n_d/HMS/shift_basis_accounts_report/' : 'HMS-P-CCC',
        '/_b_a_c_k_e_n_d/HMS/bill_wise_report/' : 'HMS-P-CCC',
        '/_b_a_c_k_e_n_d/HMS/get_return_bills/' : 'HMS-P-CCGRB',
        '/_b_a_c_k_e_n_d/HMS/collectpayment_return_bills/' :'HMS-P-CCCRB',
             
}


PAGE_ACTION_MAPPING = {
    'xxx': {
        'DELETE':'RWD',
    },
}

GEN_ACTION_MAPPING = {
    'POST': 'RW',
    'PUT': 'RW',
    'PATCH': 'RW',
    'DELETE': 'RW',
    'GET': 'R',
}



