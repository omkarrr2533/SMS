from django.urls import path
from . import views

urlpatterns = [
    # File management
    path('files/', views.file_list, name='file_list'),
    path('files/upload/', views.upload_excel, name='upload_excel'),
    path('files/upload/map-columns/', views.map_columns, name='map_columns'),
    path('files/upload/preview/', views.import_preview, name='import_preview'),
    path('files/<int:file_id>/', views.student_list, name='student_list'),
    path('files/<int:file_id>/delete/', views.file_delete, name='file_delete'),
    path('files/<int:file_id>/download/', views.file_download, name='file_download'),
    path('files/<int:file_id>/export/', views.smart_export, name='smart_export'),
    path('files/<int:file_id>/analytics/', views.file_analytics, name='file_analytics'),
    path('files/<int:file_id>/upload-photos/', views.bulk_photo_upload, name='bulk_photo_upload'),
    path('files/<int:file_id>/upload-photos/confirm/', views.confirm_photo_upload, name='confirm_photo_upload'),
    path('files/<int:file_id>/bulk-id-cards/', views.bulk_id_cards, name='bulk_id_cards'),
    path('my-files/', views.my_assigned_files, name='my_assigned_files'),

    # Student management
    path('students/<int:pk>/', views.student_profile, name='student_profile'),
    path('students/<int:pk>/edit/', views.student_edit, name='student_edit'),
    path('students/<int:pk>/delete/', views.student_delete, name='student_delete'),
    path('students/<int:pk>/pdf/', views.student_pdf, name='student_pdf'),
    path('students/<int:pk>/revert/<int:log_id>/', views.revert_edit, name='revert_edit'),
    path('students/<int:pk>/id-card/', views.student_id_card, name='student_id_card'),

    # Search
    path('search/', views.global_search, name='global_search'),
    path('api/search/', views.search_api, name='search_api'),
]
