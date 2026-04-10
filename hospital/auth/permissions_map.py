PAGE_MAPPING = {

    r'^/_b_a_c_k_e_n_d/HMS/create/?(\?.*)?$': 'HMS-P-AIN',
    '/_b_a_c_k_e_n_d/HMS/patients/register/': 'HMS-P-AIN',
    r'^/_b_a_c_k_e_n_d/HMS/get-reference-doctors/?(\?.*)?$': 'HMS-P-AIN',
    r'^/_b_a_c_k_e_n_d/HMS/patient-registration-stats/?(\?.*)?$': 'HMS-P-AIN',
    '/_b_a_c_k_e_n_d/HMS/get-last-uhid/': 'HMS-P-AIN',
    r'^/_b_a_c_k_e_n_d/HMS/insurance-providers/?(\?.*)?$': 'HMS-P-AIN',
    r'^/_b_a_c_k_e_n_d/HMS/get-sidebar-mapping/?(\?.*)?$': 'HMS-P-AIN',


    # ==================== ADMISSION ====================
    r'^/_b_a_c_k_e_n_d/HMS/autoipNumber/?(\?.*)?$': 'HMS-P-AIN',
    r'^/_b_a_c_k_e_n_d/HMS/admission/?(\?.*)?$': 'HMS-P-ADM',
    r'^/_b_a_c_k_e_n_d/HMS/search-rooms/?(\?.*)?$': 'HMS-P-SRM',

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

    # ==================== VENDOR ====================
    r'^/_b_a_c_k_e_n_d/HMS/vendor/?(\?.*)?$': 'HMS-P-VND',
    r'^/_b_a_c_k_e_n_d/HMS/vendor/[^/]+/?(\?.*)?$': 'HMS-P-VNDD',


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

    # ==================== DISCHARGE ====================
    r'^/_b_a_c_k_e_n_d/HMS/search-admissions/?(\?.*)?$': 'HMS-P-SADM',
    r'^/_b_a_c_k_e_n_d/HMS/discharge/?(\?.*)?$': 'HMS-P-DIS',
    r'^/_b_a_c_k_e_n_d/HMS/search-discharge-patient/?(\?.*)?$': 'HMS-P-SADM',

    # ==================== NURSING ====================
    r'^/_b_a_c_k_e_n_d/HMS/room-shiftings/?(\?.*)?$': 'HMS-P-RSHFT',
    r'^/_b_a_c_k_e_n_d/HMS/admission-by-uhid/[^/]+/?(\?.*)?$': 'HMS-P-AUHID',
    r'^/_b_a_c_k_e_n_d/HMS/admission-by-ip/[^/]+/?(\?.*)?$': 'HMS-P-AIP',

     #Investigation Billing:
    r'^/_b_a_c_k_e_n_d/HMS/op-patient(?:/[^/]+)+/$': 'HMS-P-IB',                 
    r'^/_b_a_c_k_e_n_d/HMS/ip-patient(?:/[^/]+)+/$': 'HMS-P-IB',                 
    '/_b_a_c_k_e_n_d/HMS/doctor_list/': 'HMS-P-IB',                 
    '/_b_a_c_k_e_n_d/HMS/bill-types/': 'HMS-P-IB',                 
    '/_b_a_c_k_e_n_d/HMS/packages/': 'HMS-P-IB',                 
    r'^/_b_a_c_k_e_n_d/HMS/package-items/?(\?.*)?$': 'HMS-P-IB',                 
    r'^/_b_a_c_k_e_n_d/HMS/investigation-items/?(\?.*)?$': 'HMS-P-IB',       
    '/_b_a_c_k_e_n_d/HMS/investBilling/': 'HMS-P-IB',                 
    r'^/_b_a_c_k_e_n_d/HMS/investBillingGet/?(\?.*)?$': 'HMS-P-IB',                 
    '/_b_a_c_k_e_n_d/HMS/estimateBilling/': 'HMS-P-IB',                 
    r'^/_b_a_c_k_e_n_d/HMS/get-estimate-billings/?(\?.*)?$': 'HMS-P-IB',                 
    '/_b_a_c_k_e_n_d/HMS/delete-bill/': 'HMS-P-IB',       

    #Investigation Reports (CT):
    r'^/_b_a_c_k_e_n_d/HMS/investigations/?(\?.*)?$': 'HMS-P-ICT',                
    '/_b_a_c_k_e_n_d/HMS/scan-reports/': 'HMS-P-ICT',                 
    r'^/_b_a_c_k_e_n_d/HMS/scan_reports/?(\?.*)?$': 'HMS-P-ICT',                 
    r'^/_b_a_c_k_e_n_d/HMS/scan_reports(?:/[^/]+)+/$': 'HHMS-P-ICT',                 
    r'^/_b_a_c_k_e_n_d/HMS/scan-reports/approve(?:/[^/]+)+/$': 'HMS-P-ICT',                 
    r'^/_b_a_c_k_e_n_d/HMS/scan-reports/delete(?:/[^/]+)+/$': 'HMS-P-ICT',  
    r'^/_b_a_c_k_e_n_d/HMS/scan-reports/edit(?:/[^/]+)+/$': 'HMS-P-ICT',  

    #Investigation Reports (MRI):
    '/_b_a_c_k_e_n_d/HMS/mri_investigations/': 'HMS-P-IMRI',                 
    '/_b_a_c_k_e_n_d/HMS/mri-reports/': 'HMS-P-IMRI',                 
    '/_b_a_c_k_e_n_d/HMS/mri_reports/': 'HMS-P-IMRI',                 
    r'^/_b_a_c_k_e_n_d/HMS/mri_reports/(?:/[^/]+)+/$': 'HMS-P-IMRI',                 
    r'^/_b_a_c_k_e_n_d/HMS/mri-reports/approve(?:/[^/]+)+/$': 'HMS-P-IMRI',                 
    r'^/_b_a_c_k_e_n_d/HMS/mri-reports/delete(?:/[^/]+)+/$': 'HMS-P-IMRI',                 
    r'^/_b_a_c_k_e_n_d/HMS/mri-reports/edit(?:/[^/]+)+/$': 'HMS-P-IMRI', 

    #Investigation Reports (USG):
    '/_b_a_c_k_e_n_d/HMS/usg_investigations/': 'HMS-P-IUSG',               
    '/_b_a_c_k_e_n_d/HMS/usg-reports/': 'HMS-P-IUSG',                 
    '/_b_a_c_k_e_n_d/HMS/usg_reports/': 'HMS-P-IUSG',                 
    r'^/_b_a_c_k_e_n_d/HMS/usg_reports/(?:/[^/]+)+/$': 'HMS-P-IUSG',                 
    r'^/_b_a_c_k_e_n_d/HMS/usg-reports/approve(?:/[^/]+)+/$': 'HMS-P-IUSG',                 
    r'^/_b_a_c_k_e_n_d/HMS/usg-reports/delete(?:/[^/]+)+/$': 'HMS-P-IUSG',                 
    r'^/_b_a_c_k_e_n_d/HMS/usg-reports/edit(?:/[^/]+)+/$': 'HMS-P-IUSG',  

    #Investigation Reports (X-Ray):
    '/_b_a_c_k_e_n_d/HMS/x_ray_investigations/': 'HMS-P-IXRAY',              
    '/_b_a_c_k_e_n_d/HMS/x_ray-reports/': 'HMS-P-IXRAY',                 
    '/_b_a_c_k_e_n_d/HMS/x_ray_reports/': 'HMS-P-IXRAY',                 
    r'^/_b_a_c_k_e_n_d/HMS/x_ray_reports/(?:/[^/]+)+/$': 'HMS-P-IXRAY',                 
    r'^/_b_a_c_k_e_n_d/HMS/x_ray-reports/approve(?:/[^/]+)+/$': 'HMS-P-IXRAY',                 
    r'^/_b_a_c_k_e_n_d/HMS/x_ray-reports/delete(?:/[^/]+)+/$': 'HMS-P-IXRAY',                 
    r'^/_b_a_c_k_e_n_d/HMS/x_ray-reports/edit(?:/[^/]+)+/$': 'HMS-P-IXRAY',

    #Summary:    
    r'^/_b_a_c_k_e_n_d/HMS/summaries/?(\?.*)?$': 'HMS-P-SUM',                  
    '/_b_a_c_k_e_n_d/HMS/summary-type/': 'HMS-P-SUM',                  
    '/_b_a_c_k_e_n_d/HMS/summaries/create/': 'HMS-P-SUM',                  
    r'^/_b_a_c_k_e_n_d/HMS/approve-summary(?:/[^/]+)+/$': 'HMS-P-SUM',                  
    r'^/_b_a_c_k_e_n_d/HMS/delete-summary(?:/[^/]+)+/$': 'HMS-P-SUM',                  
    r'^/_b_a_c_k_e_n_d/HMS/get-editsummary(?:/[^/]+)+/$': 'HMS-P-SUM',                  
    r'^/_b_a_c_k_e_n_d/HMS/update-summary(?:/[^/]+)+/$': 'HMS-P-SUM',                  
    r'^/_b_a_c_k_e_n_d/HMS/patient-investigations(?:/[^/]+)+/$': 'HMS-P-SUM', 
    r'^/_b_a_c_k_e_n_d/HMS/get-printsummary(?:/[^/]+)+/$': 'HMS-P-SUM',                  

    #Doctor Master: 
    '/_b_a_c_k_e_n_d/HMS/doctor_list_diagnostics/': 'HMS-P-DLD',                  
    r'^/_b_a_c_k_e_n_d/HMS/doctor_schedule(?:/[^/]+)+/$': 'HMS-P-DRM',                  
    r'^/_b_a_c_k_e_n_d/HMS/doctor_schedule_upsert(?:/[^/]+)+/$': 'HMS-P-DRM',   

    #Package Master:
    '/_b_a_c_k_e_n_d/HMS/investigation-prices/': 'HMS-P-IPKG',                  
    '/_b_a_c_k_e_n_d/HMS/lab-items/': 'HMS-P-IPKG',                  
    '/_b_a_c_k_e_n_d/HMS/departments/': 'HMS-P-IPKG',                  
    '/_b_a_c_k_e_n_d/HMS/packages_crud/': 'HMS-P-IPKG',                  
    '/_b_a_c_k_e_n_d/HMS/packages/create/': 'HMS-P-IPKG',                  
    r'^/_b_a_c_k_e_n_d/HMS/bill-types(?:/[^/]+)+/$': 'HMS-P-IPKG',                  
    r'^/_b_a_c_k_e_n_d/HMS/bill-types/update(?:/[^/]+)+/$': 'HMS-P-IPKG',                  
    r'^/_b_a_c_k_e_n_d/HMS/bill-types/delete(?:/[^/]+)+/$': 'HMS-P-IPKG',     

    #Bill Type Master:
    '/_b_a_c_k_e_n_d/HMS/bill-types_get/': 'HMS-P-BT',                  
    '/_b_a_c_k_e_n_d/HMS/bill-types/create/': 'HMS-P-BT',                  
    '/_b_a_c_k_e_n_d/HMS/investigation-price/patch-bill-type/': 'HMS-P-BT',       
    r'^/_b_a_c_k_e_n_d/HMS/bill-types_get/?(\?.*)?$': 'HMS-P-BT',                  
    r'^/_b_a_c_k_e_n_d/HMS/bill-types/update(?:/[^/]+)+/$': 'HMS-P-BT',                  
    r'^/_b_a_c_k_e_n_d/HMS/bill-types/delete(?:/[^/]+)+/$': 'HMS-P-BT',                  

    #Investigation Prices:
    '/_b_a_c_k_e_n_d/HMS/investigation-prices_get/': 'HMS-P-IP',                  
    '/_b_a_c_k_e_n_d/HMS/investigation-prices/create/': 'HMS-P-IP',                        
    r'^/_b_a_c_k_e_n_d/HMS/investigation-prices/update(?:/[^/]+)+/$': 'HMS-P-IP',                  
    r'^/_b_a_c_k_e_n_d/HMS/investigation-prices/delete(?:/[^/]+)+/$': 'HMS-P-IP',  

    #Report:
    r'^/_b_a_c_k_e_n_d/HMS/dept-budr/?(\?.*)?$': 'HMS-P-DBUDR',   

    #Velavan Items:
    '/_b_a_c_k_e_n_d/HMS/velavan_items/list/': 'HMS-P-VI',               
    '/_b_a_c_k_e_n_d/HMS/velavan_create_item/': 'HMS-P-VI',               
    '/_b_a_c_k_e_n_d/HMS/velavan_get_items/': 'HMS-P-VI',               
    r'^/_b_a_c_k_e_n_d/HMS/velavan_update_item(?:/[^/]+)+/$': 'HMS-P-VI',               
    r'^/_b_a_c_k_e_n_d/HMS/velavan_delete_item(?:/[^/]+)+/$': 'HMS-P-VI',               

    #Velavan Vendors:
    '/_b_a_c_k_e_n_d/HMS/velavan_vendors/list/': 'HMS-P-VV', 
    '/_b_a_c_k_e_n_d/HMS/velavan_create_vendor/': 'HMS-P-VV',               
    '/_b_a_c_k_e_n_d/HMS/velavan_get_vendors/': 'HMS-P-VV',               
    r'^/_b_a_c_k_e_n_d/HMS/velavan_update_vendor(?:/[^/]+)+/$': 'HMS-P-VV',               
    r'^/_b_a_c_k_e_n_d/HMS/velavan_delete_vendor(?:/[^/]+)+/$': 'HMS-P-VV',  

    #Velavan Invoices:
    '/_b_a_c_k_e_n_d/HMS/velavan/invoices/': 'HMS-P-VIN',        
    r'^/_b_a_c_k_e_n_d/HMS/velavan/invoices/list/?(\?.*)?$': 'HMS-P-VINR',        
    r'^/_b_a_c_k_e_n_d/HMS/velavan/previous-purchases/?(\?.*)?$': 'HMS-P-VINR',  
    r'^/_b_a_c_k_e_n_d/HMS/velavan/invoices/update(?:/[^/]+)+/$': 'HMS-P-VINR',     
    r'^/_b_a_c_k_e_n_d/HMS/velavan/invoices/update(?:/[^/]+)+/$': 'HMS-P-VINA',     

    #OT Master:
    '/_b_a_c_k_e_n_d/HMS/create_ot/': 'HMS-P-OTM',               
    '/_b_a_c_k_e_n_d/HMS/list_ots/': 'HMS-P-OTM',                  
    r'^/_b_a_c_k_e_n_d/HMS/update_ot(?:/[^/]+)+/$': 'HMS-P-OTM',               
    r'^/_b_a_c_k_e_n_d/HMS/delete_ot(?:/[^/]+)+/$': 'HMS-P-OTM',  

    #Anesthesia Master:
    '/_b_a_c_k_e_n_d/HMS/create_anes/': 'HMS-P-AM',               
    '/_b_a_c_k_e_n_d/HMS/list_anes/': 'HMS-P-AM',                  
    r'^/_b_a_c_k_e_n_d/HMS/update_anes(?:/[^/]+)+/$': 'HMS-P-AM',               
    r'^/_b_a_c_k_e_n_d/HMS/delete_anes(?:/[^/]+)+/$': 'HMS-P-AM', 

    #Surgery Schedule:
    '/_b_a_c_k_e_n_d/HMS/create_surgery_schedule/': 'HMS-P-OTSS',               
    r'^/_b_a_c_k_e_n_d/HMS/list_surgery_schedules/?(\?.*)?$': 'HMS-P-OTSS',                
    '/_b_a_c_k_e_n_d/HMS/get_surgery_schedule/': 'HMS-P-OTSS',                
    '/_b_a_c_k_e_n_d/HMS/update_surgery_schedule/': 'HMS-P-OTSS',                
    '/_b_a_c_k_e_n_d/HMS/cancel_surgery_schedule/': 'HMS-P-OTSS',                
    '/_b_a_c_k_e_n_d/HMS/update_schedule_status/': 'HMS-P-OTSS',                
    '/_b_a_c_k_e_n_d/HMS/list_diagnosis/': 'HMS-P-OTSS',                
    r'^/_b_a_c_k_e_n_d/HMS/get_ot_medicine_ward_requests/?(\?.*)?$': 'HMS-P-OTSS',                
    r'^/_b_a_c_k_e_n_d/HMS/get_ippharmacy_stock/?(\?.*)?$': 'HMS-P-OTSS',  
    '/_b_a_c_k_e_n_d/HMS/save_ot_medicine_ward_request/': 'HMS-P-OTSS',    

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



