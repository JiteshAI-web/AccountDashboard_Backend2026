from django.urls import path
from .views import search_banks
from . import views

from rest_framework_simplejwt.views import TokenRefreshView
urlpatterns = [
    path('auth/register/', views.register, name='register'),
    path('auth/login/', views.login, name='login'),
    path('auth/logout/', views.logout, name='logout'),
    path('auth/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('banks/search/', search_banks),
    path('bank-accounts/', views.list_bank_accounts, name='list_bank_accounts'),
    path('banks/init-company-folder/', views.init_company_folder, name='init_company_folder'),
    path('banks/create-folder/', views.create_drive_folder, name='create_drive_folder'),
    path('banks/create-folder/async/', views.create_drive_folder_async, name='create_drive_folder_async'),
    path('banks/upload-file/', views.upload_to_drive, name='upload_to_drive'),
    path('banks/upload-file/async/', views.upload_to_drive_async, name='upload_to_drive_async'),
    path('tasks/<str:task_id>/status/', views.task_status, name='task_status'),
    path('receipts/upload/', views.upload_receipt, name='upload_receipt'),

]