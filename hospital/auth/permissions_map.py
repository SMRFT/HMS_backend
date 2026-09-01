PAGE_MAPPING = {
    r'^/_b_a_c_k_e_n_d/HMS/patient-inquiry/?(\?.*)?$': 'HMS-P-AIN',
    r'^/_b_a_c_k_e_n_d/HMS/create/?(\?.*)?$': 'HMS-P-AIN',
    '/_b_a_c_k_e_n_d/HMS/patients/register/': 'HMS-P-AIN',
    r'^/_b_a_c_k_e_n_d/HMS/get-reference-doctors/?(\?.*)?$': 'HMS-P-AIN',
    r'^/_b_a_c_k_e_n_d/HMS/patient-registration-stats/?(\?.*)?$': 'HMS-P-AIN',
    r'^/_b_a_c_k_e_n_d/HMS/patient-visit-list/?(\?.*)?$': 'HMS-P-AIN',
    r'^/_b_a_c_k_e_n_d/HMS/get-pending-qr-registrations/?(\?.*)?$': 'HMS-P-AIN',
    '/_b_a_c_k_e_n_d/HMS/get-last-uhid/': 'HMS-P-AIN',
    r'^/_b_a_c_k_e_n_d/HMS/insurance-providers/?(\?.*)?$': 'HMS-P-AIN',
    r'^/_b_a_c_k_e_n_d/HMS/process-registration-refund/?(\?.*)?$': 'HMS-P-AIN',
    r'^/_b_a_c_k_e_n_d/HMS/update-registration-visit/?(\?.*)?$': 'HMS-P-AIN',
    r'^/_b_a_c_k_e_n_d/HMS/referred-patients-report/?(\?.*)?$': 'HMS-P-AIN',
    r'^/_b_a_c_k_e_n_d/HMS/front-office-reports/?(\?.*)?$': 'HMS-P-AIN',
    r'^/_b_a_c_k_e_n_d/HMS/RoomOccupencyReport/?(\?.*)?$': 'HMS-P-ROR',
    r'^/_b_a_c_k_e_n_d/HMS/PreDayRoomOccupancyReport/?(\?.*)?$': 'HMS-P-ROR',
    r'^/_b_a_c_k_e_n_d/HMS/get-sidebar-mapping/?(\?.*)?$': 'HMS-P-SB',
    r'^/_b_a_c_k_e_n_d/HMS/insurance-claims/?(\?.*)?$': 'HMS-P-ICD',


    # ==================== WARD REQUEST ====================
    r'^/_b_a_c_k_e_n_d/HMS/save_medicine_ward_request/?(\?.*)?$': 'HMS-P-WR',
    r'^/_b_a_c_k_e_n_d/HMS/update_medicine_ward_request/?(\?.*)?$': 'HMS-P-WR',
    r'^/_b_a_c_k_e_n_d/HMS/get_medicine_ward_requests/?(\?.*)?$': 'HMS-P-WR',
    r'^/_b_a_c_k_e_n_d/HMS/return_medicine_ward_request/?(\?.*)?$': 'HMS-P-WR',
    r'^/_b_a_c_k_e_n_d/HMS/get_pending_ward_returns/?(\?.*)?$': 'HMS-P-WR',
    r'^/_b_a_c_k_e_n_d/HMS/approve_ward_return/?(\?.*)?$': 'HMS-P-WR',
    r'^/_b_a_c_k_e_n_d/HMS/get_radiology_ward_requests/?(\?.*)?$': 'HMS-P-WR',
    r'^/_b_a_c_k_e_n_d/HMS/save_radiology_ward_request/?(\?.*)?$': 'HMS-P-WR',
    r'^/_b_a_c_k_e_n_d/HMS/update_radiology_ward_request/?(\?.*)?$': 'HMS-P-WR',
    r'^/_b_a_c_k_e_n_d/HMS/cancel_radiology_ward_request/?(\?.*)?$': 'HMS-P-WR',
    


    
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

    # ==================== LAUNDRY ====================
    r'^/_b_a_c_k_e_n_d/HMS/save_laundry_request/?(\?.*)?$': 'HMS-P-LND',
    r'^/_b_a_c_k_e_n_d/HMS/get_laundry_requests/?(\?.*)?$': 'HMS-P-LND',
    r'^/_b_a_c_k_e_n_d/HMS/update_laundry_status/?(\?.*)?$': 'HMS-P-LND',
    r'^/_b_a_c_k_e_n_d/HMS/get_all_laundry_requests/?(\?.*)?$': 'HMS-P-LND',
    r'^/_b_a_c_k_e_n_d/HMS/get_laundry_items_master/?(\?.*)?$': 'HMS-P-LND',
    r'^/_b_a_c_k_e_n_d/HMS/save_laundry_item_master/?(\?.*)?$': 'HMS-P-LND',
    r'^/_b_a_c_k_e_n_d/HMS/delete_laundry_item_master/?(\?.*)?$': 'HMS-P-LND',
    
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

    r'^/_b_a_c_k_e_n_d/HMS/vendors/?(\?.*)?$': 'HMS-P-VND',
    r'^/_b_a_c_k_e_n_d/HMS/vendors/[0-9]+/?(\?.*)?$': 'HMS-P-VNDD',
    r'^/_b_a_c_k_e_n_d/HMS/general-store-vendors/?(\?.*)?$': 'HMS-P-VND',
    r'^/_b_a_c_k_e_n_d/HMS/general-store-vendors/[^/]+/?(\?.*)?$': 'HMS-P-VNDD',

    r'^/_b_a_c_k_e_n_d/HMS/pharmacy_items/?(\?.*)?$': 'HMS-P-VND',
    r'^/_b_a_c_k_e_n_d/HMS/pharmacy_items/[^/]+/?(\?.*)?$': 'HMS-P-PID',
    r'^/_b_a_c_k_e_n_d/HMS/get_pharmacy_item_tracking/?(\?.*)?$': 'HMS-P-PID',

    r'^/_b_a_c_k_e_n_d/HMS/grn/?(\?.*)?$': 'HMS-P-GRN',
    r'^/_b_a_c_k_e_n_d/HMS/grn(?:/[^/]+)+/$': 'HMS-P-GRNA',
    r'^/_b_a_c_k_e_n_d/HMS/grn-items/?(\?.*)?$': 'HMS-P-GRNR',
    r'^/_b_a_c_k_e_n_d/HMS/pharmacy_stock_history/?(\?.*)?$': 'HMS-P-PSH',
    r'^/_b_a_c_k_e_n_d/HMS/grn-ocr/?(\?.*)?$': 'HMS-P-OCR',

    # Purchase Return
    r'^/_b_a_c_k_e_n_d/HMS/purchase-return/?(\?.*)?$': 'HMS-P-GPR',
    r'^/_b_a_c_k_e_n_d/HMS/purchase-return/[^/]+/?(\?.*)?$': 'HMS-P-GPRA',

    r'^/_b_a_c_k_e_n_d/HMS/pharmacy-stock/[^/]+/?(\?.*)?$': 'HMS-P-PER',
    r'^/_b_a_c_k_e_n_d/HMS/get_active_outlets/?(\?.*)?$': 'HMS-P-OS',
    r'^/_b_a_c_k_e_n_d/HMS/pharmacy_expiry_report/?(\?.*)?$': 'HMS-P-PER',

    r'^/_b_a_c_k_e_n_d/HMS/stock-transfer/?(\?.*)?$': 'HMS-P-ST',
    '^/_b_a_c_k_e_n_d/HMS/stock-transfer-action/': 'HMS-P-STA',

    r'^/_b_a_c_k_e_n_d/HMS/purchase-order/?$': 'HMS-P-PO',
    r'^/_b_a_c_k_e_n_d/HMS/purchase-order/.+/?$': 'HMS-P-POL',
    r'^/_b_a_c_k_e_n_d/HMS/purchase-order-action/?$': 'HMS-P-POA',
    r'^/_b_a_c_k_e_n_d/HMS/purchase-order-email/?$': 'HMS-P-POA',

    r"^/_b_a_c_k_e_n_d/HMS/medicine-requisition/?$":       "HMS-P-MR",
    r"^/_b_a_c_k_e_n_d/HMS/medicine-requisition/.+/?$":    "HMS-P-MRL",
    r"^/_b_a_c_k_e_n_d/HMS/medicine-requisition-action/?$":"HMS-P-MRA",

    r"^/_b_a_c_k_e_n_d/HMS/purchase-requisition/?$":       "HMS-P-PR",
    r"^/_b_a_c_k_e_n_d/HMS/purchase-requisition/.+/?$":    "HMS-P-PRL",
    r"^/_b_a_c_k_e_n_d/HMS/purchase-requisition-action/?$":"HMS-P-PRA",

    r"^/_b_a_c_k_e_n_d/HMS/medicine-tracking/?$":          "HMS-P-MT",

    # ==================== DISCHARGE ====================
    r'^/_b_a_c_k_e_n_d/HMS/search-admissions/?(\?.*)?$': 'HMS-P-SADM',
    r'^/_b_a_c_k_e_n_d/HMS/discharge/?(\?.*)?$': 'HMS-P-DIS',
    r'^/_b_a_c_k_e_n_d/HMS/search-discharge-patient/?(\?.*)?$': 'HMS-P-IB',
    r'^/_b_a_c_k_e_n_d/HMS/discharge-billing/?(\?.*)?$': 'HMS-P-IB',
    r'^/_b_a_c_k_e_n_d/HMS/discharge-billing/.+$': 'HMS-P-IB',

    # ==================== NURSING ======================
    r'^/_b_a_c_k_e_n_d/HMS/admission-by-uhid/[^/]+/?(\?.*)?$': 'HMS-P-AUHID',
    r'^/_b_a_c_k_e_n_d/HMS/admission-by-ip/[^/]+/?(\?.*)?$': 'HMS-P-AIP',

    #Vaccination Details:
    '/_b_a_c_k_e_n_d/HMS/vaccination-masters/': 'HMS-P-HVCC',
    r'^/_b_a_c_k_e_n_d/HMS/vaccination-masters/?(\?.*)?$': 'HMS-P-HVCC',
    '/_b_a_c_k_e_n_d/HMS/add-vaccination-master/': 'HMS-P-HVCC',
    r'^/_b_a_c_k_e_n_d/HMS/update-vaccination-master(?:/[^/]+)+/$': 'HMS-P-HVCC',
    r'^/_b_a_c_k_e_n_d/HMS/delete-vaccination-master/.*$': 'HMS-P-HVCC',
    r'^/_b_a_c_k_e_n_d/HMS/pending-vaccinations/?(\?.*)?$': 'HMS-P-HVCC',
    r'^/_b_a_c_k_e_n_d/HMS/patient-vaccination(?:/[^/]+)+/$': 'HMS-P-HVCC',
    '/_b_a_c_k_e_n_d/HMS/save-patient-vaccination/': 'HMS-P-HVCC',

     #Investigation Billing:
    r'^/_b_a_c_k_e_n_d/HMS/op-patient(?:/[^/]+)+/$': 'HMS-API-UHID',           
    r'^/_b_a_c_k_e_n_d/HMS/ip-patient(?:/[^/]+)+/$': 'HMS-P-IB',                 
    '/_b_a_c_k_e_n_d/HMS/doctor_list/': 'HMS-P-IB',                 
    '/_b_a_c_k_e_n_d/HMS/bill-types/': 'HMS-P-IB',                 
    '/_b_a_c_k_e_n_d/HMS/invest-bill-types/': 'HMS-P-IB',                 
    '/_b_a_c_k_e_n_d/HMS/packages/': 'HMS-API-PACK',                 
    r'^/_b_a_c_k_e_n_d/HMS/package-items/?(\?.*)?$': 'HMS-P-IB',                 
    r'^/_b_a_c_k_e_n_d/HMS/investigation-items/?(\?.*)?$': 'HMS-P-IB',       
    '/_b_a_c_k_e_n_d/HMS/investBilling/': 'HMS-P-IB',                 
    r'^/_b_a_c_k_e_n_d/HMS/investBillingGet/?(\?.*)?$': 'HMS-P-IB',                 
    '/_b_a_c_k_e_n_d/HMS/estimateBilling/': 'HMS-P-IB',                 
    r'^/_b_a_c_k_e_n_d/HMS/get-estimate-billings/?(\?.*)?$': 'HMS-P-IB',                 
    '/_b_a_c_k_e_n_d/HMS/delete-bill/': 'HMS-P-IB',       
    '/_b_a_c_k_e_n_d/HMS/invest-refund/': 'HMS-P-IB',       

    #Investigation Reports (RD):
    r'^/_b_a_c_k_e_n_d/HMS/investigations/?(\?.*)?$': 'HMS-API-RD',                
    '/_b_a_c_k_e_n_d/HMS/scan-reports/': 'HMS-API-RD',                 
    '/_b_a_c_k_e_n_d/HMS/hard-bill-types/': 'HMS-API-RD',                 
    r'^/_b_a_c_k_e_n_d/HMS/scan_reports/?(\?.*)?$': 'HMS-API-RD',                 
    r'^/_b_a_c_k_e_n_d/HMS/scan_reports(?:/[^/]+)+/$': 'HMS-API-RD',                 
    r'^/_b_a_c_k_e_n_d/HMS/scan-reports/slot(?:/[^/]+)+/$': 'HMS-API-RD',                 
    r'^/_b_a_c_k_e_n_d/HMS/scan-reports/checkin(?:/[^/]+)+/$': 'HMS-API-RD',                 
    r'^/_b_a_c_k_e_n_d/HMS/scan-reports/scan-started(?:/[^/]+)+/$': 'HMS-API-RD',                 
    r'^/_b_a_c_k_e_n_d/HMS/scan-reports/dispatch(?:/[^/]+)+/$': 'HMS-API-RD',                 
    r'^/_b_a_c_k_e_n_d/HMS/scan-reports/approve(?:/[^/]+)+/$': 'HMS-API-RDA',                 
    r'^/_b_a_c_k_e_n_d/HMS/scan-reports/delete(?:/[^/]+)+/$': 'HMS-API-RDD',  
    r'^/_b_a_c_k_e_n_d/HMS/scan-reports/edit(?:/[^/]+)+/$': 'HMS-API-RDE',  
    r'^/_b_a_c_k_e_n_d/HMS/employee-signature/?(\?.*)?$': 'HMS-API-RD',  
    r'^/_b_a_c_k_e_n_d/HMS/radiology/dicom-study/?(\?.*)?$': 'HMS-API-RD',  

    # MHC Reports:
    r'^/_b_a_c_k_e_n_d/HMS/mhc-investigations/?(\?.*)?$': 'HMS-P-MHC',
    '/_b_a_c_k_e_n_d/HMS/mhc-reports/': 'HMS-P-MHC',
    r'^/_b_a_c_k_e_n_d/HMS/mhc-reports/format/?(\?.*)?$': 'HMS-P-MHC',
    r'^/_b_a_c_k_e_n_d/HMS/mhc-reports/checkin(?:/[^/]+)+/$': 'HMS-P-MHC',
    r'^/_b_a_c_k_e_n_d/HMS/mhc-reports/dispatch(?:/[^/]+)+/$': 'HMS-P-MHC',
    r'^/_b_a_c_k_e_n_d/HMS/mhc-reports/approve(?:/[^/]+)+/$': 'HMS-P-MHCA',
    r'^/_b_a_c_k_e_n_d/HMS/mhc-reports/delete(?:/[^/]+)+/$': 'HMS-P-MHCD',
    r'^/_b_a_c_k_e_n_d/HMS/mhc-reports/edit(?:/[^/]+)+/$': 'HMS-P-MHCE',
    r'^/_b_a_c_k_e_n_d/HMS/send-mhc-reminders/.*$': 'HMS-P-MHC',
    r'^/_b_a_c_k_e_n_d/HMS/preview-mhc-reminders/.*$': 'HMS-P-MHC',
    r'^/_b_a_c_k_e_n_d/HMS/mhc-reports(?:/[^/]+)+/$': 'HMS-P-MHC',

     #Investigation Reports (RD):      
    r'^/_b_a_c_k_e_n_d/HMS/anc-register/?(\?.*)?$': 'HMS-API-JRD',  
    r'^/_b_a_c_k_e_n_d/HMS/jrd-reports/?(\?.*)?$': 'HMS-API-JRD',  
    '/_b_a_c_k_e_n_d/HMS/jrd-reports/create/': 'HMS-API-JRD', 
    r'^/_b_a_c_k_e_n_d/HMS/jrd-reports/update(?:/[^/]+)+/$': 'HMS-P-JRDE',  
    r'^/_b_a_c_k_e_n_d/HMS/jrd-reports/delete(?:/[^/]+)+/$': 'HMS-P-JRDD',  

    #Summary:    
    r'^/_b_a_c_k_e_n_d/HMS/summaries/?(\?.*)?$': 'HMS-P-SUM',                  
    r'^/_b_a_c_k_e_n_d/HMS/summary-type/?.*$': 'HMS-P-SUM',                  
    r'^/_b_a_c_k_e_n_d/HMS/summary-heading/?.*$': 'HMS-P-SUM',                  
    '/_b_a_c_k_e_n_d/HMS/summaries/create/': 'HMS-P-SUM',                  
    r'^/_b_a_c_k_e_n_d/HMS/approve-summary(?:/[^/]+)+/$': 'HMS-P-SUMA',                  
    r'^/_b_a_c_k_e_n_d/HMS/delete-summary(?:/[^/]+)+/$': 'HMS-P-SUMD',                  
    r'^/_b_a_c_k_e_n_d/HMS/get-editsummary(?:/[^/]+)+/$': 'HMS-P-SUM',                  
    r'^/_b_a_c_k_e_n_d/HMS/update-summary(?:/[^/]+)+/$': 'HMS-P-SUME',                  
    r'^/_b_a_c_k_e_n_d/HMS/patient-investigations(?:/[^/]+)+/$': 'HMS-P-SUM', 
    r'^/_b_a_c_k_e_n_d/HMS/get-printsummary(?:/[^/]+)+/$': 'HMS-P-SUM',                  
    r'^/_b_a_c_k_e_n_d/HMS/patient-medicines(?:/[^/]+)+/$': 'HMS-P-SUM',                  
    r'^/_b_a_c_k_e_n_d/HMS/patient-discharge-medicines(?:/[^/]+)+/$': 'HMS-P-SUM',                  
    r'^/_b_a_c_k_e_n_d/HMS/upload-pdf/?(\?.*)?$': 'HMS-P-SUM',
    r'^/_b_a_c_k_e_n_d/HMS/get-file(?:/[^/]+)+/$': 'HMS-P-SUM',
    r'^/_b_a_c_k_e_n_d/HMS/send-whatsapp/?(\?.*)?$': 'HMS-API-WTSAP',
    r'^/_b_a_c_k_e_n_d/HMS/send-email/?(\?.*)?$': 'HMS-API-EML',
    r'^/_b_a_c_k_e_n_d/HMS/discharge-billing/send-visit-reminders/?(\?.*)?$': 'HMS-API-WTSAP',
    r'^/_b_a_c_k_e_n_d/HMS/send-discharge-visit-reminder/?(\?.*)?$': 'HMS-API-WTSAP',
    r'^/_b_a_c_k_e_n_d/HMS/patient-next-visit-logs/?(\?.*)?$': 'HMS-API-WTSAP',
    r'^/_b_a_c_k_e_n_d/HMS/communication-logs/?(\?.*)?$': 'HMS-P-SUM',

        '^/_b_a_c_k_e_n_d/HMS/create_dialysis_discharge_summary/': 'HMS-P-CDDS',
    r'^/_b_a_c_k_e_n_d/HMS/Print_dialysis_dischargesummary/?(\?.*)?$': 'HMS-P-PDDS',

    #HR: 
    r'^/_b_a_c_k_e_n_d/HMS/hr/internships/?(\?.*)?$': 'HMS-P-HRIN',
    r'^/_b_a_c_k_e_n_d/HMS/hr/internships/autocomplete/?(\?.*)?$': 'HMS-P-HRIN',
    '/_b_a_c_k_e_n_d/HMS/hr/internships/certificate-template/': 'HMS-P-HRIN',
    r'^/_b_a_c_k_e_n_d/HMS/hr/internships/certificate-template(?:/[^/]+)+/$': 'HMS-P-HRIN',
    r'^/_b_a_c_k_e_n_d/HMS/hr/internships/edit(?:/[^/]+)+/$': 'HMS-P-HRIN',
    r'^/_b_a_c_k_e_n_d/HMS/hr/internships/payment(?:/[^/]+)+/$': 'HMS-P-HRINP',
    r'^/_b_a_c_k_e_n_d/HMS/hr/internships/approve(?:/[^/]+)+/$': 'HMS-P-HRINA',

    #Doctor Master: 
    '/_b_a_c_k_e_n_d/HMS/doctor_list_diagnostics/': 'HMS-API-DLD',                  
    '/_b_a_c_k_e_n_d/HMS/doctor_schedule/': 'HMS-P-DRM',
    r'^/_b_a_c_k_e_n_d/HMS/doctor_schedule(?:/[^/]+)+/$': 'HMS-P-DRM',                    
    r'^/_b_a_c_k_e_n_d/HMS/doctor_schedule_upsert(?:/[^/]+)+/$': 'HMS-P-DRM',   
    r'^/_b_a_c_k_e_n_d/HMS/doctor-report/?.*': 'HMS-API-DLD',   

    #Package Master:
    '/_b_a_c_k_e_n_d/HMS/investigation-prices/': 'HMS-P-IPKG',                  
    '/_b_a_c_k_e_n_d/HMS/lab-items/': 'HMS-P-IPKG',                 
    '/_b_a_c_k_e_n_d/HMS/packages_crud/': 'HMS-P-IPKG',                  
    '/_b_a_c_k_e_n_d/HMS/packages/create/': 'HMS-P-IPKG',                  
    r'^/_b_a_c_k_e_n_d/HMS/packages(?:/[^/]+)+/$': 'HMS-P-IPKG',                  
    r'^/_b_a_c_k_e_n_d/HMS/packages/update(?:/[^/]+)+/$': 'HMS-P-IPKGE',                  
    r'^/_b_a_c_k_e_n_d/HMS/packages/delete(?:/[^/]+)+/$': 'HMS-P-IPKGD',     

    #MedicinePackage Master:            
    '/_b_a_c_k_e_n_d/HMS/medicine-packages/': 'HMS-P-MPKG',                  
    r'^/_b_a_c_k_e_n_d/HMS/pharmacy-items/?(\?.*)?$': 'HMS-P-MPKG',                
    '/_b_a_c_k_e_n_d/HMS/medicine-packages/create/': 'HMS-P-MPKG',                  
    r'^/_b_a_c_k_e_n_d/HMS/medicine-packages(?:/[^/]+)+/$': 'HMS-P-MPKG',                  
    r'^/_b_a_c_k_e_n_d/HMS/medicine-packages/update/(?:/[^/]+)+/$': 'HMS-P-MPKGE',                  
    r'^/_b_a_c_k_e_n_d/HMS/medicine-packages/delete(?:/[^/]+)+/$': 'HMS-P-MPKGD',   
    #Bill Type Master:
    '/_b_a_c_k_e_n_d/HMS/bill-types_get/': 'HMS-P-BT',                  
    '/_b_a_c_k_e_n_d/HMS/bill-types/create/': 'HMS-P-BT',                  
    '/_b_a_c_k_e_n_d/HMS/investigation-price/patch-bill-type/': 'HMS-P-BT',       
    r'^/_b_a_c_k_e_n_d/HMS/bill-types_get/?(\?.*)?$': 'HMS-P-BT',                  
    r'^/_b_a_c_k_e_n_d/HMS/bill-types/update(?:/[^/]+)+/$': 'HMS-P-BTE',                  
    r'^/_b_a_c_k_e_n_d/HMS/bill-types/delete(?:/[^/]+)+/$': 'HMS-P-BTD',                  

    #Investigation Prices:
    '/_b_a_c_k_e_n_d/HMS/investigation-prices_get/': 'HMS-P-IP',                  
    r'^/_b_a_c_k_e_n_d/HMS/investigation-prices_get/?(\?.*)?$': 'HMS-P-IP',                  
    '/_b_a_c_k_e_n_d/HMS/investigation-prices/create/': 'HMS-P-IP',                        
    r'^/_b_a_c_k_e_n_d/HMS/investigation-prices/update(?:/[^/]+)+/$': 'HMS-P-IPE',                  
    r'^/_b_a_c_k_e_n_d/HMS/investigation-prices/update_item(?:/[^/]+)+/$': 'HMS-P-IPE',                  
    r'^/_b_a_c_k_e_n_d/HMS/investigation-prices/delete(?:/[^/]+)+/$': 'HMS-P-IPD',  
    r'^/_b_a_c_k_e_n_d/HMS/investigation-prices/delete_item(?:/[^/]+)+/$': 'HMS-P-IPD',  

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
    r'^/_b_a_c_k_e_n_d/HMS/vel-ip-patient(?:/[^/]+)+/$': 'HMS-P-VINR',        
    r'^/_b_a_c_k_e_n_d/HMS/velavan/previous-purchases/?(\?.*)?$': 'HMS-P-VINR',  
    r'^/_b_a_c_k_e_n_d/HMS/velavan/invoices/update(?:/[^/]+)+/$': 'HMS-P-VINE',     
    r'^/_b_a_c_k_e_n_d/HMS/velavan/invoices/approve(?:/[^/]+)+/$': 'HMS-P-VINA',   
    r'^/_b_a_c_k_e_n_d/HMS/implant/requests/report/?(\?.*)?$': 'HMS-P-OTIRV',   
    '/_b_a_c_k_e_n_d/HMS/velavan/purchase-return/': 'HMS-P-VIN', 
    '/_b_a_c_k_e_n_d/HMS/velavan/purchase-return/list/': 'HMS-P-VINR', 
    
    # Velavan Sales
    '/_b_a_c_k_e_n_d/HMS/velavan/sales/': 'HMS-P-VS',               
    r'^/_b_a_c_k_e_n_d/HMS/velavan/sales/list/?(\?.*)?$': 'HMS-P-VS',               
    r'^/_b_a_c_k_e_n_d/HMS/velavan/stock/search/?(\?.*)?$': 'HMS-P-VS',               
    r'^/_b_a_c_k_e_n_d/HMS/velavan/stock/by-grn/?(\?.*)?$': 'HMS-P-VS',               
    r'^/_b_a_c_k_e_n_d/HMS/velavan/stock/list/?(\?.*)?$': 'HMS-P-VS',  
    '/_b_a_c_k_e_n_d/HMS/velavan/sales-return/': 'HMS-P-VS',  
    r'^/_b_a_c_k_e_n_d/HMS/velavan/sales-return/list/?(\?.*)?$': 'HMS-P-VS',  

    #Velavan Customers:     
    '/_b_a_c_k_e_n_d/HMS/velavan_create_customer/': 'HMS-P-VCC',       
    '/_b_a_c_k_e_n_d/HMS/velavan_customers/list/': 'HMS-P-VCC',       
    r'^/_b_a_c_k_e_n_d/HMS/velavan_update_customer(?:/[^/]+)+/$': 'HMS-P-VCE',       
    r'^/_b_a_c_k_e_n_d/HMS/velavan_delete_customer(?:/[^/]+)+/$': 'HMS-P-VCD',       

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
    r'^/_b_a_c_k_e_n_d/HMS/ot_staffs/?(\?.*)?$': 'HMS-P-OTSS',

    r'^/_b_a_c_k_e_n_d/HMS/get_medicine_packages/?(\?.*)?$': 'HMS-P-OTMB',  
    r'^/_b_a_c_k_e_n_d/HMS/mark_ot_medicine_received/?(\?.*)?$': 'HMS-P-OTMB',  
    r'^/_b_a_c_k_e_n_d/HMS/get_ot_medicine_ward_requests/?(\?.*)?$': 'HMS-P-OTMB',                
    r'^/_b_a_c_k_e_n_d/HMS/update_ot_medicine_ward_request/?(\?.*)?$': 'HMS-P-OTMBE',                
    r'^/_b_a_c_k_e_n_d/HMS/delete_ot_medicine_ward_request/?(\?.*)?$': 'HMS-P-OTMBD',  
     r'^/_b_a_c_k_e_n_d/HMS/get_pharmacy_items/?(\?.*)?$': 'HMS-P-OTMB',
    '/_b_a_c_k_e_n_d/HMS/save_ot_medicine_ward_request/': 'HMS-P-OTMB', 

    #Implant Request:
    r'^/_b_a_c_k_e_n_d/HMS/get_implant_items/?(\?.*)?$': 'HMS-P-OTIR',  
    '/_b_a_c_k_e_n_d/HMS/save_implant_request/': 'HMS-P-OTIR',  
    r'^/_b_a_c_k_e_n_d/HMS/get_implant_requests/?(\?.*)?$': 'HMS-P-OTIR',             
    r'^/_b_a_c_k_e_n_d/HMS/get_ward_implant_requests/?(\?.*)?$': 'HMS-P-OTIR',
    r'^/_b_a_c_k_e_n_d/HMS/update_implant_request/?(\?.*)?$': 'HMS-P-OTIRE',                
    r'^/_b_a_c_k_e_n_d/HMS/delete_implant_request/?(\?.*)?$': 'HMS-P-OTIRD',      

    
    '/_b_a_c_k_e_n_d/HMS/save_lab_ward_request/': 'HMS-P-IB',
    '/_b_a_c_k_e_n_d/HMS/cancel_lab_ward_request/': 'HMS-P-IB',
    '/_b_a_c_k_e_n_d/HMS/get_lab_ward_requests/': 'HMS-P-IB',
    r'^/_b_a_c_k_e_n_d/HMS/get_lab_ward_requests/?(\?.*)?$': 'HMS-P-IB',    
               

    r'^/_b_a_c_k_e_n_d/HMS/crash-cart/items/?(\?.*)?$': 'HMS-P-CL',
    r'^/_b_a_c_k_e_n_d/HMS/crash-cart/daily-check/?(\?.*)?$': 'HMS-P-CL',
    r'^/_b_a_c_k_e_n_d/HMS/crash-cart/monthly-report/?(\?.*)?$': 'HMS-P-CL',

    #Doctor Fee Cuts:
    r'^/_b_a_c_k_e_n_d/HMS/doctor-fee-admitted-patients/?(\?.*)?$': 'HMS-P-DFC',
    r'^/_b_a_c_k_e_n_d/HMS/doctor-fee-cuts/approve-doctor-fee/?(\?.*)?$': 'HMS-P-DFC',
    r'^/_b_a_c_k_e_n_d/HMS/doctor-fee-cuts-report/?(\?.*)?$': 'HMS-P-DFCR',    
    r'^/_b_a_c_k_e_n_d/HMS/send-doctor-fee-cut-monthly-emails/?(\?.*)?$': 'HMS-P-DFCR',

    #Assets Management:
    r'^/_b_a_c_k_e_n_d/HMS/item-master/?(\?.*)?$': 'HMS-API-IT',
    r'^/_b_a_c_k_e_n_d/HMS/item-master/price-history/[^/]+/?(\?.*)?$': 'HMS-API-IT',
    r'^/_b_a_c_k_e_n_d/HMS/item-master/[^/]+/?(\?.*)?$': 'HMS-API-IT',
    r'^/_b_a_c_k_e_n_d/HMS/department-master/?(\?.*)?$': 'HMS-API-IT',
    r'^/_b_a_c_k_e_n_d/HMS/department-master/[^/]+/?(\?.*)?$': 'HMS-API-IT',
    r'^/_b_a_c_k_e_n_d/HMS/group-master/?(\?.*)?$': 'HMS-API-IT',
    r'^/_b_a_c_k_e_n_d/HMS/group-master/[^/]+/?(\?.*)?$': 'HMS-API-IT',
    r'^/_b_a_c_k_e_n_d/HMS/category-master/?(\?.*)?$': 'HMS-API-IT',
    r'^/_b_a_c_k_e_n_d/HMS/category-master/[^/]+/?(\?.*)?$': 'HMS-API-IT',
    r'^/_b_a_c_k_e_n_d/HMS/group-type-master/?(\?.*)?$': 'HMS-API-IT',
    r'^/_b_a_c_k_e_n_d/HMS/group-type-master/[^/]+/?(\?.*)?$': 'HMS-API-IT',

    # Stores GRN:
    '/_b_a_c_k_e_n_d/HMS/stores-grn/': 'HMS-P-SGRN',
    '/_b_a_c_k_e_n_d/HMS/stores-grn/.*/': 'HMS-P-SGRN',

    # Stores Intent:
    '/_b_a_c_k_e_n_d/HMS/stores-intent/': 'HMS-API-SINTENT',
    '/_b_a_c_k_e_n_d/HMS/stores-intent/create/': 'HMS-API-SINTENT',
    '/_b_a_c_k_e_n_d/HMS/stores-intent/update/.*/': 'HMS-API-SINTENT',
    '/_b_a_c_k_e_n_d/HMS/stores-intent/delete/.*/': 'HMS-API-SINTENTA',
    '/_b_a_c_k_e_n_d/HMS/stores-get_stores_lab_approved_items/': 'HMS-P-SGLA',
    '/_b_a_c_k_e_n_d/HMS/stores-stores_daily_usage_items/?(\?.*)?$': 'HMS-P-SDUI',
    '/_b_a_c_k_e_n_d/HMS/stores-stores_daily_usage_report/?(\?.*)?$': 'HMS-P-SDUI',

    # Vending Machine & Stores Reports:
    '/_b_a_c_k_e_n_d/HMS/vending-machine-sales/': 'HMS-P-SGRN',
    r'^/_b_a_c_k_e_n_d/HMS/vending-machine-sales/?(\?.*)?$': 'HMS-P-SGRN',
    '/_b_a_c_k_e_n_d/HMS/vending-machine-sales/import-excel/': 'HMS-P-SGRN',
    r'^/_b_a_c_k_e_n_d/HMS/vending-machine-sales/import-excel/?(\?.*)?$': 'HMS-P-SGRN',
    '/_b_a_c_k_e_n_d/HMS/vending-machine-report/': 'HMS-P-SGRN',
    r'^/_b_a_c_k_e_n_d/HMS/vending-machine-report/?(\?.*)?$': 'HMS-P-SGRN',
    '/_b_a_c_k_e_n_d/HMS/stores-grn-supplier-report/': 'HMS-P-SGRN',
    r'^/_b_a_c_k_e_n_d/HMS/stores-grn-supplier-report/?(\?.*)?$': 'HMS-P-SGRN',
    '/_b_a_c_k_e_n_d/HMS/stores-indent-department-report/': 'HMS-API-SINTENT',
    r'^/_b_a_c_k_e_n_d/HMS/stores-indent-department-report/?(\?.*)?$': 'HMS-API-SINTENT',


 



    
    # Stores Assets Management:
    '/_b_a_c_k_e_n_d/HMS/stores-assets-management/': 'HMS-API-SAM',               
    r'^/_b_a_c_k_e_n_d/HMS/stores-assets-management/[^/]+/?(\?.*)?$': 'HMS-API-SAM',
    '/_b_a_c_k_e_n_d/HMS/stores-assets-management/.*/': 'HMS-API-SAM',

    # Stores Assets Maintenance & Incharge Assign:
    r'^/_b_a_c_k_e_n_d/HMS/stores-assets-maintenance/?(\?.*)?$': 'HMS-API-AIA',               
    r'^/_b_a_c_k_e_n_d/HMS/stores-assets-maintenance/[^/]+/?(\?.*)?$': 'HMS-API-AIA',
    '/_b_a_c_k_e_n_d/HMS/stores-assets-maintenance/.*/': 'HMS-API-AIA',

    # Asset Maintenance Request & Approval:
    r'^/_b_a_c_k_e_n_d/HMS/asset-maintenance-request/?(\?.*)?$': 'HMS-API-AMR',               
    r'^/_b_a_c_k_e_n_d/HMS/asset-maintenance-request/[^/]+/?(\?.*)?$': 'HMS-API-AMR',
    '/_b_a_c_k_e_n_d/HMS/asset-maintenance-request/.*/': 'HMS-API-AMR',

    #Recycle Assets Management:
    '/_b_a_c_k_e_n_d/HMS/recycle_asset/': 'HMS-API-SRM',               
    r'^/_b_a_c_k_e_n_d/HMS/recycle_asset/[^/]+/?(\?.*)?$': 'HMS-API-SRM',               
    '/_b_a_c_k_e_n_d/HMS/recycle_asset/.*/': 'HMS-API-SRM',   

    # PHARMACY 
         r'^/_b_a_c_k_e_n_d/HMS/patient_details/[^/]+/?(\?.*)?$': 'HMS-P-PPD',
         r'^/_b_a_c_k_e_n_d/HMS/get_pharmacy_stock/[^/]+/?(\?.*)?$': 'HMS-P-PGS',               

        '/_b_a_c_k_e_n_d/HMS/get_pharmacy_stock/': 'HMS-P-PGS',

        '/_b_a_c_k_e_n_d/HMS/save_pharmacy_bill/': 'HMS-P-PSB',
        '/_b_a_c_k_e_n_d/HMS/get_pharmacy_BillType/': 'HMS-P-PGPBT',
        '/_b_a_c_k_e_n_d/HMS/get_estimate_bills/': 'HMS-P-PGEB',
        '/_b_a_c_k_e_n_d/HMS/get_last_billed_uhid/': 'HMS-P-PGLBU',
        

        
         '/_b_a_c_k_e_n_d/HMS/pharmacy_deletebill/': 'HMS-P-PDB',
         '/_b_a_c_k_e_n_d/HMS/pharmacy_medicinechart/': 'HMS-P-PMC',
         '/_b_a_c_k_e_n_d/HMS/substitute_medicine/': 'HMS-P-PSM',
         '/_b_a_c_k_e_n_d/HMS/convert_to_bill/': 'HMS-P-PCB',
         '/_b_a_c_k_e_n_d/HMS/finalize_bill/': 'HMS-P-PFB',
         r'^/_b_a_c_k_e_n_d/HMS/searchby_ip/?(\?.*)?$': 'HMS-P-PSIP',
         '/_b_a_c_k_e_n_d/HMS/ipadvance_bills/': 'HMS-P-CCIPAB',
          '/_b_a_c_k_e_n_d/HMS/pharmacy_view_bills/': 'HMS-P-PHVSB',

         r'/_b_a_c_k_e_n_d/HMS/admissionstatus/?(\?.*)?$': 'HMS-P-PAS',

        #  salesreturn urls
         '/_b_a_c_k_e_n_d/HMS/salesreturn_get_patientdetails/': 'HMS-P-SRGPD',
         '/_b_a_c_k_e_n_d/HMS/get_salesreturn_billdetails/': 'HMS-P-SRBD',
         '/_b_a_c_k_e_n_d/HMS/OP_salesreturn_billdetails/': 'HMS-P-OPSRBD',
          r'/_b_a_c_k_e_n_d/HMS/get_salesreturn_details/?(\?.*)?$': 'HMS-P-PGSRD',


        '/_b_a_c_k_e_n_d/HMS/OPPharmacy_pending_bills/': 'HMS-P-CCOPPB',
        '/_b_a_c_k_e_n_d/HMS/collect_oppharmacy_payment/': 'HMS-P-PCOPP',
        '/_b_a_c_k_e_n_d/HMS/get_active_shift/'         : 'HMS-P-CCGAS',
        '/_b_a_c_k_e_n_d/HMS/cash_counter_shiftdetails/': 'HMS-P-CCSTSD',

        # Central Cash Counter
        '/_b_a_c_k_e_n_d/HMS/cash_counter/': 'HMS-P-CCC',
        '/_b_a_c_k_e_n_d/HMS/cash_counter_manager/': 'HMS-P-CCC',
        '/_b_a_c_k_e_n_d/HMS/get_employee_counter_assignments/': 'HMS-P-CCC',
        '/_b_a_c_k_e_n_d/HMS/assign_employee_cash_counter/': 'HMS-P-CCC',

        '/_b_a_c_k_e_n_d/HMS/get_active_account_heads/': 'HMS-P-CCGAH',
        '/_b_a_c_k_e_n_d/HMS/post_receipt_payments/': 'HMS-P-CCPRP',
        '/_b_a_c_k_e_n_d/HMS/get_receipt_payments/': 'HMS-P-CCGRP',
        '/_b_a_c_k_e_n_d/HMS/get_mainblock_pendingbills/': 'HMS-P-CCGMPB',
        '/_b_a_c_k_e_n_d/HMS/update_mainblock_pendingbills/': 'HMS-P-CCUPB',        
        '/_b_a_c_k_e_n_d/HMS/shift_basis_accounts_report/' : 'HMS-P-CCC',
        '/_b_a_c_k_e_n_d/HMS/bill_wise_report/' : 'HMS-P-CCC',
        '/_b_a_c_k_e_n_d/HMS/get_return_bills/' : 'HMS-P-CCGRB',
        '/_b_a_c_k_e_n_d/HMS/collectpayment_return_bills/' :'HMS-P-CCCRB',

        # Accounts Reports Dashboard
        r'^/_b_a_c_k_e_n_d/HMS/discharge-bills-report/?(\?.*)?$': 'HMS-P-CCC',
        r'^/_b_a_c_k_e_n_d/HMS/advance-registration-report/?(\?.*)?$': 'HMS-P-CCC',
        r'^/_b_a_c_k_e_n_d/HMS/get_shift_summary_report/?(\?.*)?$': 'HMS-P-CCC',
        r'^/_b_a_c_k_e_n_d/HMS/bill-cancel-report/?(\?.*)?$': 'HMS-P-CCC',
        r'^/_b_a_c_k_e_n_d/HMS/credit-card-report/?(\?.*)?$': 'HMS-P-CCC',
        r'^/_b_a_c_k_e_n_d/HMS/datewise-collection-summary/?(\?.*)?$': 'HMS-P-CCC',
        r'^/_b_a_c_k_e_n_d/HMS/miscellaneous-payment-report/?(\?.*)?$': 'HMS-P-CCC',
        r'^/_b_a_c_k_e_n_d/HMS/daily-cash-report/?(\?.*)?$': 'HMS-P-CCC',
        r'^/_b_a_c_k_e_n_d/HMS/debit-bills-report/?(\?.*)?$': 'HMS-P-CCC',
        r'^/_b_a_c_k_e_n_d/HMS/audit-report/?(\?.*)?$': 'HMS-P-CCC',
        r'^/_b_a_c_k_e_n_d/HMS/sales-tax-register/?(\?.*)?$': 'HMS-P-CCC',
        r'^/_b_a_c_k_e_n_d/HMS/stock-report-ip-op/?(\?.*)?$': 'HMS-P-CCC',
        r'^/_b_a_c_k_e_n_d/HMS/SalesReturnReport/?(\?.*)?$': 'HMS-P-CCC',

        #complaints and Tickets
        '/_b_a_c_k_e_n_d/HMS/complaints/': 'HMS-P-CTI',
        r'^/_b_a_c_k_e_n_d/HMS/complaints/admin/?(\\?.*)?$': 'HMS-P-CTIA',
        r'^/_b_a_c_k_e_n_d/HMS/complaints/admin-list/?(\\?.*)?$': 'HMS-P-CTIA',
        r'^/_b_a_c_k_e_n_d/HMS/complaints/(?P<pk>[^/]+)/?$': 'HMS-P-CTI',
        r'^/_b_a_c_k_e_n_d/HMS/complaints/(\\?.*)?$': 'HMS-P-CTI',

        # Company Secretary:

        '/_b_a_c_k_e_n_d/HMS/get_licence_master/': 'HMS-P-CSLM',
        r'/_b_a_c_k_e_n_d/HMS/licence_master_details/?(\\?.*)?$': 'HMS-P-CSLD',
        '/_b_a_c_k_e_n_d/HMS/get_incharge_list/': 'HMS-P-CSIL',
        r'/_b_a_c_k_e_n_d/HMS/licence_renewal/?(\\?.*)?$': 'HMS-P-CSLR',

    #    lab inventory:
     r'/_b_a_c_k_e_n_d/HMS/dealer_items/?(\\?.*)?$': 'HMS-P-LBDI',
     '/_b_a_c_k_e_n_d/HMS/raise_indent/': 'HMS-P-LBRI',

        
        # Vaccination Management & Reminders:
         r'^/_b_a_c_k_e_n_d/HMS/vaccination-masters/.*$': 'HMS-P-HVCC',
        r'^/_b_a_c_k_e_n_d/HMS/add-vaccination-master/.*$': 'HMS-P-HVCC',
        r'^/_b_a_c_k_e_n_d/HMS/update-vaccination-master/.*$': 'HMS-P-HVCC',
        r'^/_b_a_c_k_e_n_d/HMS/delete-vaccination-master/.*$': 'HMS-P-HVCC',
        r'^/_b_a_c_k_e_n_d/HMS/pending-vaccinations/.*$': 'HMS-P-HVCC',
        r'^/_b_a_c_k_e_n_d/HMS/patient-vaccination/.*$': 'HMS-P-HVCC',
        r'^/_b_a_c_k_e_n_d/HMS/save-patient-vaccination/.*$': 'HMS-P-HVCC',
        r'^/_b_a_c_k_e_n_d/HMS/send-vaccination-reminders/.*$': 'HMS-P-HVCC',
        r'^/_b_a_c_k_e_n_d/HMS/preview-vaccination-reminders/.*$': 'HMS-P-HVCC',


        # Master Health Checkup
            r'/_b_a_c_k_e_n_d/HMS/mhc_get_package/?(\\?.*)?$': 'HMS-P-MHPCK',
            r'/_b_a_c_k_e_n_d/HMS/mhc_save_details/?(\\?.*)?$': 'HMS-P-MHPSD',
            r'/_b_a_c_k_e_n_d/HMS/mhc_report/?(\\?.*)?$': 'HMS-P-MHCR',
            r'/_b_a_c_k_e_n_d/HMS/mhc_dashboard/?(\\?.*)?$': 'HMS-P-MHCD',
            '/_b_a_c_k_e_n_d/HMS/mhc_source/': 'HMS-P-MHCS',

        # MRD (Medical Records Department)
        r'/_b_a_c_k_e_n_d/HMS/mrd/discharged-files/?(\\?.*)?$': 'HMS-P-MRD',
        r'/_b_a_c_k_e_n_d/HMS/mrd/update-status/?(\\?.*)?$': 'HMS-P-MRD',
        r'/_b_a_c_k_e_n_d/HMS/mrd/stats/?(\\?.*)?$': 'HMS-P-MRD',

        # OP EMR

        #  Nursing
        r'/_b_a_c_k_e_n_d/HMS/OPEMR_get_billing_patient/?(\\?.*)?$': 'HMS-P-OPEMRGP',
        r'/_b_a_c_k_e_n_d/HMS/OPEMR_VitalEntry/?(\\?.*)?$': 'HMS-P-OPEMRVE',
        r'/_b_a_c_k_e_n_d/HMS/OPEMR_get_vital_history/?(\\?.*)?$': 'HMS-P-OPEMRVE',

        # OPDOCTOR
        '/_b_a_c_k_e_n_d/HMS/OPEMR_get_symptoms/': 'HMS-P-OPEMRGS',
        '/_b_a_c_k_e_n_d/HMS/OPEMR_get_diagnostics_tests/': 'HMS-P-OPEMRGD',
        '/_b_a_c_k_e_n_d/HMS/OPEMR_get_medicines/': 'HMS-P-OPEMRGM',
        r'/_b_a_c_k_e_n_d/HMS/OPEMR_DoctorConsultation/?(\\?.*)?$': 'HMS-P-OPEMRDC',
        '/_b_a_c_k_e_n_d/HMS/OPEMR_get_referral_doctors': 'HMS-P-OPEMRD',


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



