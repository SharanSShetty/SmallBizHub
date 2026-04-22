import json
import os
import random
import re
from datetime import timedelta
from django.utils import timezone

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from user.models import CustomUser
from user.forms import LoginForm
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from user.chatbot import build_chatbot_context, generate_chatbot_reply
from django.http import JsonResponse
from Business.models import Business,Visitor,Review, User as OwnerUser
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.views.decorators.http import require_POST
from django.db.models import Count, Avg, F, FloatField, ExpressionWrapper
from django.db.models.functions import Coalesce

PHONE_PLACEHOLDER_DOMAIN = "phone.user.local"
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


def build_placeholder_email(phone_number):
    base = f"phone-{phone_number}@{PHONE_PLACEHOLDER_DOMAIN}"
    email = base
    counter = 1
    while CustomUser.objects.filter(email=email).exists():
        email = f"phone-{phone_number}-{counter}@{PHONE_PLACEHOLDER_DOMAIN}"
        counter += 1
    return email


def build_username(seed):
    base_username = re.sub(r'[^a-zA-Z0-9_]', '', seed) or 'user'
    username = base_username
    counter = 1
    while CustomUser.objects.filter(username=username).exists():
        username = f"{base_username}{counter}"
        counter += 1
    return username


def display_email_value(email):
    return '' if is_placeholder_email(email) else (email or '')


def phone_used_elsewhere(phone_number, current_user_id=None):
    if not phone_number:
        return False

    in_users = CustomUser.objects.filter(phone_number=phone_number)
    if current_user_id is not None:
        in_users = in_users.exclude(id=current_user_id)

    return in_users.exists() or OwnerUser.objects.filter(phone_number=phone_number).exists()

def generate_user_otp(request):
    if request.method == "POST":
        data = json.loads(request.body) if request.content_type == 'application/json' else request.POST
        identifier = normalize_identifier(data.get('email') or data.get('identifier'))
        if not identifier:
            return JsonResponse({'success': False, 'message': 'Email or phone number is required.'})

        if is_phone_identifier(identifier):
            user = CustomUser.objects.filter(phone_number=identifier).first()
            if not user:
                if OwnerUser.objects.filter(phone_number=identifier).exists():
                    return JsonResponse({'success': False, 'message': 'This phone number is already linked to an owner account.'})
                user = CustomUser.objects.create(
                    username=build_username(f'user{identifier[-4:]}'),
                    email=build_placeholder_email(identifier),
                    phone_number=identifier,
                    phone_verified=True,
                )
        else:
            try:
                validate_email(identifier)
            except ValidationError:
                return JsonResponse({'success': False, 'message': 'Enter a valid email address or phone number.'})
            user = CustomUser.objects.filter(email__iexact=identifier).first()
            if not user:
                user = CustomUser.objects.create(
                    username=build_username(identifier.split('@')[0]),
                    email=identifier
                )

        # Generate and session-store OTP
        otp = str(random.randint(100000, 999999))
        expiry = (timezone.now() + timedelta(minutes=5)).timestamp()
        request.session['pending_user_otp'] = {
            'otp': otp,
            'expiry': expiry,
            'user_id': user.id,
            'identifier': identifier,
        }
        return JsonResponse({'success': True, 'otp': otp})
    return JsonResponse({'success': False, 'message': 'Invalid request.'})

def login_view(request):
    if request.method == "POST":
        form = LoginForm(request.POST)
        if form.is_valid():
            identifier = normalize_identifier(form.cleaned_data['email'])
            otp = request.POST.get('otp')
 
            pending = request.session.get('pending_user_otp')
            
            if pending and pending['identifier'] == identifier:
                if pending['otp'] == otp and pending['expiry'] > timezone.now().timestamp():
                    user = CustomUser.objects.filter(id=pending['user_id']).first()
                    if user:
                        request.session['username'] = user.username
                        # Clear OTP after successful login
                        del request.session['pending_user_otp']
                        messages.success(request, f"Welcome, {user.username}!")
                        return redirect('dashboard')
                    else:
                        messages.error(request, "User record not found.")
                else:
                    messages.error(request, "Invalid or expired OTP.")
            else:
                messages.error(request, "OTP session invalid or expired. Please request a new OTP.")
 
    else:
        form = LoginForm()
    return render(request, 'user/login.html', {'form': form})


def dashboard(request):
    if 'username' not in request.session:
        return redirect('login')  # Ensure user is logged in
        
    user = CustomUser.objects.get(username=request.session['username'])  # Get logged-in user
    query = request.GET.get('search', '')
    
    businesses_qs = Business.objects.filter(approval_status=True).annotate(
        like_count=Count('likes', distinct=True),
        visitor_count=Count('visitors', distinct=True),
        avg_rating=Coalesce(Avg('reviews__rating'), 0.0)
    ).annotate(
        trending_score=ExpressionWrapper(
            F('like_count') + F('visitor_count') + F('avg_rating'),
            output_field=FloatField()
        )
    ).order_by('-trending_score')
    
    top_trending_ids = list(businesses_qs.filter(trending_score__gt=0).values_list('id', flat=True)[:3])
    businesses = businesses_qs
        
    if query:
        businesses = businesses.filter(
            name__icontains=query
        ) | businesses.filter(
            shop__icontains=query
        ) | businesses.filter(
            business_address__icontains=query
        )
        
    # Add attributes
    for business in businesses:
        business.is_liked = business.likes.filter(id=user.id).exists()
        business.is_trending = business.id in top_trending_ids
        
    return render(request, 'user/dashboard.html', {
        'businesses': businesses,
        'username': request.session['username'],
        'user': user,
        'profile_email': display_email_value(user.email),
    })

def like_business(request, business_id):
    if request.method == "POST":
        if 'username' not in request.session:
            return JsonResponse({"error": "User not authenticated"}, status=401)

        user = CustomUser.objects.get(username=request.session['username'])
        business = get_object_or_404(Business, id=business_id)

        if business.likes.filter(id=user.id).exists():
            business.likes.remove(user)
            liked = False
        else:
            business.likes.add(user)
            liked = True

        return JsonResponse({"liked": liked, "total_likes": business.total_likes()})

    return JsonResponse({"error": "Invalid request"}, status=400)

def business_detail(request, business_id):
    if 'username' not in request.session:
        return redirect('login')  # Ensure user is logged in
    
    business = get_object_or_404(Business, id=business_id)
    user = CustomUser.objects.get(username=request.session['username'])  # Get logged-in user
    
    # Calculate trending rank
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

    # Get the position of the business
    all_ids = list(businesses_qs.values_list('id', flat=True))
    try:
        trending_rank = all_ids.index(business.id) + 1
        # Get the score to check if it's > 0
        current_score = businesses_qs.get(id=business_id).trending_score
        is_trending = trending_rank <= 10 and current_score > 0
    except (ValueError, Business.DoesNotExist):
        trending_rank = None
        is_trending = False

    # Track visitor if they haven't visited before
    Visitor.objects.get_or_create(business=business, user=user)
    
    # Get reviews for this business
    reviews = Review.objects.filter(business=business).order_by('-created_at')
    
    # Check if business is saved by user
    is_saved = user.saved_businesses.filter(id=business.id).exists()
    
    # Return with both business and reviews in the context
    return render(request, 'user/business_detail.html', {
        'business': business,
        'reviews': reviews,
        'is_saved': is_saved,
        'trending_rank': trending_rank,
        'is_trending': is_trending
    })


def logout_view(request):
    request.session.flush()
    messages.success(request, "You have been logged out.")
    return redirect('login')

def save_google_user(backend, user, response, request, *args, **kwargs):
    if backend.name == 'google-oauth2':
        email = response.get('email')
        username = email.split('@')[0]  # Extract username before '@'

        # Get Google profile picture URL
        picture_url = response.get('picture')

        # Check if user exists
        existing_user = CustomUser.objects.filter(email=email).first()
        if not existing_user:
            # Create a new user
            new_user = CustomUser.objects.create(username=username, email=email, google_profile_image=picture_url)
            new_user.save()
            request.session['username'] = new_user.username  # Store new user's username
        else:
            # Update existing user's Google profile image if it changed or wasn't set
            if picture_url and existing_user.google_profile_image != picture_url:
                existing_user.google_profile_image = picture_url
                existing_user.save()
            
            request.session['username'] = existing_user.username  # Store existing user's username

    # return redirect('/users/dashboard/')  # Redirect after login
    return None # Allow the pipeline to continue

def update_profile(request):
    if request.method == 'POST':
        if 'username' not in request.session:
            return redirect('login')
            
        try:
            # Get the user from the session username
            user = CustomUser.objects.get(username=request.session['username'])
            original_session_username = request.session['username']
            new_username = (request.POST.get('username') or '').strip()
            new_email = normalize_identifier(request.POST.get('email'))
            phone_number = (request.POST.get('phone_number') or '').strip()
            verified_number = request.session.get('user_phone_otp_verified')
            
            if not new_username:
                messages.error(request, 'Username is required.')
                return redirect('dashboard')

            if CustomUser.objects.filter(username=new_username).exclude(id=user.id).exists():
                messages.error(request, 'That username is already in use.')
                return redirect('dashboard')

            if new_email and is_phone_identifier(new_email):
                messages.error(request, 'Please enter a valid email address in the email field.')
                return redirect('dashboard')

            if new_email:
                try:
                    validate_email(new_email)
                except ValidationError:
                    messages.error(request, 'Please enter a valid email address.')
                    return redirect('dashboard')

            if new_email and CustomUser.objects.filter(email__iexact=new_email).exclude(id=user.id).exists():
                messages.error(request, 'That email address is already in use.')
                return redirect('dashboard')

            phone_number = normalize_phone_number(phone_number)
            if phone_used_elsewhere(phone_number, current_user_id=user.id):
                messages.error(request, 'This phone number is already used by another account.')
                return redirect('dashboard')

            if verified_number and phone_number and verified_number == phone_number:
                user.phone_number = phone_number
                user.phone_verified = True

                if 'user_phone_otp_verified' in request.session:
                    del request.session['user_phone_otp_verified']
                if 'pending_user_phone_otp' in request.session:
                    del request.session['pending_user_phone_otp']

            elif phone_number != (user.phone_number or ''):
                if phone_number:
                    if verified_number != phone_number:
                        messages.error(request, 'Please verify your phone number before saving.')
                        return redirect('dashboard')
                    user.phone_verified = True
                else:
                    user.phone_verified = False

                user.phone_number = phone_number or None

                if 'user_phone_otp_verified' in request.session:
                    del request.session['user_phone_otp_verified']
                if 'pending_user_phone_otp' in request.session:
                    del request.session['pending_user_phone_otp']

            # Update user details (excluding email)
            user.username = new_username
            if new_email:
                user.email = new_email
            
            # Update profile image if provided
            if 'profile_picture' in request.FILES:
                user.profile = request.FILES['profile_picture']
            
            user.save()
            
            # Update the session username if it changed
            if user.username != original_session_username:
                request.session['username'] = user.username
                
            messages.success(request, 'Profile updated successfully!')
        except CustomUser.DoesNotExist:
            messages.error(request, 'User not found!')
        
        return redirect('dashboard')
    
    return redirect('dashboard')

def delete_profile_picture(request):
    if request.method == "POST":
        if 'username' not in request.session:
            return JsonResponse({'success': False, 'error': 'Not logged in'}, status=401)
        
        try:
            user = CustomUser.objects.get(username=request.session['username'])
            if user.profile:
                # Store path before deletion
                if user.profile and hasattr(user.profile, 'path'):
                    profile_path = user.profile.path
                    if os.path.isfile(profile_path):
                        os.remove(profile_path)
                
                user.profile = None
                user.save()
                
                return JsonResponse({'success': True})
            else:
                return JsonResponse({'success': False, 'error': 'No profile picture to delete'})
        except CustomUser.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'User not found'}, status=404)
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=500)
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=400)


@csrf_exempt
def generate_user_phone_otp(request):
    if request.method == "POST":
        phone_number = request.POST.get('phone_number')
        if not phone_number:
            return JsonResponse({'success': False, 'message': 'Phone number is required.'})

        otp = str(random.randint(100000, 999999))
        request.session['pending_user_phone_otp'] = {
            'number': phone_number,
            'otp': otp,
            'expiry': (timezone.now() + timedelta(minutes=5)).timestamp()
        }
        return JsonResponse({'success': True, 'otp': otp})
    return JsonResponse({'success': False, 'message': 'Invalid request.'})


@csrf_exempt
def verify_user_phone_otp(request):
    if request.method == "POST":
        otp = request.POST.get('otp')
        pending = request.session.get('pending_user_phone_otp')

        if pending and pending['otp'] == otp and pending['expiry'] > timezone.now().timestamp():
            request.session['user_phone_otp_verified'] = pending['number']
            return JsonResponse({'success': True})
        return JsonResponse({'success': False, 'message': 'Invalid or expired OTP.'})
    return JsonResponse({'success': False, 'message': 'Invalid request.'})

def save_business(request, business_id):
    # Ensure the user is authenticated via session
    if 'username' not in request.session:
        return JsonResponse({'message': 'Unauthorized'}, status=401)

    try:
        # Get the user from the session
        user = CustomUser.objects.get(username=request.session['username'])
        business = get_object_or_404(Business, id=business_id)

        # Toggle save/unsave
        if business in user.saved_businesses.all():
            user.saved_businesses.remove(business)
            return JsonResponse({'message': 'Unsaved'})
        else:
            user.saved_businesses.add(business)
            return JsonResponse({'message': 'Saved'})
    
    except CustomUser.DoesNotExist:
        return JsonResponse({'message': 'User not found'}, status=404)

    return JsonResponse({'message': 'Error'}, status=400)


def saved_businesses(request):
    # Ensure the user is authenticated via session
    if 'username' not in request.session:
        return redirect('login')

    try:
        # Get the logged-in user
        user = CustomUser.objects.get(username=request.session['username'])

        # Fetch all saved businesses
        saved_businesses = user.saved_businesses.all()

        return render(request, 'user/saved_businesses.html', {'saved_businesses': saved_businesses})

    except CustomUser.DoesNotExist:
        return redirect('login')


def business_map(request):
    # Ensure the user is authenticated via session
    if 'username' not in request.session:
        return redirect('login')

    user = CustomUser.objects.get(username=request.session['username'])
    # Fetch approved businesses for the map
    businesses = Business.objects.filter(approval_status=True)

    return render(request, 'user/business_map.html', {
        'businesses': businesses,
        'username': request.session['username'],
        'user': user
    })

def chatbot_view(request):
    if 'username' not in request.session:
        return redirect('login')

    user = get_object_or_404(CustomUser, username=request.session['username'])
    history = request.session.get('chatbot_history', [])

    return render(request, 'user/chatbot.html', {
        'user': user,
        'username': user.username,
        'history': history,
    })


@require_POST
def chatbot_message(request):
    if 'username' not in request.session:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    user = get_object_or_404(CustomUser, username=request.session['username'])

    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON payload.'}, status=400)

    message = (payload.get('message') or '').strip()
    if not message:
        return JsonResponse({'error': 'Message cannot be empty.'}, status=400)

    user_lat = payload.get('latitude')
    user_lon = payload.get('longitude')
    try:
        user_lat = float(user_lat) if user_lat not in (None, "") else None
        user_lon = float(user_lon) if user_lon not in (None, "") else None
    except (TypeError, ValueError):
        user_lat = None
        user_lon = None

    history = request.session.get('chatbot_history', [])
    history.append({'role': 'user', 'text': message})

    try:
        context = build_chatbot_context(user, message, user_lat=user_lat, user_lon=user_lon)
        reply = generate_chatbot_reply(history, context)
    except RuntimeError as exc:
        return JsonResponse({'error': str(exc)}, status=500)

    history.append({'role': 'model', 'text': reply})
    request.session['chatbot_history'] = history[-12:]
    request.session.modified = True

    return JsonResponse({
        'reply': reply,
        'history': request.session['chatbot_history'],
    })


@require_POST
def clear_chatbot_history(request):
    if 'username' not in request.session:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    request.session['chatbot_history'] = []
    request.session.modified = True
    return JsonResponse({'success': True})
    
@csrf_exempt
def post_review(request, business_id):
    """Dedicated review page for a business.

    - GET: Show review form (if logged in) and all reviews below it.
    - POST: Require login, create review, then redirect back to this page.
    """
    business = get_object_or_404(Business, id=business_id)

    if request.method == 'POST':
        # Ensure user authentication via session for posting
        if 'username' not in request.session:
            messages.error(request, "You must be logged in to post a review.")
            return redirect('login')

        try:
            user = CustomUser.objects.get(username=request.session['username'])
        except CustomUser.DoesNotExist:
            messages.error(request, "User not found.")
            return redirect('login')

        content = request.POST.get('content', '').strip()
        parent_id = request.POST.get('parent_id')  # For replies

        if content:
            parent = None
            if parent_id:
                try:
                    parent = Review.objects.get(id=parent_id, business=business)
                except Review.DoesNotExist:
                    parent = None

            rating = request.POST.get('rating')
            rating = int(rating) if rating and rating.isdigit() else None
            Review.objects.create(user=user, business=business, content=content, parent=parent, rating=rating)
            messages.success(request, "Your review has been posted successfully!")
        else:
            messages.error(request, "Review content cannot be empty.")

        # Redirect to avoid form resubmission on refresh
        return redirect('post_review', business_id=business.id)

    # GET or other methods: just display the reviews page
    # Only fetch top-level reviews; replies are accessed via review.replies
    reviews = Review.objects.filter(business=business, parent__isnull=True).order_by('-created_at')

    return render(request, 'user/business_reviews.html', {
        'business': business,
        'reviews': reviews,
    })


def like_review(request, review_id):
    """Toggle like for a review via AJAX and return the updated count."""
    if 'username' not in request.session:
        return JsonResponse({'success': False, 'error': 'Login required'}, status=401)

    try:
        user = CustomUser.objects.get(username=request.session['username'])
    except CustomUser.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'User not found'}, status=404)

    review = get_object_or_404(Review, id=review_id)

    if user in review.likes.all():
        review.likes.remove(user)
        liked = False
    else:
        review.likes.add(user)
        liked = True

    return JsonResponse({'success': True, 'liked': liked, 'likes_count': review.total_likes()})



def main_home(request):
    # Active Users = CustomUser count + OwnerUser count
    user_count = CustomUser.objects.count()
    owner_count = OwnerUser.objects.count()
    active_users = user_count + owner_count

    # Total Business Registered
    total_businesses = Business.objects.count()

    context = {
        'active_users': active_users,
        'total_businesses': total_businesses,
    }
    return render(request, 'main_home.html', context)
