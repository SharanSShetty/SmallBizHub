from django.urls import path
from handle import views

urlpatterns = [
    path('aregister/', views.admin_register, name='admin_register'),
    path('alogin/', views.admin_login, name='admin_login'),
    path('ahome/', views.admin_home, name='admin_home'),
    path('alogout/', views.admin_logout, name='admin_logout'),
    path('approve-businesses', views.approve, name='approve_businesses'),
    path('manage_business/', views.manage_business, name='manage_business'),
    path('edit_business/<int:business_id>/', views.edit_business, name='edit_business'),
    path('manage/', views.manage_users, name='manage_users'),
    path('chat/', views.admin_chat_list, name='admin_chat_list'),
    path('chat/<int:owner_id>/', views.admin_chat_detail, name='admin_chat_detail'),
    path('delete_chat/<int:owner_id>/', views.delete_chat, name='delete_chat'),
]
