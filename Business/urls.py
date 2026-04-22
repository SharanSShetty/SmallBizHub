from django.urls import path
from Business import views

urlpatterns = [
    path('owner/login/', views.login, name='ologin'),
    path('logout/', views.ologout, name='ologout'),
    path('home/', views.home, name='home'),
    path('addbusiness',views.add,name='addbusiness'),
    path('manage_business/', views.manage_business, name='owner_manage_business'),
    path('edit_business/<int:business_id>/', views.edit_business, name='owner_edit_business'),
    path('update_business/<int:business_id>/', views.update_business, name='update_business'),
    # path('upload_image/<int:business_id>/', views.upload_image, name='upload_image'),
    path('delete_image/<int:image_id>/', views.delete_image, name='delete_image'),
    path('delete_business/<int:business_id>/', views.delete_business, name='delete_business'),
     path('business/<int:business_id>/visitors/', views.visited_users, name='visited_users'), 
     path("contact/", views.contact_us, name="contact_us"),
     path("success/", views.success_page, name="success_page"), 
     path('otp/', views.generate_owner_otp, name='generate_owner_otp'),
    path('reviews/', views.owner_reviews, name='owner_reviews'),
    path('reviews/<int:business_id>/', views.owner_reviews, name='owner_business_reviews'),
    path('delete/<int:review_id>/', views.delete_review, name='delete_review'),
    path('profile/', views.owner_profile, name='owner_profile'),
    path('generate-phone-otp/', views.generate_phone_otp, name='generate_phone_otp'),
    path('verify-phone-otp/', views.verify_phone_otp, name='verify_phone_otp'),
]
