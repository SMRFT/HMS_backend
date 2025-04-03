from django.urls import path
from . import views
from django.urls import re_path

urlpatterns = [
    path('register/', views.register_user, name='register_user'),
    path('create-stock/', views.create_stock_entry, name='create_stock_entry'),
    path('hsncodes/', views.hsn_code_list, name='hsn_code_list'),
    path('ventor/', views.ventor_list, name='ventor_list'),
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
    path('mri_investigations/', views.get_mri_investigations, name='get_mri_investigations'),  # Fetch all MRI reports
    path('mri_investigations/<str:uhid>/<str:subUhid>/', views.get_mri_patient_report, name='get_mri_patient_report'),  # Fetch specific MRI report by patientId
    path('mri-reports/', views.create_mri_report, name='create_mri_report'),
    path('mri_reports/', views.get_mri_reports, name='get_mri_reports'),  # Fetch all reports
    path('mri_reports/<str:patientId>/', views.get_mri_reports, name='get_mri_report'),  # Fetch specific report by patientId
    re_path(r'^mri-reports/(?P<patient_id>.+)/approve/$', views.approve_mri_report, name='approve_mri_report'),
    path('admission/', views.create_admission, name='create_admission'),
    path('admissions/', views.list_admissions, name='list_admissions'),
    path('summaries/', views.get_summaries, name='get_summaries'),
    path('summaries/create/', views.create_summary, name='create_summary'),
    path('reference-doctor/', views.save_reference_doctor, name='get_summary'),
    path('get-reference-doctors/',views.get_reference_doctors, name='get_reference_doctors'),
    re_path(r'^approve-summary/(?P<ip_no>.+)/$', views.approve_summary, name='approve_summary'),
    re_path(r'^delete-summary/(?P<ip_no>.+)/$', views.delete_summary, name='delete_summary'),
    re_path(r'^edit-editsummary/(?P<ip_no>.+)/$', views.get_editsummary, name='get_editsummary'),
    re_path(r'^update-summary/(?P<ip_no>.+)/$', views.update_summary_fields, name='update_summary_fields'),
    path("qrsubmit_form/", views.qrsubmit_form, name="qrsubmit_form"),

]
