from django.urls import path, re_path
from . import views
from .Views import (
    admission,
    departmentBilling,
    discharge,
    doctormaster,
    grn,
    ICD11,
    inventory,
    package_crud,
    pharmacy,
    radiology,
    room,
    stock,
    summary,package_crud, investigation_price, billType
)

urlpatterns = [
    # Admission URLs
    path('autoipNumber/', admission.get_next_ip_number, name='get_next_ip_number'), 
    path('admission/', admission.admission_view, name='admission'),
    path('admission/<str:uhid>/', admission.admission_detail, name='admission_detail'), # Supports ID or UHID lookup
    re_path(r'^op-patient/(?P<uhid>[\w%/-]+)/$', admission.get_op_patient_by_uhid, name='op-patient-detail-by-uhid'),
    re_path(r'^get_op_patient_by_uhid/(?P<uhid>[\w%/-]+)/$', admission.get_op_patient_by_uhid, name='get_op_patient_by_uhid'),
    path('search-rooms/', admission.search_rooms, name='search-rooms'), 

    # Pharmacy Stock URLs
    path('ip-pharmacy-stock/', stock.ip_pharmacy_stock_view, name='ip_pharmacy_stock_list'),
    path('ip-pharmacy-stock/<str:pk>/', stock.ip_pharmacy_stock_view, name='ip_pharmacy_stock_detail'),
    path('op-pharmacy-stock/', stock.op_pharmacy_stock_view, name='op_pharmacy_stock_list'),
    path('op-pharmacy-stock/<str:pk>/', stock.op_pharmacy_stock_view, name='op_pharmacy_stock_detail'),

    # GRN URLs
    path('ip-grn/', grn.ip_grn_view, name='ip_grn_list'),
    path('ip-grn/<str:pk>/', grn.ip_grn_view, name='ip_grn_detail'),
    path('op-grn/', grn.op_grn_view, name='op_grn_list'),
    path('op-grn/<str:pk>/', grn.op_grn_view, name='op_grn_detail'),

    # Vendor URLs
    path('vendor/', inventory.vendor_view, name='vendor_list'),
    path('vendor/<str:vendor_id>/', inventory.vendor_view, name='vendor_detail'),
    
    # Room URLs
    path('block/', room.block_view, name='block_list_create'),
    path('block/<int:pk>/', room.block_view, name='block_update_delete'),
    
    path('room-category/', room.room_category_view, name='room_category_list_create'),
    path('room-category/<int:pk>/', room.room_category_view, name='room_category_update_delete'),
    
    path('room/', room.room_view, name='room_list_create'),
    path('room/<int:pk>/', room.room_view, name='room_update_delete'),
    
    path('bed/', room.bed_view, name='bed_list_create'),
    path('bed/<int:pk>/', room.bed_view, name='bed_update_delete'),
    
    path('service/', room.service_view, name='service_list_create'),
    path('service/<int:pk>/', room.service_view, name='service_update_delete'),
    
    path('room-enquiry/', room.room_enquiry_view, name='room_enquiry'),
    path('room-shifting/', room.room_shifting_view, name='room_shifting'),

    #Discharge URLs
    path('search-admissions/', discharge.search_discharge_patient, name='search-admissions'),
    path('discharge/', discharge.discharge_detail_view, name='discharge-create'),

    # Patient URLs
    path('patients/register/', views.patientCreateView, name='patient-register'),
    path('create/', views.patientCreateView, name='patient-list'),
    path('get-last-uhid/', views.get_last_uhid, name='get_last_uhid'),
    path('doctors/', views.doctor_view, name='doctor_view'),
    path('doctor_list/', views.doctor_list, name='doctor_list'),
    path('doctor_detail/<str:first_name>/', views.doctor_detail, name='doctor_detail'),
    path('add-reference-doctor/', views.save_reference_doctor, name='save_reference_doctor'),
    path('get-reference-doctors/', views.get_reference_doctors, name='get_reference_doctors'),

    #Radiology Reports :
    path('investigations/', radiology.get_investigations, name='get_investigations'),
    path('scan-reports/', radiology.create_scan_report, name='create_scan_report'),     
    re_path(r'^scan-reports/approve/(?P<investBillNo>.+)/(?P<itemName>.+)/$', radiology.approve_scan_report, name='approve_scan_report'),
    re_path(r'^scan-reports/delete/(?P<investBillNo>.+)/(?P<itemName>.+)/$', radiology.soft_delete_scan_report, name='soft_delete_scan_report'),
    re_path(r'^scan-reports/edit/(?P<investBillNo>.+)/(?P<itemName>.+)/$', radiology.edit_scan_report_impression, name='edit_scan_report_impression'),     
    
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
    
    #Doctor Master:
    path('doctor_list_diagnostics/', doctormaster.doctor_list_from_diagnostics, name='doctor_list_diagnostics'), 
    path('doctor_schedule/', doctormaster.doctor_schedule_list, name='doctor_schedule_list'),
    path('doctor_schedule/<str:employee_id>/', doctormaster.doctor_schedule_detail, name='doctor_schedule_detail'),
    path('doctor_schedule_upsert/<str:employee_id>/', doctormaster.doctor_schedule_upsert, name='doctor_schedule_upsert'),

    path('get_oppharmacy_stock/', pharmacy.get_oppharmacy_stock, name='get_oppharmacy_stock'),
    path('save_oppharmacy_bill/', pharmacy.save_oppharmacy_bill, name='save_oppharmacy_bill'),


    #Package Master:
    path('investigation-prices/',  package_crud.get_bill_types,    name='get_bill_types'),
    path('lab-items/',  package_crud.get_lab_items,    name='get_lab_items'),
    path('departments/',  package_crud.get_departments,    name='get_departments'),
    path('packages_crud/',  package_crud.get_packages,    name='get_packages'),
    path('packages/create/',  package_crud.create_package,  name='create_package'),
    path('packages/<int:package_no>/', package_crud.get_package,     name='get_package'),
    path('packages/<int:package_no>/update/', package_crud.update_package, name='update_package'),
    path('packages/<int:package_no>/delete/', package_crud.delete_package, name='delete_package'),

    #Investigation Price Master:
    path('investigation-prices_get/', investigation_price.get_investigation_prices),
    path('investigation-prices/create/', investigation_price.create_investigation_price),
    path('investigation-prices/<str:bill_type_no>/update/',investigation_price.update_investigation_price),
    path('investigation-prices/<str:bill_type_no>/delete/',investigation_price.delete_investigation_price),
    
    #Bil Type Master:
    path('bill-types_get/', billType.get_bill_types),
    path('bill-types/create/', billType.create_bill_type),
    path('bill-types/<str:bill_type_no>/update/', billType.update_bill_type),
    path('bill-types/<str:bill_type_no>/delete/', billType.delete_bill_type),
    path('investigation-price/patch-bill-type/',    billType.patch_bill_type_prices),
    

]
