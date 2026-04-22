import re
import uuid
import os
import random

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.models import User as AdminUser
from django.http import JsonResponse, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt

from django.conf import settings


from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.urls import reverse
from django.utils.encoding import force_bytes, force_str
from django.db.models import Count, Avg, F, Max, FloatField, ExpressionWrapper
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone
from datetime import timedelta

from Business.models import (
    User, Review, Business, BusinessImage, 
    Visitor, SocialMediaLink, OperatingHour, Message
)
from Business.forms import (
    LoginForm, BusinessForm, BusinessImageForm
)
from user.models import CustomUser

PHONE_PLACEHOLDER_DOMAIN = "phone.owner.local"
PHONE_REGEX = re.compile(r'^\+?\d{10,15}$')


def normalize_phone_number(value):
    return re.sub(r'\D', '', value or '')


def normalize_identifier(value):
    value = (value or '').strip()
    if '@' in value:
        return value.lower()

    normalized_phone = normalize_phone_number(value)
    if PHONE_REGEX.match(normalized_phone):
        return normalized_phone
    return value


def is_phone_identifier(value):
    return bool(PHONE_REGEX.match(value or ''))


def is_placeholder_email(email):
    return bool(email and email.endswith(f"@{PHONE_PLACEHOLDER_DOMAIN}"))


def build_owner_placeholder_email(phone_number):
    base = f"phone-{phone_number}@{PHONE_PLACEHOLDER_DOMAIN}"
    email = base
    counter = 1
    while User.objects.filter(email=email).exists():
        email = f"phone-{phone_number}-{counter}@{PHONE_PLACEHOLDER_DOMAIN}"
        counter += 1
    return email


def display_email_value(email):
    return '' if is_placeholder_email(email) else (email or '')


def owner_phone_used_elsewhere(phone_number, current_owner_id=None):
    if not phone_number:
        return False

    owners = User.objects.filter(phone_number=phone_number)
    if current_owner_id is not None:
        owners = owners.exclude(id=current_owner_id)

    return owners.exists() or CustomUser.objects.filter(phone_number=phone_number).exists()


def generate_owner_otp(request):
    if request.method == "POST":
        identifier = normalize_identifier(request.POST.get('email') or request.POST.get('identifier'))
        if not identifier:
            return JsonResponse({'success': False, 'message': 'Email or phone number is required.'})

        if is_phone_identifier(identifier):
            user = User.objects.filter(phone_number=identifier).first()
            if not user:
                if CustomUser.objects.filter(phone_number=identifier).exists():
                    return JsonResponse({'success': False, 'message': 'This phone number is already linked to a user account.'})
                user = User.objects.create(
                    email=build_owner_placeholder_email(identifier),
                    phone_number=identifier,
                    phone_verified=True,
                )
        else:
            try:
                validate_email(identifier)
            except ValidationError:
                return JsonResponse({'success': False, 'message': 'Enter a valid email address or phone number.'})
            user = User.objects.filter(email__iexact=identifier).first()
            if not user:
                # Auto-register new user
                user = User.objects.create(email=identifier)
                
                pass

        # Generate and session-store OTP
        otp = str(random.randint(100000, 999999))
        expiry = (timezone.now() + timedelta(minutes=5)).timestamp()
        request.session['pending_owner_otp'] = {
            'otp': otp,
            'expiry': expiry,
            'owner_id': user.id,
            'identifier': identifier
        }
        return JsonResponse({'success': True, 'otp': otp})
    return JsonResponse({'success': False, 'message': 'Invalid request.'})


def login(request):
    if request.method == "POST":
        form = LoginForm(request.POST)
        if form.is_valid():
            identifier = normalize_identifier(form.cleaned_data['email'])
            otp = request.POST.get('otp')
            
            pending = request.session.get('pending_owner_otp')
            
            if pending and pending['identifier'] == identifier:
                if pending['otp'] == otp and pending['expiry'] > timezone.now().timestamp():
                    owner = User.objects.filter(id=pending['owner_id']).first()
                    if not owner:
                        messages.error(request, "Owner account not found.")
                        return render(request, 'owner/login.html', {'form': form})
                    request.session['user_email'] = owner.email
                    # Clear OTP after successful login
                    del request.session['pending_owner_otp']
                    return redirect('home')
                else:
                    messages.error(request, "Invalid or expired OTP.")
            else:
                messages.error(request, "OTP session invalid or expired. Please request a new OTP.")
    else:
        form = LoginForm()
    return render(request, 'owner/login.html', {'form': form})


def ologout(request):
    request.session.flush()
    return redirect('ologin')


def home(request):
    # Check if the user is logged in
    if 'user_email' not in request.session:
        return redirect('ologin')  # Redirect if not logged in
    
    user_email = request.session['user_email']
    owner = User.objects.get(email=user_email)
    
    # Fetch all businesses owned by the logged-in user
    owner_businesses = Business.objects.filter(owner__email=user_email)
    
    # Check if the user already has an approved business
    has_approved_business = Business.objects.filter(
        owner__email=user_email,
        approval_status=True
    ).exists()
    
    # Analytics Data
    labels = []
    data = []
    visits_data = []
    total_likes = 0
    total_visits = 0
    total_reviews = 0
    avg_rating = 0.0
    recent_reviews = []
    top_rated_business = None
    most_visited_business = None
    
    traffic_labels = []
    traffic_values = []
    
    if has_approved_business:
        approved_businesses = owner_businesses.filter(approval_status=True)
        
        # Basic Stats
        labels = [business.name for business in approved_businesses]
        data = [business.total_likes() for business in approved_businesses]
        visits_data = [business.visitors.count() for business in approved_businesses]
        total_likes = sum(data)
        total_visits = sum(visits_data)
        
        # Advanced Stats
        all_reviews = Review.objects.filter(business__in=approved_businesses)
        total_reviews = all_reviews.count()
        avg_rating = all_reviews.aggregate(Avg('rating'))['rating__avg'] or 0.0
        recent_reviews = all_reviews.order_by('-created_at')[:5]
        
        # Top Performers
        if approved_businesses.exists():
            # Get business with most visits
            most_visited_business = approved_businesses.annotate(
                v_count=Count('visitors')
            ).order_by('-v_count').first()
            
            # Get business with highest rating
            top_rated_business = approved_businesses.annotate(
                r_avg=Avg('reviews__rating')
            ).order_by('-r_avg').first()

        # Traffic Trend (Last 30 Days)
        thirty_days_ago = timezone.now() - timedelta(days=30)
        daily_visits = Visitor.objects.filter(
            business__in=approved_businesses,
            visit_time__gte=thirty_days_ago
        ).annotate(
            date=TruncDate('visit_time')
        ).values('date').annotate(
            count=Count('id')
        ).order_by('date')
        
        traffic_labels = [item['date'].strftime('%d %b') for item in daily_visits]
        traffic_values = [item['count'] for item in daily_visits]

    return render(request, 'owner/home.html', {
        'user_email': user_email,
        'owner': owner,
        'businesses': owner_businesses,
        'labels': labels,
        'data': data,
        'visits_data': visits_data,
        'total_likes': total_likes,
        'total_visits': total_visits,
        'total_reviews': total_reviews,
        'avg_rating': round(avg_rating, 1),
        'recent_reviews': recent_reviews,
        'top_rated_business': top_rated_business,
        'most_visited_business': most_visited_business,
        'traffic_labels': traffic_labels,
        'traffic_values': traffic_values,
        'has_approved_business': has_approved_business
    })



def add(request):
    # Check if 'user_email' is in the session
    if 'user_email' not in request.session:
        messages.error(request, "You must be logged in to add a business.")
        return redirect('ologin')  # Redirect to login page or any other page

    # Get the logged-in user from the session
    user_email = request.session['user_email']
    owner = User.objects.get(email=user_email)

    if request.method == 'POST':
        form = BusinessForm(request.POST, request.FILES)
        files = request.FILES.getlist('business_images')
        
        if form.is_valid():
            mobile_number = form.cleaned_data.get('mobile_number')
            verified_number = request.session.get('phone_otp_verified')

            # Allow if number matches owner's already-verified profile phone
            profile_phone_is_verified = (
                owner.phone_number and
                owner.phone_verified and
                owner.phone_number == mobile_number
            )

            if not profile_phone_is_verified and verified_number != mobile_number:
                messages.error(request, "Please verify the mobile number before adding the business.")
                return render(request, 'owner/add_business.html', {
                    'form': form,
                    'user_email': user_email,
                    'owner': owner,
                    'profile_phone': owner.phone_number or '',
                    'profile_phone_verified': owner.phone_verified,
                })
            
            # Create a new business and assign the logged-in user as the owner
            business = form.save(commit=False)
            business.owner = owner  # Automatically set the owner
            
            # Logic to extract name if not provided (though form field is there, user might not change it)
            if not business.name:
                 clean_name = re.sub(r'\d+', '', user_email.split('@')[0])
                 business.name = clean_name.title()

            business.save()  # Save the business
            
            # Handle the business images
            for file in files:
                BusinessImage.objects.create(business=business, image=file)
            
            # Handle Social Media Links
            # Expected POST data format: social_platform_1, social_url_1, social_platform_2...
            for key in request.POST:
                if key.startswith('social_platform_'):
                    index = key.split('_')[-1]
                    platform = request.POST.get(f'social_platform_{index}')
                    url = request.POST.get(f'social_url_{index}')
                    if platform and url:
                        SocialMediaLink.objects.create(business=business, platform=platform, url=url)

            # Handle Operating Hours
            # Expected POST data: hours_open_0, hours_close_0, hours_closed_0 (for Monday=0)
            for day_code in range(7): # 0 to 6
                open_time = request.POST.get(f'hours_open_{day_code}')
                close_time = request.POST.get(f'hours_close_{day_code}')
                is_closed = request.POST.get(f'hours_closed_{day_code}') == 'on'
                
                if open_time == '': open_time = None
                if close_time == '': close_time = None
                
                # Only create if there's data (or if it's explicitly closed)
                if open_time or close_time or is_closed:
                    OperatingHour.objects.create(
                        business=business,
                        day_of_week=day_code,
                        open_time=open_time,
                        close_time=close_time,
                        is_closed=is_closed
                    )

            pass


            









            
            messages.success(request, "Your request was sent successfully. Please wait for admin approval.")
            return redirect('addbusiness')  # Or redirect to another page after successful submission
    else:
        # Auto-fill name logic
        clean_name = re.sub(r'\d+', '', user_email.split('@')[0]).title()
        initial_data = {
            'email': user_email,
            'name': clean_name,
            'mobile_number': owner.phone_number or '',  # Pre-fill from verified profile phone
        }
        form = BusinessForm(initial=initial_data)

    return render(request, 'owner/add_business.html', {
        'form': form,
        'user_email': user_email,
        'owner': owner,
        'profile_phone': owner.phone_number or '',
        'profile_phone_verified': owner.phone_verified,
    })


def edit_business(request, business_id):
    if 'user_email' not in request.session:
        messages.error(request, "You must be logged in.")
        return redirect('ologin')
        
    user_email = request.session['user_email']
    owner = get_object_or_404(User, email=user_email)
    business = get_object_or_404(Business, id=business_id, owner=owner)
    
    if request.method == 'POST':
        if 'delete_image' in request.POST:
            image_id = request.POST.get('delete_image')
            image = get_object_or_404(BusinessImage, id=image_id)
            if image.business.id == business.id:
                image.delete()
                messages.success(request, "Image deleted successfully.")
            return redirect('owner_edit_business', business_id=business.id)

        form = BusinessForm(request.POST, request.FILES, instance=business)
        files = request.FILES.getlist('business_images')
        
        if form.is_valid():
            business = form.save()
            
            for file in files:
                BusinessImage.objects.create(business=business, image=file)
            
            SocialMediaLink.objects.filter(business=business).delete()
            for key in request.POST:
                if key.startswith('social_platform_'):
                    index = key.split('_')[-1]
                    platform = request.POST.get(f'social_platform_{index}')
                    url = request.POST.get(f'social_url_{index}')
                    if platform and url:
                        SocialMediaLink.objects.create(business=business, platform=platform, url=url)
            
            OperatingHour.objects.filter(business=business).delete()
            for day_code in range(7):
                open_time = request.POST.get(f'hours_open_{day_code}')
                close_time = request.POST.get(f'hours_close_{day_code}')
                is_closed = request.POST.get(f'hours_closed_{day_code}') == 'on'
                
                if open_time == '': open_time = None
                if close_time == '': close_time = None
                
                if open_time or close_time or is_closed:
                    OperatingHour.objects.create(
                        business=business,
                        day_of_week=day_code,
                        open_time=open_time,
                        close_time=close_time,
                        is_closed=is_closed
                    )

            messages.success(request, "Business updated successfully!")
            return redirect('owner_edit_business', business_id=business.id)
    else:
        form = BusinessForm(instance=business)
    
    social_links = list(SocialMediaLink.objects.filter(business=business).values('platform', 'url'))
    operating_hours = OperatingHour.objects.filter(business=business)
    hours_data = {}
    for oh in operating_hours:
        hours_data[oh.day_of_week] = oh
        
    return render(request, 'owner/edit_business.html', {
        'form': form, 
        'business': business,
        'social_links': social_links,
        'hours_data': hours_data,
        'user_email': user_email,
        'owner': owner
    })

def manage_business(request):
    if 'user_email' not in request.session:
        messages.error(request, "You must be logged in to manage the business.")
        return redirect('ologin')

    try:
        user_email = request.session['user_email']
        owner = User.objects.get(email=user_email)
        businesses = Business.objects.filter(owner=owner, approval_status=True)
        
        # Calculate trending ranks globally
        businesses_qs = Business.objects.filter(approval_status=True).annotate(
            like_count=Count('likes', distinct=True),
            visitor_count=Count('visitors', distinct=True),
            avg_rating=Coalesce(Avg('reviews__rating'), 0.0)
        ).annotate(
            trending_score=ExpressionWrapper(
                F('like_count') + F('visitor_count') + F('avg_rating'),
                output_field=FloatField()
            )
        ).order_by('-trending_score', '-id')

        all_ids = list(businesses_qs.values_list('id', flat=True))
        trending_data = {}
        for b in businesses:
            try:
                rank = all_ids.index(b.id) + 1
                score = businesses_qs.get(id=b.id).trending_score
                if rank <= 10 and score > 0:
                    trending_data[b.id] = rank
            except (ValueError, Business.DoesNotExist):
                pass

        # Prepare business images data
        business_images_data = {}
        for business in businesses:
            business_images_data[business.id] = [img.image.url for img in business.images.all()]
            
        context = {
            'businesses': businesses,
            'business_images_data': business_images_data,
            'owner': owner,
            'user_email': user_email,
            'trending_data': trending_data
        }
        return render(request, 'owner/manage_business.html', context)
    except User.DoesNotExist:
        messages.error(request, "User account not found.")
        return redirect('ologin')



def update_business(request, business_id):
    if 'user_email' not in request.session:
        return JsonResponse({'success': False, 'message': 'Authentication required'}, status=401)

    try:
        business = get_object_or_404(Business, id=business_id, owner__email=request.session['user_email'])

        if request.method == 'POST':
            # Updating business details
            business.name = request.POST.get('name', business.name)
            business.shop = request.POST.get('shop', business.shop)
            business.mobile_number = request.POST.get('mobile_number', business.mobile_number)
            business.business_type = request.POST.get('business_type', business.business_type)
            business.google_map_location = request.POST.get('google_map_location', business.google_map_location)
            business.business_address = request.POST.get('business_address', business.business_address)
            business.description = request.POST.get('description', business.description)
            business.hours_of_operation = request.POST.get('hours_of_operation', business.hours_of_operation)

            # Handling image upload
            image_file = request.FILES.get('image')
            if image_file:
                new_image = BusinessImage(business=business, image=image_file)
                new_image.save()

            business.save()
            return JsonResponse({'success': True, 'message': 'Business updated successfully.'})

    except Business.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Business not found'}, status=404)
    
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

    return HttpResponseForbidden()


# def upload_image(request, business_id):
#     if 'user_email' not in request.session:
#         messages.error(request, "You must be logged in to upload images.")
#         return JsonResponse({'success': False, 'message': 'Authentication required'}, status=401)

#     try:
#         business = get_object_or_404(Business, id=business_id, owner__email=request.session['user_email'])

#         if request.method == 'POST' and request.FILES.get('image'):
#             form = BusinessImageForm(request.POST, request.FILES)
#             if form.is_valid():
#                 image = form.save(commit=False)
#                 image.business = business
#                 image.save()
#                 messages.success(request, "Image uploaded successfully.")
#                 return JsonResponse({
#                     'success': True,
#                     'image_url': image.image.url,
#                     'image_id': image.id
#                 })
#             return JsonResponse({'success': False, 'message': 'Invalid image format.'}, status=400)

#     except Exception as e:
#         return JsonResponse({'success': False, 'message': str(e)}, status=500)

#     return JsonResponse({'success': False, 'message': 'Invalid request.'})

def delete_image(request, image_id):
    if 'user_email' not in request.session:
        messages.error(request, "You must be logged in to delete images.")
        return JsonResponse({'success': False, 'message': 'Authentication required'}, status=401)

    try:
        image = get_object_or_404(BusinessImage, id=image_id, business__owner__email=request.session['user_email'])

        if request.method == 'POST':
            image.delete()
            messages.success(request, "Image deleted successfully.")
            return JsonResponse({'success': True, 'message': 'Image deleted successfully.'})

    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

    return JsonResponse({'success': False, 'message': 'Invalid request.'})

@csrf_exempt
def delete_business(request, business_id):
    if request.method == 'POST':
        try:
            # Get the business object
            business = Business.objects.get(id=business_id)
            # Delete the business
            business.delete()
            return JsonResponse({'success': True})
        except Business.DoesNotExist:
            return JsonResponse({'success': False, 'message': 'Business not found'})
    return JsonResponse({'success': False, 'message': 'Invalid request'})

def visited_users(request, business_id):
    if 'user_email' not in request.session:
        return redirect('ologin')

    business = get_object_or_404(Business, id=business_id)

    # Only allow the owner to see visitors
    if business.owner.email != request.session['user_email']:
        return redirect('home')

    # Fetch all visitors for this business
    visitors = Visitor.objects.filter(business=business).select_related('user')

    return render(request, 'owner/visitedusers.html', {
        'business': business,
        'visitors': visitors
    })

def contact_us(request):
    if 'user_email' not in request.session:
        return redirect('ologin')

    user_email = request.session['user_email']
    owner = User.objects.get(email=user_email)
    
    if request.method == "POST":
        message_content = request.POST.get("message")
        if message_content:
            Message.objects.create(owner=owner, content=message_content, is_from_owner=True)
            return redirect("contact_us")

    # Mark messages from Admin as seen
    Message.objects.filter(owner=owner, is_from_owner=False, is_seen=False).update(is_seen=True)

    messages_list = Message.objects.filter(owner=owner).order_by('timestamp')

    return render(request, "owner/contact.html", {
        "user_email": user_email, 
        "owner": owner,
        "messages": messages_list
    })




def success_page(request):
    return render(request, "owner/success.html")

def owner_reviews(request, business_id=None):
    if 'user_email' not in request.session:
        return redirect('ologin')

    user_email = request.session['user_email']
    user = get_object_or_404(User, email=user_email)  # Retrieve user based on session email

    if business_id:
        # Get specific business ensuring it belongs to the owner
        business = get_object_or_404(Business, id=business_id, owner=user)
        reviews = Review.objects.filter(business=business)
        context = {'reviews': reviews, 'current_business': business, 'owner': user, 'user_email': user_email}
    else:
        # Get all businesses and their reviews
        owner_businesses = Business.objects.filter(owner=user)
        reviews = Review.objects.filter(business__in=owner_businesses)
        context = {'reviews': reviews, 'owner': user, 'user_email': user_email}
    
    return render(request, 'owner/owner_reviews.html', context)

def delete_review(request, review_id):
    if 'user_email' not in request.session:
        return redirect('ologin')

    user_email = request.session['user_email']
    user = get_object_or_404(User, email=user_email)

    review = get_object_or_404(Review, id=review_id, business__owner=user)
    
    if request.method == 'POST':
        review.delete()
        return redirect('owner_reviews')

    return render(request, 'owner/confirm_delete.html', {'review': review})


def handle_owner_google_auth(backend, user, response, request, *args, **kwargs):
    """
    Custom pipeline step to handle Google Login for Business Owners.
    It intercepts the flow for 'owner-google-oauth2' backend.
    """
    if backend.name == 'owner-google-oauth2':
        email = response.get('email')
        if not email:
            messages.error(request, "Google account does not have a verified email.")
            return redirect('ologin')

        # Check if owner exists in Business.models.User
        existing_owner = User.objects.filter(email=email).first()
        
        picture = response.get('picture') # Get Google Profile Image

        if not existing_owner:
            # Create new owner
            new_owner = User.objects.create(email=email, profile_image=picture) 
            request.session['user_email'] = new_owner.email
        else:
            # Update profile image if changed or empty
            if picture and existing_owner.profile_image != picture:
                existing_owner.profile_image = picture
                existing_owner.save()
            request.session['user_email'] = existing_owner.email
            
        # Redirect to Owner Home
        return redirect('home')
        
    return None # Continue pipeline for other backends (like standard user login)


def owner_user_details(backend, response, user=None, is_new=False, *args, **kwargs):
    """
    Custom pipeline step for Business Owner Google OAuth.
    Only updates the profile_image field with the picture URL if it exists.
    """
    if backend.name == 'owner-google-oauth2':
        picture = response.get('picture')
        if picture and user:
            # Only update profile_image if it's empty or different
            if not user.profile_image or user.profile_image != picture:
                user.profile_image = picture
                user.save(update_fields=['profile_image'])
    return None


@csrf_exempt
def generate_phone_otp(request):
    if request.method == "POST":
        phone_number = request.POST.get('phone_number')
        if not phone_number:
            return JsonResponse({'success': False, 'message': 'Phone number is required.'})
        
        # Generate and store OTP in session
        otp = str(random.randint(100000, 999999))
        request.session['pending_phone_otp'] = {
            'number': phone_number,
            'otp': otp,
            'expiry': (timezone.now() + timedelta(minutes=5)).timestamp()
        }
        return JsonResponse({'success': True, 'otp': otp})
    return JsonResponse({'success': False, 'message': 'Invalid request.'})


@csrf_exempt
def verify_phone_otp(request):
    if request.method == "POST":
        otp = request.POST.get('otp')
        pending = request.session.get('pending_phone_otp')
        
        if pending and pending['otp'] == otp and pending['expiry'] > timezone.now().timestamp():
            # Set a temporary verified flag in session
            request.session['phone_otp_verified'] = pending['number']
            return JsonResponse({'success': True})
        else:
            return JsonResponse({'success': False, 'message': 'Invalid or expired OTP.'})
    return JsonResponse({'success': False, 'message': 'Invalid request.'})


def owner_profile(request):
    if 'user_email' not in request.session:
        return redirect('ologin')
    
    user_email = request.session['user_email']
    user = get_object_or_404(User, email=user_email)
    
    if request.method == "POST":
        phone_number = normalize_phone_number(request.POST.get('phone_number'))
        new_email = normalize_identifier(request.POST.get('email'))
        
        # Check if phone matches the verified one in session
        verified_number = request.session.get('phone_otp_verified')

        if new_email and is_phone_identifier(new_email):
            messages.error(request, "Please enter a valid email address.")
            return redirect('owner_profile')

        if new_email:
            try:
                validate_email(new_email)
            except ValidationError:
                messages.error(request, "Please enter a valid email address.")
                return redirect('owner_profile')

        if new_email and User.objects.filter(email__iexact=new_email).exclude(id=user.id).exists():
            messages.error(request, "That email address is already in use.")
            return redirect('owner_profile')

        if owner_phone_used_elsewhere(phone_number, current_owner_id=user.id):
            messages.error(request, "This phone number is already used by another account.")
            return redirect('owner_profile')

        if verified_number and phone_number and verified_number == phone_number:
            user.phone_number = phone_number
            user.phone_verified = True

            del request.session['phone_otp_verified']
            if 'pending_phone_otp' in request.session:
                del request.session['pending_phone_otp']
        elif phone_number != (user.phone_number or ''):
            if phone_number:
                messages.error(request, "Please verify your phone number before saving.")
                return redirect('owner_profile')
            user.phone_number = None
            user.phone_verified = False

        if new_email:
            user.email = new_email
        user.save()
        request.session['user_email'] = user.email

        messages.success(request, "Profile updated successfully.")
        return redirect('owner_profile')
    
    return render(request, 'owner/profile.html', {'owner': user, 'profile_email': display_email_value(user.email)})
