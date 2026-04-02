PAGE_MAPPING = {

    r'^/_b_a_c_k_e_n_d/HMS/create/?(\?.*)?$': 'HMS-P-ADM',
    '/_b_a_c_k_e_n_d/HMS/patients/register/': 'HMS-P-AIN',
    r'^/_b_a_c_k_e_n_d/HMS/doctor_schedule_list/?(\?.*)?$': 'HMS-P-AIN',
    r'^/_b_a_c_k_e_n_d/HMS/doctor_schedule/?(\?.*)?$': 'HMS-P-AIN',
    r'^/_b_a_c_k_e_n_d/HMS/get-reference-doctors/?(\?.*)?$': 'HMS-P-AIN',
    r'^/_b_a_c_k_e_n_d/HMS/patient-registration-stats/?(\?.*)?$': 'HMS-P-AIN',
    '/_b_a_c_k_e_n_d/HMS/get-last-uhid/': 'HMS-P-AIN',
    r'^/_b_a_c_k_e_n_d/HMS/insurance-providers/?(\?.*)?$': 'HMS-P-AIN',
    r'^/_b_a_c_k_e_n_d/HMS/get-sidebar-mapping/?(\?.*)?$': 'HMS-P-AIN',


    # ==================== ADMISSION ====================
    r'^/_b_a_c_k_e_n_d/HMS/doctor_list_diagnostics/?(\?.*)?$': 'HMS-P-DLD',
    r'^/_b_a_c_k_e_n_d/HMS/autoipNumber/?(\?.*)?$': 'HMS-P-AIN',
    r'^/_b_a_c_k_e_n_d/HMS/admission/?(\?.*)?$': 'HMS-P-ADM',
    r'^/_b_a_c_k_e_n_d/HMS/admission/[^/]+/?(\?.*)?$': 'HMS-P-ADD',
    r'^/_b_a_c_k_e_n_d/HMS/op-patient/[^/]+/?(\?.*)?$': 'HMS-P-OPP',
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
    r'^/_b_a_c_k_e_n_d/HMS/room-category/[0-9]+/?(\?.*)?$': 'HMS-P-RCATD',
    r'^/_b_a_c_k_e_n_d/HMS/room/?(\?.*)?$': 'HMS-P-RM',
    r'^/_b_a_c_k_e_n_d/HMS/room/[0-9]+/?(\?.*)?$': 'HMS-P-RMD',
    r'^/_b_a_c_k_e_n_d/HMS/bed/?(\?.*)?$': 'HMS-P-BED',
    r'^/_b_a_c_k_e_n_d/HMS/bed/[0-9]+/?(\?.*)?$': 'HMS-P-BEDD',
    r'^/_b_a_c_k_e_n_d/HMS/service/?(\?.*)?$': 'HMS-P-SRV',
    r'^/_b_a_c_k_e_n_d/HMS/service/[0-9]+/?(\?.*)?$': 'HMS-P-SRVD',
    r'^/_b_a_c_k_e_n_d/HMS/room-enquiry/?(\?.*)?$': 'HMS-P-RENQ',
    r'^/_b_a_c_k_e_n_d/HMS/room-shifting/?(\?.*)?$': 'HMS-P-RSHFT',

    # ==================== DISCHARGE ====================
    r'^/_b_a_c_k_e_n_d/HMS/search-admissions/?(\?.*)?$': 'HMS-P-SADM',
    r'^/_b_a_c_k_e_n_d/HMS/discharge/?(\?.*)?$': 'HMS-P-DIS',

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
    '/_b_a_c_k_e_n_d/HMS/doctor_list_diagnostics/': 'HMS-P-DRM',                  
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


    # PHARMACY STOCK   
        '/_b_a_c_k_e_n_d/HMS/get_oppharmacy_stock/': 'HMS-P-PGS',
        '/_b_a_c_k_e_n_d/HMS/save_oppharmacy_bill/': 'HMS-P-PSOPB',
        '/_b_a_c_k_e_n_d/HMS/get_pharmacy_BillType/': 'HMS-P-PGPBT',
        '/_b_a_c_k_e_n_d/HMS/get_estimate_bills/': 'HMS-P-PGEB',
        '/_b_a_c_k_e_n_d/HMS/get_last_billed_uhid/': 'HMS-P-PGLBU',
        '/_b_a_c_k_e_n_d/HMS/OPPharmacy_pending_bills/': 'HMS-P-PGLBU',
         '/_b_a_c_k_e_n_d/HMS/collect_oppharmacy_payment/': 'HMS-P-PCOPP',
         '/_b_a_c_k_e_n_d/HMS/oppharmacy_deletebill/': 'HMS-P-POPPDB',
         '/_b_a_c_k_e_n_d/HMS/uhidadmissionstatus/': 'HMS-P-POPUAS',

        # Central cah counter

        '/_b_a_c_k_e_n_d/HMS/cashcountershiftdetails/': 'HMS-P-PCCSD',
        '/_b_a_c_k_e_n_d/HMS/get_active_shift/': 'HMS-P-PGAS',

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



