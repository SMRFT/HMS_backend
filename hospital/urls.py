from turtle import pu

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
    summary,package_crud, investigation_price, billType, velavan, otMaster, anesthesia, surgeryschedule, customer_type,doctor_reports,
    DietOrder,
    purchasereturn,
    purchase_order,
    front_office_reports,
    registration_updates
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
handler404 = 'hospital.views.custom_page_not_found'
urlpatterns = [
    # Admission URLs
    path('autoipNumber/', admission.get_next_ip_number, name='get_next_ip_number'), 
    path('admission/', admission.admission_view, name='admission'),
    path('admission/<str:uhid>/', admission.admission_detail, name='admission_detail'), 
    path('search-rooms/', admission.search_rooms, name='search-rooms'), 
    path('admission/<path:ipNumber>/', admission.admission_detail, name='admission_detail'),
    path('admission-list/', admission.admission_view, name='admission'),
    path('admission-detail/<str:uhid>/', admission.admission_detail, name='admission_detail'), # Supports ID or UHID lookup
    path('admission-room-search/', admission.search_rooms, name='search-rooms'), 
    path('admission-detail/<path:ipNumber>/', admission.admission_detail, name='admission_detail'),
    path('admission-advance/',             admission.admission_advance, name='admission_advance_list'),
    path('admission-advance/<path:ipNumber>/', admission.admission_advance, name='admission_advance_detail'),

    # Inventory URLs
    # Vendor URLs
    path("vendors/", inventory.vendor_view, name="vendor-list"),
    path("vendors/<str:pk>/", inventory.vendor_view, name="vendor-detail"),

    # Stock URLs
    path("pharmacy-items/", inventory.pharmacy_item_view, name="pharmacy-item-list"),
    path("pharmacy-items/<int:pk>/", inventory.pharmacy_item_view, name="pharmacy-item-detail"),

    # Pharmacy Category URLs
    path("pharmacy-category/", inventory.pharmacycategory_view, name="pharmacy-category-list"),
    path("pharmacy-category/<int:pk>/", inventory.pharmacycategory_view, name="pharmacy-category-detail"),

    # Chemical Composition URLs
    path("chemical-composition/", inventory.chemical_composition_view, name="chemical-composition-list"),
    path("chemical-composition/<int:pk>/", inventory.chemical_composition_view, name="chemical-composition-detail"),

    # GRN URLs
    path('grn/', inventory.grn_view, name='grn_list'),
    re_path(r'^grn/(?P<pk>.+)/$', inventory.grn_view, name='grn_detail'),
    path("pharmacy_stock_history/", inventory.pharmacy_stock_history, name="pharmacy_stock_history"),

    path("grn-ocr/", chandra_ocr.grn_ocr_scan, name="grn_ocr_scan"),

    # Stock Transfer URLs
    path('get_active_outlets/', stocktransfer.get_active_stock_outlets, name='get_active_stock_outlets'),
    re_path(r'^_b_a_c_k_e_n_d/HMS/pharmacy-stock/?$',stocktransfer.pharmacy_stock_view,name='pharmacy-stock'),
    re_path(r'^_b_a_c_k_e_n_d/HMS/pharmacy-stock/(?P<pk>\d+)/?$',stocktransfer.pharmacy_stock_view,name='pharmacy-stock-detail'),
    path('stock-transfer/', stocktransfer.stock_transfer_view, name='stock_transfer_list'),
    path("stock-transfer-action/",   stocktransfer.stock_transfer_action_view, name="stock_transfer_action"),

    path("purchase-return/",          purchasereturn.purchase_return_view,     name="purchase-return-list"),
    path("purchase-return/<str:pk>/", purchasereturn.purchase_return_view,     name="purchase-return-detail"),
    path("grn-items/",                purchasereturn.get_grn_items,            name="grn-items"),

    path('medicine-requisition/', medicine_requisition.purchase_requisition_view, name='purchase-requisition-list'),
    path('medicine-requisition/<str:pk>/', medicine_requisition.purchase_requisition_view, name='medicine-requisition-detail'),
    path('medicine-requisition/<str:pk>/approve/', medicine_requisition.purchase_requisition_view, name='approve-medicine-requisition'),
    path('medicine-requisition/<str:pk>/reject/', medicine_requisition.purchase_requisition_view, name='reject-medicine-requisition'),
    path('medicine-requisition/<str:pk>/edit/', medicine_requisition.purchase_requisition_view, name='edit-medicine-requisition'),

    path("purchase-order/",purchase_order.purchase_order_view,name="purchase_order_list"),
    path("purchase-order/<path:pk>/",purchase_order.purchase_order_view,name="purchase_order_detail"),
    path("purchase-order-action/",purchase_order.purchase_order_action_view,name="purchase_order_action"),

    path('pharmacy/notifications/', pharmacynotification.pharmacy_notifications, name='pharmacy-notifications'),

    path('get_oppharmacy_stock/',  pharmacy.get_oppharmacy_stock, name='get_oppharmacy_stock'),
    path('save_oppharmacy_bill/',  pharmacy.save_oppharmacy_bill, name='save_oppharmacy_bill'),
    path('get_oppharmacy_stock/', pharmacy.get_oppharmacy_stock, name='get_oppharmacy_stock'),
    path('pharmacy_expiry_report/', pharmacy.pharmacy_expiry_report, name='pharmacy_expiry_report'),
    path('save_oppharmacy_bill/', pharmacy.save_oppharmacy_bill, name='save_oppharmacy_bill'),
    path('get_pharmacy_BillType/', pharmacy.get_pharmacy_BillType, name='get_pharmacy_BillType'),
    path('get_estimate_bills/',    pharmacy.get_estimate_bills, name='get_estimate_bills'),
    path('get_last_billed_uhid/',  pharmacy.get_last_billed_uhid, name='get_last_billed_uhid'),
    path('OPPharmacy_pending_bills/', pharmacy.OPPharmacy_pending_bills, name='OPPharmacy_pending_bills'),
    path('collect_oppharmacy_payment/', pharmacy.collect_oppharmacy_payment, name='collect_oppharmacy_payment'),
    path('oppharmacy_deletebill/', pharmacy.oppharmacy_deletebill, name='oppharmacy_deletebill'),
    path('pharmacy_medicinechart/', pharmacy.pharmacy_medicinechart, name='pharmacy_medicinechart'),
    path('admissionstatus/', pharmacy.admissionstatus, name='admissionstatus'),
    path('patient_details/', pharmacy.patient_details, name='patient_details'),
    # path("sales_return_medicine/",  pharmacy.sales_return_medicine),
    path("salesreturn_get_patientdetails/",  pharmacy.salesreturn_get_patientdetails),
    path("get_salesreturn_billdetails/",  pharmacy.get_salesreturn_billdetails),
    path("OP_salesreturn_billdetails/",  pharmacy.OP_salesreturn_billdetails),
    path("get_salesreturn_details/", pharmacy.get_salesreturn_details),
    path("substitute_medicine/",  pharmacy.substitute_medicine),
    path("convert_to_bill/",       pharmacy.convert_to_bill),
    path("finalize_bill/",   pharmacy.finalize_bill),
    path("cashcounter_outlet/",   pharmacy.cashcounter_outlet),

    # path("pharmacy_sales_report/", accounts_report.pharmacy_sales_report, name="pharmacy_sales_report"),

    # Central cah counter
    path('cash_counter_shiftdetails/', cashcounter.cash_counter_shiftdetails, name='cash_counter_shiftdetails'),
    path('get_active_shift/', cashcounter.get_active_shift, name='get_active_shift'),
    path('get_shift_summary_report/', cashcounter.get_shift_summary_report, name='get_shift_summary_report'),
    path('get_active_account_heads/', cashcounter.get_active_account_heads, name='get_active_account_heads'),
    path('post_receipt_payments/', cashcounter.post_receipt_payments, name='post_receipt_payments'),
    path("get_receipt_payments/", cashcounter.get_receipt_payments),
    path("ipadvance_bills/",  pharmacy.ipadvance_bills),
    path("get_mainblock_pendingbills/", cashcounter.get_mainblock_pendingbills),
    path("update_mainblock_pendingbills/", cashcounter.update_mainblock_pendingbills),
    path("get_registration_bills/", cashcounter.get_registration_bills),

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

    path("room-enquiry/",       room.room_enquiry_view,       name="room_enquiry"),
    path("update-room-cleaned/", room.update_room_cleaned_view, name="update_room_cleaned"),
    path("book-room/",          room.book_room_view,           name="book_room"),

    path('get_active_admission/', room.get_active_admission, name='get_active_admission'), 
    path("room-shifting/",                    room.room_shifting_view,        name="room_shifting"),
    path("room-shifting/<path:ip_number>/update/", room.room_shifting_detail_view, name="room_shifting_detail"),

    # Discharge URLs
    path("search-discharge-patient/",discharge.search_discharge_patient,name="search-discharge-patient",),
    path("discharge-billing/",discharge.discharge_billing_list_create,name="discharge-billing-list-create",),
    path("discharge-billing/<str:pk>/",discharge.discharge_billing_detail,name="discharge-billing-detail",),
    path("discharge-billing/<str:pk>/convert-to-bill/",discharge.convert_estimate_to_bill,name="discharge-billing-convert",),

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

    path('get_oppharmacy_stock/', pharmacy.get_oppharmacy_stock, name='get_oppharmacy_stock'),
    path('save_oppharmacy_bill/', pharmacy.save_oppharmacy_bill, name='save_oppharmacy_bill'),
    path('get_pharmacy_BillType/', pharmacy.get_pharmacy_BillType, name='get_pharmacy_BillType'),
    path('get_estimate_bills/', pharmacy.get_estimate_bills, name='get_estimate_bills'),
    path('get_last_billed_uhid/', pharmacy.get_last_billed_uhid, name='get_last_billed_uhid'),
    path('OPPharmacy_pending_bills/', pharmacy.OPPharmacy_pending_bills, name='OPPharmacy_pending_bills'),
    path('collect_oppharmacy_payment/', pharmacy.collect_oppharmacy_payment, name='collect_oppharmacy_payment'),

    # Customer Type URLs
    path('customer-types/', customer_type.customer_type_list, name='customer_type_list'),
    path('customer-types/<int:pk>/', customer_type.customer_type_detail, name='customer_type_detail'),

    #Radiology Reports :
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

    #JRD Reports : 
    path('anc-register/', jrdReport.get_anc_register,  name='get_anc_register'),
    path('jrd-reports/', jrdReport.list_jrd_reports,  name='jrd_list'),
    path('jrd-reports/create/',jrdReport.create_jrd_report, name='jrd_create'),
    re_path(r'^jrd-reports/update/(?P<jrd_id>\d+)/$',jrdReport.update_jrd_report, name='update_jrd_report'),
    re_path(r'^jrd-reports/delete/(?P<jrd_id>\d+)/$',jrdReport.delete_jrd_report, name='delete_jrd_report'),
    
    #Summary:
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

    #ICD11:
    path("icd11/search/", ICD11.icd11_search,name='icd11_search'),
    path("icd11/entity/<str:entity_id>/", ICD11.icd11_detail),

    #Investigation Billing:
    re_path(r'^op-patient/(?P<uhid>[\w%/-]+)/$', departmentBilling.op_patient_detail_by_uhid, name='op-patient-detail-by-uhid'),
    re_path(r'^ip-patient/(?P<ipNumber>[\w%/-]+)/$', departmentBilling.ip_patient_detail_by_ipNumber, name='ip-patient-detail-by-ipNumber'),  
    path('bill-types/', departmentBilling.get_bill_types, name='get_bill_types'),  
    path('packages/', departmentBilling.get_packages, name='get_packages'),
    path('package-items/', departmentBilling.get_package_items, name='get_package_items'),
    path('investigation-items/', departmentBilling.get_investigation_items, name='get_investigation_items'),
    path('investBilling/', departmentBilling.invest_billing_create, name='invest-billing-create'),
    path('investBillingGet/', departmentBilling.billing_report_view, name='billing_report_view'),
    path('estimateBilling/', departmentBilling.estimate_billing_create, name='estimate_billing_create'),
    path('get-estimate-billings/', departmentBilling.estimate_billing_list, name='estimate-billing-list'),
    path('delete-bill/', departmentBilling.delete_bill_view, name='delete_bill_view'),
    path('invest-refund/', departmentBilling.invest_refund_create, name='invest_refund_create'),

    #Doctor Master:
    path('doctor_list_diagnostics/', doctormaster.doctor_list_from_diagnostics, name='doctor_list_diagnostics'), 
    path('doctor_schedule/', doctormaster.doctor_schedule_list, name='doctor_schedule_list'),
    path('doctor_schedule/<str:employee_id>/', doctormaster.doctor_schedule_detail, name='doctor_schedule_detail'),
    path('doctor_schedule_upsert/<str:employee_id>/', doctormaster.doctor_schedule_upsert, name='doctor_schedule_upsert'),

    path("wardrequest/", NursingStation.get_admission_list, name="wardrequest"),
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
    path("update_medicine_ward_request/", NursingStation.update_medicine_ward_request, name="update_medicine_ward_request"),
    path("cancel_medicine_ward_request/", NursingStation.cancel_medicine_ward_request, name="cancel_medicine_ward_request"),
    path("remove_individual_medicine/", NursingStation.remove_individual_medicine_from_ward_request, name="remove_individual_medicine"),
    path("get_radiology_ward_requests/", NursingStation.get_radiology_ward_requests, name="get_radiology_ward_requests"),
    path("save_radiology_ward_request/", NursingStation.save_radiology_ward_request, name="save_radiology_ward_request"),
    path("cancel_radiology_ward_request/", NursingStation.cancel_radiology_ward_request, name="cancel_radiology_ward_request"),
    path("remove_individual_radiology/", NursingStation.remove_individual_test_from_radiology_ward_request, name="remove_individual_radiology"),
    path("dosage_master/", NursingStation.dosage_master_view, name="dosage_master"),
    
    #Package Master:
    path('investigation-prices/',  package_crud.get_bill_types,    name='get_bill_types'),
    path('lab-items/',  package_crud.get_lab_items,    name='get_lab_items'),
    path('outlets/',  package_crud.get_outlets,    name='get_outlets'),
    path('packages_crud/',  package_crud.get_packages,    name='get_packages'),
    path('packages/create/',  package_crud.create_package,  name='create_package'),
    path('packages/<int:package_no>/', package_crud.get_package,     name='get_package'),
    path('packages/update/<int:package_no>/', package_crud.update_package, name='update_package'),
    path('packages/delete/<int:package_no>/', package_crud.delete_package, name='delete_package'),

    #Investigation Price Master:
    path('investigation-prices_get/', investigation_price.get_investigation_prices, name='get_investigation_prices'),
    path('investigation-prices/create/', investigation_price.create_investigation_price, name='create_investigation_price'),
    path('investigation-prices/update/<str:bill_type_no>/', investigation_price.update_investigation_price, name='update_investigation_price'),
    path('investigation-prices/delete/<str:bill_type_no>/', investigation_price.delete_investigation_price, name='delete_investigation_price'),
    path('investigation-prices/update_item/<str:bill_type_no>/<int:item_id>/', investigation_price.update_investigation_item, name='update_investigation_item'),
    path('investigation-prices/delete_item/<str:bill_type_no>/<int:item_id>/', investigation_price.delete_investigation_item, name='delete_investigation_item'),

    #Bil Type Master:
    path('bill-types_get/', billType.get_bill_types, name='get_bill_types'),
    path('bill-types/create/', billType.create_bill_type, name='create_bill_type'),
    path('bill-types/update/<int:bill_type_int>/', billType.update_bill_type, name='update_bill_type'),
    path('bill-types/delete/<int:bill_type_int>/', billType.delete_bill_type, name='delete_bill_type'),
    path('investigation-price/patch-bill-type/',    billType.patch_bill_type_prices, name='patch_bill_type_prices'),

    #Reports:
    path('dept-budr/', departmentBilling.dept_budr_view, name='dept_budr_view'),
    path('doctor-report/', doctor_reports.doctor_report_view, name='doctor_report_view'),
    path('front-office-reports/', front_office_reports.front_office_report_view, name='front_office_reports'),

    #Velavan Items:    
    path('velavan_items/list/', velavan.list_items, name='list_items'),
    path('velavan_get_items/', velavan.velavan_get_items, name='velavan_get_items'),
    path('velavan_create_item/', velavan.velavan_create_item, name='velavan_create_item'),
    path('velavan_update_item/<str:item_id>/', velavan.velavan_update_item, name='velavan_update_item'),
    path('velavan_delete_item/<str:item_id>/', velavan.velavan_delete_item, name='velavan_delete_item'),
    
    #Velavan Vendor:    
    path('velavan_vendors/list/', velavan.list_vendors, name='list_vendors'),
    path('velavan_get_vendors/', velavan.velavan_get_vendors, name='velavan_get_vendors'),
    path('velavan_create_vendor/', velavan.velavan_create_vendor, name='velavan_create_vendor'),
    path("velavan_update_vendor/<str:vendor_id>/", velavan.velavan_update_vendor, name="velavan_update_vendor"),
    path("velavan_delete_vendor/<str:vendor_id>/", velavan.velavan_delete_vendor, name="velavan_delete_vendor"),

    #Velavan Invoice:
    path('velavan/invoices/', velavan.create_velavan_in, name='create_velavan_in'),
    path('velavan/invoices/list/', velavan.list_velavan_invoices, name='list_velavan_invoices'),
    path('velavan/previous-purchases/', velavan.get_previous_purchases, name='previous_purchases'),
    path('velavan/invoices/update/<path:grn_number>/', velavan.update_velavan_invoice, name='update_velavan_invoice'),  
    path('velavan/invoices/approve/<path:grn_number>/', velavan.approve_velavan_invoice, name='approve_velavan_invoice'),  

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

    path('stores-assets-management/', assets.stores_assets_management_list_create, name='stores_assets_management_list_create'),
    path('stores-assets-management/<path:pk>/', assets.stores_assets_management_detail, name='stores_assets_management_detail'),

    path('stores-assets-maintenance/', assets.stores_assets_maintenance_details, name='stores_assets_maintenance_details'),
    path('stores-assets-maintenance/<path:pk>/', assets.stores_assets_maintenance_details, name='stores_assets_maintenance_details'),

    path("recycle_asset/", assets.create_recycle_asset, name="create_recycle_asset"),
    path("recycle_asset/<path:pk>/", assets.update_recycle_asset, name="update_recycle_asset"),
    #OT Master:
    path('create_ot/', otMaster.create_ot,  name='create_ot'),
    path('list_ots/',  otMaster.list_ots,   name='list_ots'),
    path('update_ot/<str:ot_id>/', otMaster.update_ot, name='update_ot'),
    path('delete_ot/<str:ot_id>/', otMaster.delete_ot, name='delete_ot'), 

    #Anesthesia Master:
    path('create_anes/', anesthesia.create_anes,  name='create_anes'),
    path('list_anes/',  anesthesia.list_anes,   name='list_anes'),
    path('update_anes/<str:anesthesia_id>/', anesthesia.update_anes, name='update_anes'),
    path('delete_anes/<str:anesthesia_id>/', anesthesia.delete_anes, name='delete_anes'), 

    #Surgery Schedule:
    path("create_surgery_schedule/", surgeryschedule.create_surgery_schedule, name='create_surgery_schedule'),
    path("list_surgery_schedules/",  surgeryschedule.list_surgery_schedules, name='list_surgery_schedules'),
    path("get_surgery_schedule/",surgeryschedule.get_surgery_schedule, name='get_surgery_schedule'),
    path("update_surgery_schedule/", surgeryschedule.update_surgery_schedule, name='update_surgery_schedule'),
    path("cancel_surgery_schedule/", surgeryschedule.cancel_surgery_schedule, name='cancel_surgery_schedule'),
    path("update_schedule_status/",  surgeryschedule.update_schedule_status, name='update_schedule_status'),
    path("list_diagnosis/",  surgeryschedule.list_diagnosis, name='list_diagnosis'),    
    path("get_ot_medicine_ward_requests/", surgeryschedule.get_ot_medicine_ward_requests, name="get_ot_medicine_ward_requests"),
    path('get_ippharmacy_stock/', surgeryschedule.get_ippharmacy_stock, name='get_ippharmacy_stock'),
    path("save_ot_medicine_ward_request/", surgeryschedule.save_ot_medicine_ward_request, name="save_ot_medicine_ward_request"),
    path("update_ot_medicine_ward_request/", surgeryschedule.update_ot_medicine_ward_request, name="update_ot_medicine_ward_request"),
    path("delete_ot_medicine_ward_request/", surgeryschedule.delete_ot_medicine_ward_request, name="delete_ot_medicine_ward_request"),

    # Diet / Food Ordering:
    path("save_diet_order/",    DietOrder.save_diet_order,    name="save_diet_order"),
    path("get_diet_orders/",    DietOrder.get_diet_orders,    name="get_diet_orders"),
    path("update_diet_status/", DietOrder.update_diet_status, name="update_diet_status"),
    path("get_all_diet_orders/", DietOrder.get_all_diet_orders, name="get_all_diet_orders"),
    path("get_diet_master/",    DietOrder.get_diet_master,    name="get_diet_master"),
    path("save_diet_master/",   DietOrder.save_diet_master,   name="save_diet_master"),
    path("get_diet_extra_master/",  DietOrder.get_diet_extra_master,  name="get_diet_extra_master"),
    path("save_diet_extra_master/", DietOrder.save_diet_extra_master, name="save_diet_extra_master"),
    path("add_extra_to_order/", DietOrder.add_extra_to_order, name="add_extra_to_order"),
    path("update_diet_order_extras/", DietOrder.update_diet_order_extras, name="update_diet_order_extras"),

    # Accounts Report URLs
    path("shift_basis_accounts_report/", shift_basis_report.shift_basis_accounts_report, name="shift_basis_accounts_report"),
    path("bill_wise_report/", bill_wise_report.bill_wise_report, name="bill_wise_report"),
    path("cash_counter_manager/",   cash_counter_manager.cash_counter_manager, name="cash_counter_manager"),
    path('discharge-bills-report/', accounting_reports.discharge_bills_report, name='discharge_bills_report'),
    path('advance-registration-report/', accounting_reports.advance_registration_report, name='advance_registration_report'),
    path('get_shift_summary_report/', accounting_reports.get_shift_summary_report, name='get_shift_summary_report'),

    # path("salesreturn_get_patientdetails/",  pharmacy.get_salesreturn_billdetails),
    # path("get_salesreturn_billdetails/",  pharmacy.get_salesreturn_billdetails),
    path("salesreturn_get_patientdetails/",pharmacy.salesreturn_get_patientdetails, name="salesreturn_get_patientdetails"),
    path("get_salesreturn_billdetails/", pharmacy.get_salesreturn_billdetails, name="get_salesreturn_billdetails"),
    path("OP_salesreturn_billdetails/", pharmacy.OP_salesreturn_billdetails, name="OP_salesreturn_billdetails"),

    # Insurance Claim URLs
    path('insurance-claims/', insurance.insurance_claim_view, name='insurance_claim_list'),
    path('insurance-claims/<str:claim_id>/', insurance.insurance_claim_view, name='insurance_claim_detail'),
    path('patient-admission-details/', insurance.get_patient_admission_details, name='patient_admission_details'),
]
