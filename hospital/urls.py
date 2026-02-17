from django.urls import path, re_path
from . import views
from . import Views
from .Views import (
    admission,
    departmentBilling,
    discharge,
    doctormaster,
    grn,
    ICD11,
    inventory,
    pharmacy,
    radiology,
    room,
    stock,
    summary,
)

urlpatterns = [
    # Admission URLs
    path('doctor_list_diagnostics/', doctormaster.doctor_list_from_diagnostics, name='doctor_list_diagnostics'), # Duplicate but consistent
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
    path('room-category/<str:pk>/', room.room_category_view, name='room_category_update_delete'),
    
    path('room/', room.room_view, name='room_list_create'),
    path('room/<str:pk>/', room.room_view, name='room_update_delete'),
    
    path('roomservice-description/', room.room_service_description_view, name='roomservice_list'),

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
    path('investigations/', radiology.get_ct_investigations, name='get_investigations'),
    # path('investigations/<str:uhid>/<str:subUhid>/', views.get_patient_report, name='get_patient_report'),

    #Investigation Reports (CT):
    path('investigations/', radiology.get_ct_investigations, name='get_ct_investigations'),
    path('ct-reports/', radiology.create_ct_report, name='create_ct_report'),   
    path('ct_reports/', radiology.get_ct_reports, name='get_ct_reports'),  # Fetch all reports
    path('ct_reports/<str:patientId>/', radiology.get_ct_reports, name='get_ct_report'),  # Fetch specific report by patientId      
    re_path(r'^ct-reports/approve/(?P<investBillNo>.+)/$', radiology.approve_ct_report, name='approve_ct_report'),     
    re_path(r'^ct-reports/delete/(?P<investBillNo>.+)/$', radiology.soft_delete_ct_report, name='soft_delete_ct_report'),
    re_path(r'^ct-reports/edit/(?P<investBillNo>.+)/$', radiology.edit_ct_report_impression, name='edit_ct_report_impression'),     
    #Investigation Reports (MRI):
    path('mri_investigations/', radiology.get_mri_investigations, name='get_mri_investigations'),  
    path('mri-reports/', radiology.create_mri_report, name='create_mri_report'),
    path('mri_reports/', radiology.get_mri_reports, name='get_mri_reports'),  # Fetch all reports
    path('mri_reports/<str:patientId>/', radiology.get_mri_reports, name='get_mri_report'),  # Fetch specific report by patientId   
    re_path(r'^mri-reports/approve/(?P<investBillNo>.+)/$', radiology.approve_mri_report, name='approve_mri_report'),  
    re_path(r'^mri-reports/delete/(?P<investBillNo>.+)/$', radiology.soft_delete_mri_report, name='soft_delete_mri_report'), 
    re_path(r'^mri-reports/edit/(?P<investBillNo>.+)/$', radiology.edit_mri_report_impression, name='edit_mri_report_impression'),     
    #Investigation Reports (USG):
    path('usg_investigations/', radiology.get_usg_investigations, name='get_usg_investigations'),  
    path('usg-reports/', radiology.create_usg_report, name='create_usg_report'),
    path('usg_reports/', radiology.get_usg_reports, name='get_usg_reports'),  # Fetch all reports
    path('usg_reports/<str:patientId>/', radiology.get_usg_reports, name='get_usg_report'),  # Fetch specific report by patientId   
    re_path(r'^usg-reports/approve/(?P<investBillNo>.+)/$', radiology.approve_usg_report, name='approve_usg_report'),  
    re_path(r'^usg-reports/delete/(?P<investBillNo>.+)/$', radiology.soft_delete_usg_report, name='soft_delete_usg_report'),
    re_path(r'^usg-reports/edit/(?P<investBillNo>.+)/$', radiology.edit_usg_report_impression, name='edit_usg_report_impression'),     
    #Investigation Reports (X-RAY):
    path('x_ray_investigations/', radiology.get_x_ray_investigations, name='get_x_ray_investigations'), 
    path('x_ray-reports/', radiology.create_x_ray_report, name='create_x_ray_report'),
    path('x_ray_reports/', radiology.get_x_ray_reports, name='get_x_ray_reports'),  # Fetch all reports
    path('x_ray_reports/<str:investBillNo>/', radiology.get_x_ray_reports, name='get_x_ray_report'),  # Fetch specific report by patientId   
    re_path(r'^x_ray-reports/approve/(?P<investBillNo>.+)/$', radiology.approve_x_ray_report, name='approve_x_ray_report'),  
    re_path(r'^x_ray-reports/delete/(?P<investBillNo>.+)/$', radiology.soft_delete_x_ray_report, name='soft_delete_x_ray_report'), 
    re_path(r'^x_ray-reports/edit/(?P<investBillNo>.+)/$', radiology.edit_x_ray_report_impression, name='edit_x_ray_report_impression'),     

    #Summary:
    path('summaries/', summary.get_summaries, name='get_summaries'),
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
    path('lab-tests/', departmentBilling.get_lab_tests, name='get-lab-tests'), 
    path('investBilling/', departmentBilling.invest_billing_create, name='invest-billing-create'),
    path('investBillingGet/', departmentBilling.billing_report_view, name='billing_report_view'),
    path('estimateBilling/', departmentBilling.estimate_billing_create, name='estimate_billing_create'),
    path('get-estimate-billings/', departmentBilling.estimate_billing_list, name='estimate-billing-list'),
    path('delete-bill/', departmentBilling.delete_bill_view, name='delete_bill_view'),
    
    #Doctor Master:
    path('doctor_list_diagnostics/', doctormaster.doctor_list_from_diagnostics, name='doctor_list_diagnostics'), # Duplicate
    path('doctor_schedule/', doctormaster.doctor_schedule_list, name='doctor_schedule_list'),
    path('doctor_schedule/<str:employee_id>/', doctormaster.doctor_schedule_detail, name='doctor_schedule_detail'),
    path('doctor_schedule_upsert/<str:employee_id>/', doctormaster.doctor_schedule_upsert, name='doctor_schedule_upsert'),

    path('get_oppharmacy_stock/', pharmacy.get_oppharmacy_stock, name='get_oppharmacy_stock'),
    path('save_oppharmacy_bill/', pharmacy.save_oppharmacy_bill, name='save_oppharmacy_bill'),
]
