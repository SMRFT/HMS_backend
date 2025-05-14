from django.urls import path
from . import views
from django.urls import re_path  # Use re_path for regex matching

urlpatterns = [
     path('register/', views.register_user, name='register_user'),
    path('create-stock/', views.create_stock_entry, name='create_stock_entry'),
    path('hsncodes/', views.hsn_code_list, name='hsn_code_list'),
    path('ventor/', views.ventor_list, name='ventor_list'),
    path('blocks/', views.block_list, name='block_list'),
    path('blocks/<str:block_name>/', views.block_detail, name='block_detail'),
    path('rooms/', views.room_list, name='room_list'),
    path('discharge/', views.discharge_detail_view, name='discharge-create'),
    path('login/', views.login_user, name='login'),
    path('patients/register/', views.patientCreateView, name='patient-register'),
    path('create/', views.patientCreateView, name='patient-list'),
    path('doctors/', views.doctor_view, name='doctor_view'),
    path('doctor_list/', views.doctor_list, name='doctor_list'),
    path('doctor_detail/<str:first_name>/', views.doctor_detail, name='doctor_detail'),    
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

    path('admission/', views.create_admission, name='create_admission'),
    path('admissions/', views.list_admissions, name='list_admissions'),
    path('summaries/', views.get_summaries, name='get_summaries'),
    path('summaries/create/', views.create_summary, name='create_summary'),   
    re_path(r'^approve-summary/(?P<ip_no>.+)/$', views.approve_summary, name='approve_summary'),
    re_path(r'^delete-summary/(?P<ip_no>.+)/$', views.delete_summary, name='delete_summary'),
    re_path(r'^edit-editsummary/(?P<ip_no>.+)/$', views.get_editsummary, name='get_editsummary'),
    re_path(r'^update-summary/(?P<ip_no>.+)/$', views.update_summary_fields, name='update_summary_fields'),
    re_path(r'^op-patient/(?P<uhid>[\w%/-]+)/$', views.op_patient_detail_by_uhid, name='op-patient-detail-by-uhid'),
    re_path(r'^ip-patient/(?P<ipNumber>[\w%/-]+)/$', views.ip_patient_detail_by_ipNumber, name='ip-patient-detail-by-ipNumber'),
    path('bill-types/', views.get_bill_types, name='get_bill_types'),   
    path('investBilling/', views.invest_billing_create, name='invest-billing-create'),
     path('investBillingGet/', views.billing_report_view, name='billing_report_view'),
    path('estimateBilling/', views.estimate_billing_create, name='estimate_billing_create'),
    path('get-estimate-billings/', views.estimate_billing_list, name='estimate-billing-list'),
    path('autoipNumber/', views.get_next_ip_number, name='get_next_ip_number'),  
    path('delete-bill/', views.delete_bill_view, name='delete_bill_view'),  
    # path('get_ct_scan_data/', views.get_ct_scan_data, name='get_ct_scan_data'),  

    # path('patient-investigations/<str:ip_no>/', views.get_patient_investigations, name='get_patient_investigations'),
    re_path(r'^patient-investigations/(?P<ip_no>[\w%/-]+)/$', views.get_patient_investigations, name='get_patient_investigations'),

     path("qrsubmit_form/", views.qrsubmit_form, name="qrsubmit_form"),
]
