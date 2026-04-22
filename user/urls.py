from django.urls import path,include
from user.views import (
    login_view,
    generate_user_otp,
    dashboard,
    logout_view,
    like_business,
    business_detail,
    update_profile,
    save_business,
    saved_businesses,
    business_map,
    post_review,

    delete_profile_picture,
    generate_user_phone_otp,
    verify_user_phone_otp,
    like_review,
    chatbot_view,
    chatbot_message,
    clear_chatbot_history,
)

urlpatterns = [
    path('login/', login_view, name='login'),
    path('generate-otp/', generate_user_otp, name='generate_user_otp'),
    path('dashboard/', dashboard, name='dashboard'),
    path('logout/', logout_view, name='logout'),
    path('oauth/', include('social_django.urls', namespace='social')),  # Add Google login
    path('like/<int:business_id>/', like_business, name='like_business'),
    path('business/<int:business_id>/',business_detail, name='business_detail'),
    path('update-profile/', update_profile, name='update_profile'),
    path('save_business/<int:business_id>/', save_business, name='save_business'),
    path('saved/', saved_businesses, name='saved_businesses'),
    path('map/', business_map, name='business_map'),
    path('post-review/<int:business_id>/', post_review, name='post_review'),
    path('review-like/<int:review_id>/', like_review, name='like_review'),

    path('delete-profile-picture/', delete_profile_picture, name='delete_profile_picture'),
    path('generate-phone-otp/', generate_user_phone_otp, name='generate_user_phone_otp'),
    path('verify-phone-otp/', verify_user_phone_otp, name='verify_user_phone_otp'),
    path('chatbot/', chatbot_view, name='chatbot'),
    path('chatbot/message/', chatbot_message, name='chatbot_message'),
    path('chatbot/clear/', clear_chatbot_history, name='clear_chatbot_history'),
]
