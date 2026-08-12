from django.urls import path, re_path
from . import views
from .Views import (
    admission,
    departmentBilling,
    discharge,
    doctormaster,
    ICD11,
    inventory,
    medicine_requisition,
    stocktransfer,
    chandra_ocr,
    package_crud,
    pharmacy,
    cashcounter,
    radiology,
    jrdReport,
    room,
    pharmacynotification,
    NursingStation,
    dashboard,
    advanced_dashboard,
    doctor_dashboard,
    insurance_provider,
    summary,
    investigation_price,
    billType,
    velavan,
    otMaster,
    anesthesia,
    surgeryschedule,
    customer_type,
    doctor_reports,
    DietOrder,
    purchasereturn,
    purchase_order,
    Purchase_Requisition,
    front_office_reports,
    registration_updates,
    laundry,
    physicalstockentry,
    salesreturn,
    medicine_package,
    companysecretary,
    communication,
    hr,
    labinventory,
    abdm_integration,
    abdm_m1,
    abdm_m2_hip,
    DoctorFeeCuts,
    vaccination,
)
from .Views.AccountsReport import (
    shift_basis_report,
    cash_counter_manager,
    bill_wise_report,
    accounting_reports,
)
from .Views.Stores import stores
from .Views.Assets import assets
from .Views.Insurance import insurance
from .Views.Reports import roomoccupencyreport, marketing_reports, salesreturnreport
from .Views.Complaints import complaints
from .Views.QRScan import qrscan


handler404 = 'hospital.views.custom_page_not_found'

urlpatterns = [
    # Crash Cart URLs
    path('crash-cart/items/', NursingStation.get_crash_cart_items, name='get_crash_cart_items'),
    path('crash-cart/daily-check/', NursingStation.save_crash_cart_daily_check, name='save_crash_cart_daily_check'),
    path('crash-cart/monthly-report/', NursingStation.get_crash_cart_monthly_report, name='get_crash_cart_monthly_report'),

    # Admission URLs
    path('autoipNumber/', admission.get_next_ip_number, name='get_next_ip_number'), 
    path('admission/', admission.admission_view, name='admission'),
    path('admission/<str:uhid>/', admission.admission_detail, name='admission_detail'), 
    path('search-rooms/', admission.search_rooms, name='search-rooms'), 
    path('admission/<path:ipNumber>/', admission.admission_detail, name='admission_detail'),
    path('admission-list/', admission.admission_view, name='admission'),
    path('admission-detail/<str:uhid>/', admission.admission_detail, name='admission_detail'), 
    path('admission-room-search/', admission.search_rooms, name='search-rooms'), 
    path('admission-detail/<path:ipNumber>/', admission.admission_detail, name='admission_detail'),
    path('admission-advance/', admission.admission_advance, name='admission_advance_list'),
    path('admission-advance/<path:ipNumber>/', admission.admission_advance, name='admission_advance_detail'),
    
    # Inventory URLs
    # Vendor URLs
    path("vendors/", inventory.vendor_view, name="vendor-list"),
    path("vendors/<str:pk>/", inventory.vendor_view, name="vendor-detail"),
    path("general-store-vendors/", stores.general_store_vendor_list_create, name="general-store-vendor-list-create"),
    path("general-store-vendors/<str:pk>/", stores.general_store_vendor_detail, name="general-store-vendor-detail"),

    # Stock URLs (Supporting both dash and underscore formatting if referenced across platforms)
    path("pharmacy-items/", inventory.pharmacy_item_view, name="pharmacy-item-list"),
    path("pharmacy-items/<int:pk>/", inventory.pharmacy_item_view, name="pharmacy-item-detail"),
    path("pharmacy_items/", inventory.pharmacy_item_view, name="pharmacy-item-list-alt"),
    path("pharmacy_items/<int:pk>/", inventory.pharmacy_item_view, name="pharmacy-item-detail-alt"),
    path("get_pharmacy_item_tracking/", inventory.get_pharmacy_item_tracking, name="get_pharmacy_item_tracking"),

    # Pharmacy Category URLs
    path("pharmacy-category/", inventory.pharmacycategory_view, name="pharmacy-category-list"),
    path("pharmacy-category/<int:pk>/", inventory.pharmacycategory_view, name="pharmacy-category-detail"),

    # Chemical Composition URLs
    path("chemical-composition/", inventory.chemical_composition_view, name="chemical-composition-list"),
    path("chemical-composition/<int:pk>/", inventory.chemical_composition_view, name="chemical-composition-detail"),

    path('get_pharmacy_stock/', pharmacy.get_pharmacy_stock, name='get_pharmacy_stock'),
    path('save_pharmacy_bill/', pharmacy.save_pharmacy_bill, name='save_pharmacy_bill'),
    path('get_pharmacy_BillType/', pharmacy.get_pharmacy_BillType, name='get_pharmacy_BillType'),
    path('get_estimate_bills/', pharmacy.get_estimate_bills, name='get_estimate_bills'),
    path('get_last_billed_uhid/', pharmacy.get_last_billed_uhid, name='get_last_billed_uhid'),
    path('pharmacy_view_bills/', pharmacy.pharmacy_view_bills, name='pharmacy_view_bills'),
    path('collect_oppharmacy_payment/', pharmacy.collect_oppharmacy_payment, name='collect_oppharmacy_payment'),
    path('pharmacy_deletebill/', pharmacy.pharmacy_deletebill, name='pharmacy_deletebill'),
    path('pharmacy_medicinechart/', pharmacy.pharmacy_medicinechart, name='pharmacy_medicinechart'),
    path('admissionstatus/', pharmacy.admissionstatus, name='admissionstatus'),
    path('patient_details/', pharmacy.patient_details, name='patient_details'),
    path("substitute_medicine/", pharmacy.substitute_medicine),
    path("convert_to_bill/", pharmacy.convert_to_bill),
    path("finalize_bill/", pharmacy.finalize_bill),
    path("cashcounter_outlet/", pharmacy.cashcounter_outlet),
    path('searchby_ip/', pharmacy.searchby_ip, name='searchby_ip'),

    
    # GRN URLs
    path('grn/', inventory.grn_view, name='grn_list'),
    re_path(r'^grn/(?P<pk>.+)/$', inventory.grn_view, name='grn_detail'),
    path("pharmacy_stock_history/", inventory.pharmacy_stock_history, name="pharmacy_stock_history"),
    path("grn-ocr/", chandra_ocr.grn_ocr_scan, name="grn_ocr_scan"),

    # Stock Transfer URLs
    path('get_active_outlets/', stocktransfer.get_active_stock_outlets, name='get_active_stock_outlets'),
    re_path(r'^_b_a_c_k_e_n_d/HMS/pharmacy-stock/?$', stocktransfer.pharmacy_stock_view, name='pharmacy-stock'),
    re_path(r'^_b_a_c_k_e_n_d/HMS/pharmacy-stock/(?P<pk>\d+)/?$', stocktransfer.pharmacy_stock_view, name='pharmacy-stock-detail'),
    path('stock-transfer/', stocktransfer.stock_transfer_view, name='stock_transfer_list'),
    path("stock-transfer-action/", stocktransfer.stock_transfer_action_view, name="stock_transfer_action"),

    path("purchase-return/", purchasereturn.purchase_return_view, name="purchase-return-list"),
    path("purchase-return/<str:pk>/", purchasereturn.purchase_return_view, name="purchase-return-detail"),
    path("grn-items/", purchasereturn.get_grn_items, name="grn-items"),

    path("medicine-requisition/", medicine_requisition.medicine_requisition_view, name="medicine_requisition_list"),
    path("medicine-requisition/<path:pk>/", medicine_requisition.medicine_requisition_view, name="medicine_requisition_detail"),
    path("medicine-requisition-action/", medicine_requisition.medicine_requisition_action_view, name="medicine_requisition_action"),

    path("purchase-order/", purchase_order.purchase_order_view, name="purchase_order_list"),
    path("purchase-order/<path:pk>/", purchase_order.purchase_order_view, name="purchase_order_detail"),
    path("purchase-order-action/", purchase_order.purchase_order_action_view, name="purchase_order_action"),
    path("purchase-order-email/", purchase_order.purchase_order_email_view, name="purchase_order_email"),

    # Purchase Requisition
    path("purchase-requisition/", Purchase_Requisition.purchase_requisition_view, name="purchase_requisition_list"),
    path("purchase-requisition/<str:pk>/", Purchase_Requisition.purchase_requisition_view, name="purchase_requisition_detail"),
    path("purchase-requisition-action/", Purchase_Requisition.purchase_requisition_action_view, name="purchase_requisition_action"),
    path("pharmacy-stock-batches/", physicalstockentry.pharmacy_stock_batches_view, name="pharmacy-stock-batches"),
 
    # Physical stock entry CRUD
    path("physical-stock-entry/", physicalstockentry.physical_stock_entry_view, name="physical-stock-entry-list"),
    path("physical-stock-entry/<int:pk>/", physicalstockentry.physical_stock_entry_view, name="physical-stock-entry-detail"),
 
    # Approval
    path("physical-stock-approval/", physicalstockentry.physical_stock_approval_view, name="physical-stock-approval-list"),
    path("physical-stock-approval/<int:pk>/", physicalstockentry.physical_stock_approval_view, name="physical-stock-approval-detail"),

    path('medicine-tracking/', inventory.medicine_tracking, name='medicine_tracking'),
    path('pharmacy/notifications/', pharmacynotification.pharmacy_notifications, name='pharmacy-notifications'),
    path('pharmacy_expiry_report/', pharmacy.pharmacy_expiry_report, name='pharmacy_expiry_report'),

    path('get_pharmacy_BillType/', pharmacy.get_pharmacy_BillType, name='get_pharmacy_BillType'),
    path('get_estimate_bills/', pharmacy.get_estimate_bills, name='get_estimate_bills'),
    path('get_last_billed_uhid/', pharmacy.get_last_billed_uhid, name='get_last_billed_uhid'),
    path('pharmacy_view_bills/', pharmacy.pharmacy_view_bills, name='pharmacy_view_bills'),
    
    path('collect_oppharmacy_payment/', pharmacy.collect_oppharmacy_payment, name='collect_oppharmacy_payment'),
    path('pharmacy_deletebill/', pharmacy.pharmacy_deletebill, name='pharmacy_deletebill'),
    path('pharmacy_medicinechart/', pharmacy.pharmacy_medicinechart, name='pharmacy_medicinechart'),
    path('admissionstatus/', pharmacy.admissionstatus, name='admissionstatus'),
    path('patient_details/', pharmacy.patient_details, name='patient_details'),
    path("substitute_medicine/", pharmacy.substitute_medicine),
    path("convert_to_bill/", pharmacy.convert_to_bill),
    path("finalize_bill/", pharmacy.finalize_bill),
    path("cashcounter_outlet/", pharmacy.cashcounter_outlet),
    path('searchby_ip/', pharmacy.searchby_ip, name='searchby_ip'),

    # Central Cash Counter
    path('cash_counter_shiftdetails/', cashcounter.cash_counter_shiftdetails, name='cash_counter_shiftdetails'),
    path('get_active_shift/', cashcounter.get_active_shift, name='get_active_shift'),
    path('get_shift_summary_report/', cashcounter.get_shift_summary_report, name='get_shift_summary_report'),
    path('get_active_account_heads/', cashcounter.get_active_account_heads, name='get_active_account_heads'),
    path('post_receipt_payments/', cashcounter.post_receipt_payments, name='post_receipt_payments'),
    path("get_receipt_payments/", cashcounter.get_receipt_payments),
    path("ipadvance_bills/", cashcounter.ipadvance_bills),
    path("get_mainblock_pendingbills/", cashcounter.get_mainblock_pendingbills),
    path("update_mainblock_pendingbills/", cashcounter.update_mainblock_pendingbills),
    path("get_registration_bills/", cashcounter.get_registration_bills),
    path('OPPharmacy_pending_bills/', cashcounter.OPPharmacy_pending_bills, name='OPPharmacy_pending_bills'),
     path('collectpayment_return_bills/', cashcounter.collectpayment_return_bills, name='collectpayment_return_bills'),

    # Medicine Package Master
    path('medicine-packages/', medicine_package.get_medicine_packages, name='get_medicine_packages'),
    path('medicine-packages/create/', medicine_package.create_medicine_package, name='create_medicine_package'),
    path('medicine-packages/<str:pkg_id>/', medicine_package.get_medicine_package, name='get_medicine_package'),
    path('medicine-packages/update/<str:pkg_id>/', medicine_package.update_medicine_package, name='update_medicine_package'),
    path('medicine-packages/delete/<str:pkg_id>/', medicine_package.delete_medicine_package, name='delete_medicine_package'),
    path('pharmacy-items-pkg/', medicine_package.get_pharmacy_items, name='get_pharmacy_items_pkg'),

    # Room URLs
    path('block/', room.block_view, name='block_list_create'),
    path('block/<int:pk>/', room.block_view, name='block_update_delete'),
    path('room-category/', room.room_category_view, name='room_category_list_create'),
    path('room-category/<str:pk>/', room.room_category_view, name='room_category_update_delete'),
    path('nursingstation/', room.nursingstation_view, name='nursingstation_list_create'),
    path('nursingstation/<str:pk>/', room.nursingstation_view, name='nursingstationupdate_delete'),
    path('roomservice-description/', room.room_service_description_view, name='room_service_description_view_list_create'),
    path('roomservice-description/<str:pk>/', room.room_service_description_view, name='room_service_description_view_update_delete'),
    path('room-kititems/', room.room_kititems_view, name='room_kititems_list_create'),
    path('room-kititems/<str:pk>/', room.room_kititems_view, name='room_kititems_update_delete'),
    path('room/', room.room_view, name='room_list_create'),
    path('room/<str:pk>/', room.room_view, name='room_update_delete'),
    path("room-enquiry/", room.room_enquiry_view, name="room_enquiry"),
    path("update-room-cleaned/", room.update_room_cleaned_view, name="update_room_cleaned"),
    path("book-room/", room.book_room_view, name="book_room"),
    path('get_active_admission/', room.get_active_admission, name='get_active_admission'), 
    path("room-shifting/", room.room_shifting_view, name="room_shifting"),
    path("room-shifting/<path:ip_number>/update/", room.room_shifting_detail_view, name="room_shifting_detail"),

    # Discharge URLs
    path("search-discharge-patient/", discharge.search_discharge_patient, name="search-discharge-patient"),
    path("discharge-billing/", discharge.discharge_billing_list_create, name="discharge-billing-list-create"),
    path("discharge-billing/<str:pk>/", discharge.discharge_billing_detail, name="discharge-billing-detail"),
    path("discharge-billing/<str:pk>/convert-to-bill/", discharge.convert_estimate_to_bill, name="discharge-billing-convert"),
    path("dialysis-discharge-summary/", discharge.create_dialysis_discharge_summary, name="dialysis-discharge-summary"),
    path('dialysis_patient_details/', discharge.dialysis_patient_details, name='dialysis_patient_details'),

    # Patient URLs
    path('patients/register/', views.patientCreateView, name='patient-register'),
    path('create/', views.patientCreateView, name='patient-list'),
    path('get-last-uhid/', views.get_last_uhid, name='get_last_uhid'),
    path('patient-registration-stats/', views.patient_registration_stats, name='patient_registration_stats'),
    path('patient-visit-list/', views.patient_visit_list, name='patient_visit_list'),
    path('generate-qr-session/', views.generate_qr_session, name='generate_qr_session'),
    path('submit-qr-registration/', views.submit_qr_registration, name='submit_qr_registration'),
    path('check-qr-status/', views.check_qr_status, name='check_qr_status'),
    path('get-pending-qr-registrations/', views.get_pending_qr_registrations, name='get_pending_qr_registrations'),
    path('consume-qr-registration/', views.consume_qr_registration, name='consume_qr_registration'),
    path('add-reference-doctor/', views.save_reference_doctor, name='save_reference_doctor'),
    path('get-reference-doctors/', views.get_reference_doctors, name='get_reference_doctors'),

    # Customer Type URLs
    path('customer-types/', customer_type.customer_type_list, name='customer_type_list'),
    path('customer-types/<int:pk>/', customer_type.customer_type_detail, name='customer_type_detail'),

    # Radiology Reports
    path('investigations/', radiology.get_investigations, name='get_investigations'),
    path('scan-reports/', radiology.create_scan_report, name='create_scan_report'),  
    path('hard-bill-types/', radiology.get_hard_bill_types, name='get_hard_bill_types'),  
    re_path(r'^scan-reports/slot/(?P<investBillNo>.+)/(?P<item_id>.+)/$', radiology.update_slot_datetime, name='update_slot_datetime'),   
    re_path(r'^scan-reports/approve/(?P<investBillNo>.+)/(?P<item_id>.+)/$', radiology.approve_scan_report, name='approve_scan_report'),
    re_path(r'^scan-reports/delete/(?P<investBillNo>.+)/(?P<item_id>.+)/$', radiology.soft_delete_scan_report, name='soft_delete_scan_report'),
    re_path(r'^scan-reports/edit/(?P<investBillNo>.+)/(?P<item_id>.+)/$', radiology.edit_scan_report_impression, name='edit_scan_report_impression'),
    re_path(r'^scan-reports/checkin/(?P<investBillNo>.+)/(?P<item_id>.+)/$', radiology.patient_checkin, name='patient_checkin'),
    re_path(r'^scan-reports/scan-started/(?P<investBillNo>.+)/(?P<item_id>.+)/$', radiology.scan_started, name='scan_started'),
    re_path(r'^scan-reports/dispatch/(?P<investBillNo>.+)/(?P<item_id>.+)/$', radiology.dispatch_report, name='dispatch_report'),
    path('scan-reports/format/', radiology.get_radiology_format, name='get_radiology_format'),  
    path('employee-signature/', radiology.get_employee_signature_by_id, name='employee-signature'),  

    # JRD Reports
    path('anc-register/', jrdReport.get_anc_register, name='get_anc_register'),
    path('jrd-reports/', jrdReport.list_jrd_reports, name='jrd_list'),
    path('jrd-reports/create/', jrdReport.create_jrd_report, name='jrd_create'),
    re_path(r'^jrd-reports/update/(?P<jrd_id>\d+)/$', jrdReport.update_jrd_report, name='update_jrd_report'),
    re_path(r'^jrd-reports/delete/(?P<jrd_id>\d+)/$', jrdReport.delete_jrd_report, name='delete_jrd_report'),
    
    # Summary
    path('summaries/', summary.get_summaries, name='get_summaries'),
    path('summary-type/', summary.summary_type, name='summary_type'),
    path('summaries/create/', summary.create_summary, name='create_summary'),   
    re_path(r'^approve-summary/(?P<ip_no>.+)/$', summary.approve_summary, name='approve_summary'),
    re_path(r'^delete-summary/(?P<ip_no>.+)/$', summary.delete_summary, name='delete_summary'),
    re_path(r'^get-editsummary/(?P<ip_no>.+)/$', summary.get_editsummary, name='get_editsummary'),
    re_path(r'^update-summary/(?P<ip_no>.+)/$', summary.update_summary_fields, name='update_summary_fields'),
    re_path(r'^patient-investigations/(?P<ip_no>[\w%/-]+)/$', summary.get_patient_investigations, name='get_patient_investigations'),
    re_path(r'^get-printsummary/(?P<ip_no>.+)/$', summary.get_printsummary, name='get_printsummary'),
    re_path(r'^patient-medicines/(?P<ip_no>.+)/$', summary.get_patient_medicines, name='get_patient_medicines'),
    re_path(r'^patient-discharge-medicines/(?P<ip_no>.+)/$', summary.get_patient_discharge_medicines, name='get_patient_discharge_medicines'),
    path('upload-pdf/', communication.upload_pdf_to_gridfs, name='upload_pdf_to_gridfs'),
    re_path(r'^get-file/(?P<file_id>.+)/$', communication.get_pdf_from_gridfs, name='get_pdf_from_gridfs'),
    path('send-whatsapp/', communication.send_whatsapp, name='send_whatsapp'),
    path('send-email/', communication.send_email, name='send_email'),
    path('communication-logs/', communication.get_communication_logs, name='get_communication_logs'),

    # ICD11
    path("icd11/search/", ICD11.icd11_search, name='icd11_search'),
    path("icd11/entity/<str:entity_id>/", ICD11.icd11_detail),

    # Investigation Billing
    re_path(r'^op-patient/(?P<uhid>[\w%/-]+)/$', departmentBilling.op_patient_detail_by_uhid, name='op-patient-detail-by-uhid'),
    re_path(r'^ip-patient/(?P<ipNumber>[\w%/-]+)/$', departmentBilling.ip_patient_detail_by_ipNumber, name='ip-patient-detail-by-ipNumber'),  
    path('bill-types/', departmentBilling.get_bill_types, name='get_bill_types'),  
    path('invest-bill-types/', departmentBilling.get_invest_bill_types, name='get_invest_bill_types'),  
    path('packages/', departmentBilling.get_packages, name='get_packages'),
    path('package-items/', departmentBilling.get_package_items, name='get_package_items'),
    path('investigation-items/', departmentBilling.get_investigation_items, name='get_investigation_items'),
    path('investBilling/', departmentBilling.invest_billing_create, name='invest-billing-create'),
    path('investBillingGet/', departmentBilling.billing_report_view, name='billing_report_view'),
    path('estimateBilling/', departmentBilling.estimate_billing_create, name='estimate_billing_create'),
    path('get-estimate-billings/', departmentBilling.estimate_billing_list, name='estimate-billing-list'),
    path('delete-bill/', departmentBilling.delete_bill_view, name='delete_bill_view'),
    path('invest-refund/', departmentBilling.invest_refund_create, name='invest_refund_create'),

    # Doctor Master
    path('doctor_list_diagnostics/', doctormaster.doctor_list_from_diagnostics, name='doctor_list_diagnostics'), 
    path('doctor_schedule/', doctormaster.doctor_schedule_list, name='doctor_schedule_list'),
    path('doctor_schedule/<str:employee_id>/', doctormaster.doctor_schedule_detail, name='doctor_schedule_detail'),
    path('doctor_schedule_upsert/<str:employee_id>/', doctormaster.doctor_schedule_upsert, name='doctor_schedule_upsert'),

    # Nursing Station / Ward Requests
    path("wardrequest/", NursingStation.get_admission_list, name="wardrequest"),
    path("update_admission_status/", NursingStation.update_admission_status, name="update_admission_status"),
    path("location-mapping/", NursingStation.get_location_mapping, name="location-mapping"),
    path("get_wards_list/", NursingStation.get_wards_list, name="get_wards_list"),
    path("uhidadmissionstatus/", NursingStation.uhidadmissionstatus, name="uhidadmissionstatus"),
    path("get_LabBillType_list/", NursingStation.get_LabBillType_list, name="get_LabBillType_list"),
    path("get_lab_ward_requests/", NursingStation.get_lab_ward_requests, name="get_lab_ward_requests"),
    path("save_lab_ward_request/", NursingStation.save_lab_ward_request, name="save_lab_ward_request"),
    path("cancel_lab_ward_request/", NursingStation.cancel_lab_ward_request, name="cancel_lab_ward_request"),
    path("remove_individual_test/", NursingStation.remove_individual_test_from_lab_ward_request, name="remove_individual_test"),
    path("get_medicine_ward_requests/", NursingStation.get_medicine_ward_requests, name="get_medicine_ward_requests"),
    path("save_medicine_ward_request/", NursingStation.save_medicine_ward_request, name="save_medicine_ward_request"),
    path("return_medicine_ward_request/", NursingStation.return_medicine_ward_request, name="return_medicine_ward_request"),
    path("get_pending_ward_returns/", NursingStation.get_pending_ward_returns, name="get_pending_ward_returns"),
    path("approve_ward_return/", NursingStation.approve_ward_return, name="approve_ward_return"),
    path("update_medicine_ward_request/", NursingStation.update_medicine_ward_request, name="update_medicine_ward_request"),
    path("cancel_medicine_ward_request/", NursingStation.cancel_medicine_ward_request, name="cancel_medicine_ward_request"),
    path("remove_individual_medicine/", NursingStation.remove_individual_medicine_from_ward_request, name="remove_individual_medicine"),
    path("get_radiology_ward_requests/", NursingStation.get_radiology_ward_requests, name="get_radiology_ward_requests"),
    path("save_radiology_ward_request/", NursingStation.save_radiology_ward_request, name="save_radiology_ward_request"),
    path("cancel_radiology_ward_request/", NursingStation.cancel_radiology_ward_request, name="cancel_radiology_ward_request"),
    path("remove_individual_radiology/", NursingStation.remove_individual_test_from_radiology_ward_request, name="remove_individual_radiology"),
    path("dosage_master/", NursingStation.dosage_master_view, name="dosage_master"),
    
    # Package Master
    path('investigation-prices/', package_crud.get_bill_types, name='get_bill_types'),
    path('lab-items/', package_crud.get_lab_items, name='get_lab_items'),
    path('outlets/', package_crud.get_outlets, name='get_outlets'),
    path('packages_crud/', package_crud.get_packages, name='get_packages'),
    path('packages/create/', package_crud.create_package, name='create_package'),
    path('packages/<int:package_no>/', package_crud.get_package, name='get_package'),
    path('packages/update/<int:package_no>/', package_crud.update_package, name='update_package'),
    path('packages/delete/<int:package_no>/', package_crud.delete_package, name='delete_package'),

    # Investigation Price Master
    path('investigation-prices_get/', investigation_price.get_investigation_prices, name='get_investigation_prices'),
    path('investigation-prices/create/', investigation_price.create_investigation_price, name='create_investigation_price'),
    path('investigation-prices/update/<str:bill_type_no>/', investigation_price.update_investigation_price, name='update_investigation_price'),
    path('investigation-prices/delete/<str:bill_type_no>/', investigation_price.delete_investigation_price, name='delete_investigation_price'),
    path('investigation-prices/update_item/<str:bill_type_no>/<int:item_id>/', investigation_price.update_investigation_item, name='update_investigation_item'),
    path('investigation-prices/delete_item/<str:bill_type_no>/<int:item_id>/', investigation_price.delete_investigation_item, name='delete_investigation_item'),

    # Bill Type Master
    path('bill-types_get/', billType.get_bill_types, name='get_bill_types'),
    path('bill-types/create/', billType.create_bill_type, name='create_bill_type'),
    path('bill-types/update/<int:bill_type_int>/', billType.update_bill_type, name='update_bill_type'),
    path('bill-types/delete/<int:bill_type_int>/', billType.delete_bill_type, name='delete_bill_type'),
    path('investigation-price/patch-bill-type/', billType.patch_bill_type_prices, name='patch_bill_type_prices'),

    # Reports
    path('dept-budr/', departmentBilling.dept_budr_view, name='dept_budr_view'),
    path('doctor-report/', doctor_reports.doctor_report_view, name='doctor_report_view'),
    path('front-office-reports/', front_office_reports.front_office_report_view, name='front_office_reports'),
    path('RoomOccupencyReport/', roomoccupencyreport.room_occupancy_report_view, name='room_occupancy_report'),
    path('PreDayRoomOccupancyReport/', roomoccupencyreport.previous_day_room_occupancy_view, name='pre_day_room_occupancy_report'),
    path('SalesReturnReport/', salesreturnreport.sales_return_report_view, name='sales_return_report'),
    path('marketing-area-zipcode-report/', marketing_reports.marketing_area_zipcode_report, name='marketing_area_zipcode_report'),

    # Velavan Items
    path('velavan_items/list/', velavan.list_items, name='list_items'),
    path('velavan_get_items/', velavan.velavan_get_items, name='velavan_get_items'),
    path('velavan_create_item/', velavan.velavan_create_item, name='velavan_create_item'),
    path('velavan_update_item/<str:item_id>/', velavan.velavan_update_item, name='velavan_update_item'),
    path('velavan_delete_item/<str:item_id>/', velavan.velavan_delete_item, name='velavan_delete_item'),
    
    # Velavan Vendor
    path('velavan_vendors/list/', velavan.list_vendors, name='list_vendors'),
    path('velavan_get_vendors/', velavan.velavan_get_vendors, name='velavan_get_vendors'),
    path('velavan_create_vendor/', velavan.velavan_create_vendor, name='velavan_create_vendor'),
    path("velavan_update_vendor/<str:vendor_id>/", velavan.velavan_update_vendor, name="velavan_update_vendor"),
    path("velavan_delete_vendor/<str:vendor_id>/", velavan.velavan_delete_vendor, name="velavan_delete_vendor"),

    # Velavan Invoice
    path('velavan/invoices/', velavan.create_velavan_in, name='create_velavan_in'),
    path('velavan/invoices/list/', velavan.list_velavan_invoices, name='list_velavan_invoices'),
    path('velavan/previous-purchases/', velavan.get_previous_purchases, name='previous_purchases'),
    path('velavan/invoices/update/<path:grn_number>/', velavan.update_velavan_invoice, name='update_velavan_invoice'),  
    path('velavan/invoices/approve/<path:grn_number>/', velavan.approve_velavan_invoice, name='approve_velavan_invoice'), 
    re_path(r'^vel-ip-patient/(?P<ipNumber>[\w%/-]+)/$', velavan.get_ip_patient, name='get_ip_patient'),  
    path('velavan/purchase-return/', velavan.create_velavan_purchase_return, name='create_velavan_purchase_return'),
    path('velavan/purchase-return/list/', velavan.list_velavan_purchase_returns, name='list_velavan_purchase_returns'),
    
    # Velavan Sales
    path('velavan/sales/', velavan.create_velavan_sale, name='create_velavan_sale'),
    path('velavan/sales/list/', velavan.list_velavan_sales, name='list_velavan_sales'),
    path('velavan/stock/list/', velavan.velavan_get_stock, name='velavan_get_stock'),
    path('velavan/stock/search/', velavan.velavan_search_stock, name='velavan_search_stock'),
    path('velavan/stock/by-grn/', velavan.velavan_stock_by_grn, name='velavan_stock_by_grn'),
    path('velavan/sales-return/', velavan.create_velavan_sales_return, name='create_velavan_sales_return'),
    path('velavan/sales-return/list/', velavan.list_velavan_sales_returns, name='list_velavan_sales_returns'),
     #Velavan Customers:
    path('velavan_customers/list/', velavan.velavan_get_customers, name='velavan_get_customers'),
    path('velavan_create_customer/', velavan.velavan_create_customer, name='velavan_create_customer'),
    path('velavan_update_customer/<str:customer_id>/', velavan.velavan_update_customer, name='velavan_update_customer'),
    path('velavan_delete_customer/<str:customer_id>/', velavan.velavan_delete_customer, name='velavan_delete_customer'),

    # Dashboard URLs
    path('dashboard/stats/', dashboard.dashboard_stats, name='dashboard_stats'),
    path('advanced-dashboard/stats/', advanced_dashboard.advanced_dashboard_stats, name='advanced_dashboard_stats'),
    path('doctor-dashboard/stats/', doctor_dashboard.doctor_dashboard_stats, name='doctor_dashboard_stats'),

    # User Permissions (Dynamic Table)
    path('user-permissions/', views.get_user_permissions, name='get_user_permissions'),
    path('update-user-permissions/', views.update_user_permissions, name='update_user_permissions'),
    path('get-all-employees/', views.get_all_employees, name='get_all_employees'),
    path('registration-bills/', views.registration_bills, name='registration_bills'),
    re_path(r'^update-bill-status/(?P<bill_number>.+)/$', views.update_bill_status, name='update_bill_status'),
    path('update-registration-visit/', registration_updates.update_registration_visit, name='update_registration_visit'),
    path('process-registration-refund/', registration_updates.process_registration_refund, name='process_registration_refund'),
    path('get-sidebar-mapping/', views.get_sidebar_mapping, name='get_sidebar_mapping'),
    path('update-sidebar-mapping/', views.update_sidebar_mapping, name='update_sidebar_mapping'),
    path('get-all-outlets/', views.get_all_outlets, name='get_all_outlets'),
    
    # Insurance Provider URLs
    path('insurance-providers/', insurance_provider.insurance_provider_list_create, name='insurance_provider_list_create'),
    path('insurance-providers/<str:pk>/', insurance_provider.insurance_provider_detail, name='insurance_provider_detail'),
  
    # Stores URLs
    path('item-master/', stores.item_master_list_create, name='item_master_list_create'),
    path('item-master/price-history/<str:item_id>/', stores.item_price_history, name='item_price_history'),
    path('item-master/<str:pk>/', stores.item_master_detail, name='item_master_detail'),
    path('department-master/', stores.department_list_create, name='department_list_create'),
    path('department-master/<str:pk>/', stores.department_detail, name='department_detail'),
    path('group-master/', stores.group_list_create, name='group_list_create'),
    path('group-master/<str:pk>/', stores.group_detail, name='group_detail'),
    path('category-master/', stores.category_list_create, name='category_list_create'),
    path('category-master/<str:pk>/', stores.category_detail, name='category_detail'),
    path('group-type-master/', stores.group_type_list_create, name='group_type_list_create'),
    path('group-type-master/<str:pk>/', stores.group_type_detail, name='group_type_detail'),
    path('stores-grn/', stores.stores_grn_list_create, name='stores_grn_list_create'),
    path('stores-grn/<str:pk>/', stores.stores_grn_detail, name='stores_grn_detail'),
    path('stores-intent/', stores.get_stores_intents, name='get_stores_intents'),
    path('stores-intent/create/', stores.create_stores_intent, name='create_stores_intent'),
    path('stores-intent/update/<str:pk>/', stores.update_stores_intent, name='update_stores_intent'),
    path('stores-intent/delete/<str:pk>/', stores.soft_delete_intent, name='soft_delete_intent'),
    path('stores-get_stores_lab_approved_items/', stores.get_stores_lab_approved_items, name='get_stores_lab_approved_items'),
    path('stores-stores_daily_usage_items/', stores.stores_daily_usage_items, name='stores_daily_usage_items'),
    path('stores-stores_daily_usage_report/', stores.stores_lab_used_qty_report, name='stores_lab_used_qty_report'),
    

    # Assets Master
    path('stores-assets-management/', assets.stores_assets_management_list_create, name='stores_assets_management_list_create'),
    path('stores-assets-management/<path:pk>/', assets.stores_assets_management_detail, name='stores_assets_management_detail'),
    path('stores-assets-maintenance/', assets.stores_assets_maintenance_details, name='stores_assets_maintenance_details'),
    path('stores-assets-maintenance/<path:pk>/', assets.stores_assets_maintenance_details, name='stores_assets_maintenance_details'),
    path('asset-maintenance-request/', assets.asset_maintenance_request_list_detail, name='asset_maintenance_request_list_detail'),
    path('asset-maintenance-request/<path:pk>/', assets.asset_maintenance_request_list_detail, name='asset_maintenance_request_detail'),
    path("recycle_asset/", assets.create_recycle_asset, name="create_recycle_asset"),
    path("recycle_asset/<path:pk>/", assets.update_recycle_asset, name="update_recycle_asset"),

    # OT Master
    path('create_ot/', otMaster.create_ot, name='create_ot'),
    path('list_ots/', otMaster.list_ots, name='list_ots'),
    path('update_ot/<str:ot_id>/', otMaster.update_ot, name='update_ot'),
    path('delete_ot/<str:ot_id>/', otMaster.delete_ot, name='delete_ot'), 

    # Anesthesia Master
    path('create_anes/', anesthesia.create_anes, name='create_anes'),
    path('list_anes/', anesthesia.list_anes, name='list_anes'),
    path('update_anes/<str:anesthesia_id>/', anesthesia.update_anes, name='update_anes'),
    path('delete_anes/<str:anesthesia_id>/', anesthesia.delete_anes, name='delete_anes'), 

    # Surgery Schedule
    path("create_surgery_schedule/", surgeryschedule.create_surgery_schedule, name='create_surgery_schedule'),
    path("list_surgery_schedules/", surgeryschedule.list_surgery_schedules, name='list_surgery_schedules'),
    path("ot_staffs/", surgeryschedule.ot_staffs, name='ot_staffs'),
    path("get_surgery_schedule/", surgeryschedule.get_surgery_schedule, name='get_surgery_schedule'),
    path("update_surgery_schedule/", surgeryschedule.update_surgery_schedule, name='update_surgery_schedule'),
    path("cancel_surgery_schedule/", surgeryschedule.cancel_surgery_schedule, name='cancel_surgery_schedule'),
    path("update_schedule_status/", surgeryschedule.update_schedule_status, name='update_schedule_status'),
    path("list_diagnosis/", surgeryschedule.list_diagnosis, name='list_diagnosis'),    
    path("get_ot_medicine_ward_requests/", surgeryschedule.get_ot_medicine_ward_requests, name="get_ot_medicine_ward_requests"),
    path('get_pharmacy_items/', surgeryschedule.get_pharmacy_items, name='get_pharmacy_items'),
    path('get_medicine_packages/', surgeryschedule.get_medicine_packages, name='get_medicine_packages'),
    path("save_ot_medicine_ward_request/", surgeryschedule.save_ot_medicine_ward_request, name="save_ot_medicine_ward_request"),
    path("update_ot_medicine_ward_request/", surgeryschedule.update_ot_medicine_ward_request, name="update_ot_medicine_ward_request"),
    path("delete_ot_medicine_ward_request/", surgeryschedule.delete_ot_medicine_ward_request, name="delete_ot_medicine_ward_request"),
    path("mark_ot_medicine_received/", surgeryschedule.mark_ot_medicine_received, name="mark_ot_medicine_received"),
    path("get_implant_items/",       surgeryschedule.get_implant_items, name="get_implant_items"),
    path("save_implant_request/",     surgeryschedule.save_implant_request, name="save_implant_request"),
    path("get_implant_requests/",     surgeryschedule.get_implant_requests, name="get_implant_requests"),
    path("get_ward_implant_requests/", surgeryschedule.get_ward_implant_requests, name="get_ward_implant_requests"),
    path("update_implant_request/",   surgeryschedule.update_implant_request, name="update_implant_request"),
    path("delete_implant_request/",   surgeryschedule.delete_implant_request, name="delete_implant_request"),
    path("implant/requests/report/", surgeryschedule.list_implant_requests_report, name="list_implant_requests_report"),
    path("implant/requests/pending-count/", surgeryschedule.get_pending_implant_requests_count, name="get_pending_implant_requests_count"),

    # Diet / Food Ordering
    path("save_diet_order/", DietOrder.save_diet_order, name="save_diet_order"),
    path("get_diet_orders/", DietOrder.get_diet_orders, name="get_diet_orders"),
    path("update_diet_status/", DietOrder.update_diet_status, name="update_diet_status"),
    path("get_all_diet_orders/", DietOrder.get_all_diet_orders, name="get_all_diet_orders"),
    path("get_diet_master/", DietOrder.get_diet_master, name="get_diet_master"),
    path("save_diet_master/", DietOrder.save_diet_master, name="save_diet_master"),
    path("get_diet_extra_master/", DietOrder.get_diet_extra_master, name="get_diet_extra_master"),
    path("save_diet_extra_master/", DietOrder.save_diet_extra_master, name="save_diet_extra_master"),
    path("add_extra_to_order/", DietOrder.add_extra_to_order, name="add_extra_to_order"),
    path("update_diet_order_extras/", DietOrder.update_diet_order_extras, name="update_diet_order_extras"),

    # Laundry Ward Request
    path("save_laundry_request/", laundry.save_laundry_request, name="save_laundry_request"),
    path("get_laundry_requests/", laundry.get_laundry_requests, name="get_laundry_requests"),
    path("update_laundry_status/", laundry.update_laundry_status, name="update_laundry_status"),
    path("get_all_laundry_requests/", laundry.get_all_laundry_requests, name="get_all_laundry_requests"),
    path("save_laundry_item_master/", laundry.save_laundry_item_master, name="save_laundry_item_master"),
    path("get_laundry_items_master/", laundry.get_laundry_items_master, name="get_laundry_items_master"),
    path("delete_laundry_item_master/", laundry.delete_laundry_item_master, name="delete_laundry_item_master"),

    # Accounts Report URLs
    path("shift_basis_accounts_report/", shift_basis_report.shift_basis_accounts_report, name="shift_basis_accounts_report"),
    path("bill_wise_report/", bill_wise_report.bill_wise_report, name="bill_wise_report"),
    path("cash_counter_manager/", cash_counter_manager.cash_counter_manager, name="cash_counter_manager"),
    path("get_employee_counter_assignments/", cash_counter_manager.get_employee_counter_assignments, name="get_employee_counter_assignments"),
    path("assign_employee_cash_counter/", cash_counter_manager.assign_employee_cash_counter, name="assign_employee_cash_counter"),
    path('discharge-bills-report/', accounting_reports.discharge_bills_report, name='discharge_bills_report'),
    path('advance-registration-report/', accounting_reports.advance_registration_report, name='advance_registration_report'),
    path('get_shift_summary_report/', accounting_reports.get_shift_summary_report, name='get_shift_summary_report'),
    path('bill-cancel-report/', accounting_reports.bill_cancel_report, name='bill_cancel_report'),
    path('credit-card-report/', accounting_reports.credit_card_report, name='credit_card_report'),
    path('datewise-collection-summary/', accounting_reports.datewise_collection_summary, name='datewise_collection_summary'),
    path('miscellaneous-payment-report/', accounting_reports.miscellaneous_payment_report, name='miscellaneous_payment_report'),
    path('daily-cash-report/', accounting_reports.daily_cash_report, name='daily_cash_report'),
    path('debit-bills-report/', accounting_reports.debit_bills_report, name='debit_bills_report'),
    path('audit-report/', accounting_reports.audit_report, name='audit_report'),
    path('sales-tax-register/', accounting_reports.sales_tax_register, name='sales_tax_register'),
    path('stock-report-ip-op/', accounting_reports.stock_report_ip_op, name='stock_report_ip_op'),

    # Sales Return URLs
    path("salesreturn_get_patientdetails/", salesreturn.salesreturn_get_patientdetails, name="salesreturn_get_patientdetails"),
    path("get_salesreturn_billdetails/", salesreturn.get_salesreturn_billdetails, name="get_salesreturn_billdetails"),
    path("OP_salesreturn_billdetails/", salesreturn.OP_salesreturn_billdetails, name="OP_salesreturn_billdetails"),
    path("get_salesreturn_details/", salesreturn.get_salesreturn_details, name="get_salesreturn_details"),
    path("gsalesreturn_get_uhid_bills/", salesreturn.salesreturn_get_uhid_bills, name="salesreturn_get_uhid_bills"),
    path("salesreturn_get_uhid_bills/", salesreturn.salesreturn_get_uhid_bills, name="salesreturn_get_uhid_bills"),
    path("get_return_bills/", salesreturn.get_return_bills, name="get_return_bills"),

    # Insurance Claim URLs
    path('insurance-claims/', insurance.insurance_claim_view, name='insurance_claim_list'),
    path('insurance-claims/<str:claim_id>/', insurance.insurance_claim_view, name='insurance_claim_detail'),
    path('patient-admission-details/', insurance.get_patient_admission_details, name='patient_admission_details'),

    # Complaints & Tickets
    path('complaints/', complaints.complaint_list_create, name='complaint_list_create'),
    path('complaints/departments/', complaints.complaints_departments, name='complaints_departments'),
    path('complaints/admin/', complaints.complaints_admin_list, name='complaints_admin_list_legacy'),
    path('complaints/admin-list/', complaints.complaints_admin_list, name='complaints_admin_list'),
    path('complaints/<path:pk>/', complaints.complaint_detail, name='complaint_detail'),

    #companysecretary
    path('get_licence_master/', companysecretary.get_licence_master, name='get_licence_masters'),
    path('licence_master_details/', companysecretary.licence_master_details, name='licence_master_details'),
    path('get_incharge_list/', companysecretary.get_incharge_list, name='get_incharge_list'),
    path('licence_master_details/<int:s_no>/', companysecretary.licence_master_details),
    path('licence_master_details/<int:s_no>/renew/', companysecretary.licence_renewal, name='licence-renewal'),


    # lab Inventory
     path('dealer_items/', labinventory.dealer_items, name='dealer_items'),
     path('raise_indent/', labinventory.raise_indent, name='raise_indent'),
    
    
    # HR Internship Management
    path('hr/internships/', hr.list_or_create_internships, name='list_or_create_internships'),
    path('hr/internships/autocomplete/', hr.get_internship_autocomplete, name='get_internship_autocomplete'),
    path('hr/internships/certificate-template/', hr.certificate_template_list_or_create, name='certificate_template_list_or_create'),
    path('hr/internships/certificate-template/<int:template_id>/', hr.certificate_template_detail, name='certificate_template_detail'),
    path('hr/internships/edit/<str:pk>/', hr.detail_or_update_internship, name='detail_or_update_internship'),
    path('hr/internships/payment/<str:pk>/', hr.add_payment, name='add_payment'),
    path('hr/internships/approve/<str:pk>/', hr.approve_internship_certificate, name="approve_internship_certificate"),

    # ABDM Integration API
    path('abdm/update-bridge-url/', abdm_integration.update_bridge_url_api, name='update_bridge_url_api'),
    path('abdm/add-service/', abdm_integration.add_service_api, name='add_service_api'),
    path('abdm/get-services/', abdm_integration.get_services_api, name='get_services_api'),

    # ABDM Milestone 1
    path('abdm/m1/generate-otp/', abdm_m1.generate_otp_api, name='abdm_m1_generate_otp'),
    path('abdm/m1/verify-otp/', abdm_m1.verify_otp_api, name='abdm_m1_verify_otp'),
    path("abha-profiles/", abdm_m1.abha_profile_list_api, name="abha_profile_list_api"),

    # ABDM Milestone 2 (HIP)
    path('v0.5/care-contexts/discover', abdm_m2_hip.discover_care_contexts, name='abdm_m2_discover'),
    path('v0.5/links/link/init', abdm_m2_hip.link_init, name='abdm_m2_link_init'),
    path('v0.5/links/link/confirm', abdm_m2_hip.link_confirm, name='abdm_m2_link_confirm'),

    # Doctor Fee Cuts URLs
    path('doctor-fee-admitted-patients/', DoctorFeeCuts.get_admitted_doctor_fee_patients, name='get_admitted_doctor_fee_patients'),
    path('doctor-fee-cuts/approve-doctor-fee/', DoctorFeeCuts.save_doctor_fee_claim, name='save_doctor_fee_claim'),
    path('doctor-fee-cuts-report/', DoctorFeeCuts.get_doctor_fee_cuts_report, name='get_doctor_fee_cuts_report'),
    path('send-doctor-fee-cut-monthly-emails/', DoctorFeeCuts.send_monthly_doctor_fee_cut_emails, name='send_monthly_doctor_fee_cut_emails'),

    # Vaccination Management URLs
    path('vaccination-masters/', vaccination.get_vaccination_masters, name='get_vaccination_masters'),
    path('add-vaccination-master/', vaccination.add_vaccination_master, name='add_vaccination_master'),
    re_path(r'^update-vaccination-master/(?P<v_id>\d+)/$', vaccination.update_vaccination_master, name='update_vaccination_master'),
    re_path(r'^delete-vaccination-master/(?P<v_id>\d+)/$', vaccination.delete_vaccination_master, name='delete_vaccination_master'),
    path('pending-vaccinations/', vaccination.get_pending_vaccinations, name='get_pending_vaccinations'),
    re_path(r'^patient-vaccination/(?P<uhid>[\w%/-]+)/$', vaccination.get_patient_vaccination, name='get_patient_vaccination'),
    path('save-patient-vaccination/', vaccination.save_patient_vaccination, name='save_patient_vaccination'),
    path('send-vaccination-reminders/', vaccination.send_vaccination_reminders_view, name='send_vaccination_reminders'),
    path('preview-vaccination-reminders/', vaccination.preview_vaccination_reminders_view, name='preview_vaccination_reminders'),

    # QR Scan / InPatient & OutPatient Feedback URLs
    path('inpatient-feedback/', qrscan.inpatient_feedback_list_create, name='inpatient_feedback_list_create'),
    path('inpatient-feedback/<str:feedback_id>/', qrscan.inpatient_feedback_detail, name='inpatient_feedback_detail'),
    path('inpatient_feedback/', qrscan.inpatient_feedback_list_create, name='inpatient_feedback_list_create_alt'),
    path('hospital/inpatient-feedback/', qrscan.inpatient_feedback_list_create, name='inpatient_feedback_list_create_hosp'),

    path('outpatient-feedback/', qrscan.outpatient_feedback_list_create, name='outpatient_feedback_list_create'),
    path('outpatient-feedback/<str:feedback_id>/', qrscan.outpatient_feedback_detail, name='outpatient_feedback_detail'),
    path('outpatient_feedback/', qrscan.outpatient_feedback_list_create, name='outpatient_feedback_list_create_alt'),
    path('hospital/outpatient-feedback/', qrscan.outpatient_feedback_list_create, name='outpatient_feedback_list_create_hosp'),
]




