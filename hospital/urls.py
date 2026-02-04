from django.urls import path
from . import views
from .Views import pharmacy, inventory, room, doctormaster, admission, discharge, stock, grn
from django.urls import re_path  # Use re_path for regex matching

urlpatterns = [
    # Admission URLs
    path('doctor_list_diagnostics/', doctormaster.doctor_list_from_diagnostics, name='doctor_list_diagnostics'),
    path('autoipNumber/', admission.get_next_ip_number, name='get_next_ip_number'), 
    path('admission/', admission.admission_view, name='admission'),
    path('admission/<str:uhid>/', admission.admission_detail, name='admission_detail'), # Supports ID or UHID lookup
    re_path(r'^op-patient/(?P<uhid>[\w%/-]+)/$', admission.get_op_patient_by_uhid, name='op-patient-detail-by-uhid'),
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

    #Patient URLs
    path('patients/register/', views.patientCreateView, name='patient-register'),
    path('create/', views.patientCreateView, name='patient-list'),
    path('doctors/', views.doctor_view, name='doctor_view'),
    path('doctor_list/', views.doctor_list, name='doctor_list'),
    path('doctor_detail/<str:first_name>/', views.doctor_detail, name='doctor_detail'),
    path('add-reference-doctor/', views.save_reference_doctor, name='save_reference_doctor'),
    path('get-reference-doctors/', views.get_reference_doctors, name='get_reference_doctors'),
    path('investigations/', views.get_investigations, name='get_investigations'),
    path('investigations/<str:uhid>/<str:subUhid>/', views.get_patient_report, name='get_patient_report'),

    path('ct-reports/', views.create_ct_report, name='create_ct_report'),   
    path('ct_reports/', views.get_ct_reports, name='get_ct_reports'),  # Fetch all reports
    path('ct_reports/<str:patientId>/', views.get_ct_reports, name='get_ct_report'),  # Fetch specific report by patientId      
    re_path(r'^ct-reports/(?P<patient_id>.+)/approve/$', views.approve_ct_report, name='approve_ct_report'),     
    re_path(r'^ct-reports/(?P<patient_id>.+)/delete/$', views.delete_ct_report, name='delete_ct_report'),     

    path('mri_investigations/', views.get_mri_investigations, name='get_mri_investigations'),  # Fetch all MRI reports
    path('mri_investigations/<str:uhid>/<str:subUhid>/', views.get_mri_patient_report, name='get_mri_patient_report'),  # Fetch specific MRI report by patientId  
    path('mri-reports/', views.create_mri_report, name='create_mri_report'),
    path('mri_reports/', views.get_mri_reports, name='get_mri_reports'),  # Fetch all reports
    path('mri_reports/<str:patientId>/', views.get_mri_reports, name='get_mri_report'),  # Fetch specific report by patientId   
    re_path(r'^mri-reports/(?P<patient_id>.+)/approve/$', views.approve_mri_report, name='approve_mri_report'),  
    re_path(r'^mri-reports/(?P<patient_id>.+)/delete/$', views.delete_mri_report, name='delete_mri_report'),    

    path('usg_investigations/', views.get_usg_investigations, name='get_usg_investigations'),  # Fetch all MRI reports
    path('usg_investigations/<str:uhid>/<str:subUhid>/', views.get_usg_patient_report, name='get_usg_patient_report'),  # Fetch specific MRI report by patientId  
    path('usg-reports/', views.create_usg_report, name='create_usg_report'),
    path('usg_reports/', views.get_usg_reports, name='get_usg_reports'),  # Fetch all reports
    path('usg_reports/<str:patientId>/', views.get_usg_reports, name='get_usg_report'),  # Fetch specific report by patientId   
    re_path(r'^usg-reports/(?P<patient_id>.+)/approve/$', views.approve_usg_report, name='approve_usg_report'),  
    re_path(r'^usg-reports/(?P<patient_id>.+)/delete/$', views.delete_usg_report, name='delete_usg_report'),

    path('x_ray_investigations/', views.get_x_ray_investigations, name='get_x_ray_investigations'),  # Fetch all MRI reports
    path('x_ray_investigations/<str:uhid>/<str:subUhid>/', views.get_x_ray_patient_report, name='get_x_ray_patient_report'),  # Fetch specific MRI report by patientId  
    path('x_ray-reports/', views.create_x_ray_report, name='create_x_ray_report'),
    path('x_ray_reports/', views.get_x_ray_reports, name='get_x_ray_reports'),  # Fetch all reports
    path('x_ray_reports/<str:patientId>/', views.get_x_ray_reports, name='get_x_ray_report'),  # Fetch specific report by patientId   
    re_path(r'^x_ray-reports/(?P<patient_id>.+)/approve/$', views.approve_x_ray_report, name='approve_x_ray_report'),  
    re_path(r'^x_ray-reports/(?P<patient_id>.+)/delete/$', views.delete_x_ray_report, name='delete_x_ray_report'),    


    path('summaries/', views.get_summaries, name='get_summaries'),
    path('summaries/create/', views.create_summary, name='create_summary'),   
    re_path(r'^approve-summary/(?P<ip_no>.+)/$', views.approve_summary, name='approve_summary'),
    re_path(r'^delete-summary/(?P<ip_no>.+)/$', views.delete_summary, name='delete_summary'),
    re_path(r'^edit-editsummary/(?P<ip_no>.+)/$', views.get_editsummary, name='get_editsummary'),
    re_path(r'^update-summary/(?P<ip_no>.+)/$', views.update_summary_fields, name='update_summary_fields'),
    re_path(r'^ip-patient/(?P<ipNumber>[\w%/-]+)/$', views.ip_patient_detail_by_ipNumber, name='ip-patient-detail-by-ipNumber'),
    path('bill-types/', views.get_bill_types, name='get_bill_types'),   
    path('investBilling/', views.invest_billing_create, name='invest-billing-create'),
    path('investBillingGet/', views.billing_report_view, name='billing_report_view'),
    path('estimateBilling/', views.estimate_billing_create, name='estimate_billing_create'),
    path('get-estimate-billings/', views.estimate_billing_list, name='estimate-billing-list'),
    path('delete-bill/', views.delete_bill_view, name='delete_bill_view'),  
    re_path(r'^patient-investigations/(?P<ip_no>[\w%/-]+)/$', views.get_patient_investigations, name='get_patient_investigations'),
    #Doctor Master:
    path('doctor_list_diagnostics/', doctormaster.doctor_list_from_diagnostics, name='doctor_list_diagnostics'),
    path('doctor_schedule/', doctormaster.doctor_schedule_list, name='doctor_schedule_list'),
    path('doctor_schedule/<str:employee_id>/', doctormaster.doctor_schedule_detail, name='doctor_schedule_detail'),
    path('doctor_schedule_upsert/<str:employee_id>/', doctormaster.doctor_schedule_upsert, name='doctor_schedule_upsert'),
]
