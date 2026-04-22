from django.db import models

class User(models.Model):
    email = models.EmailField(unique=True, verbose_name="Email Address")
    profile_image = models.URLField(max_length=500, blank=True, null=True, verbose_name="Profile Image")
    phone_number = models.CharField(max_length=15, blank=True, null=True, verbose_name="Phone Number")
    phone_verified = models.BooleanField(default=False, verbose_name="Phone Verified")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")

    def __str__(self):
        return self.email

from user.models import CustomUser  # Import from user app

class Business(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='businesses')  # Do not change
    name = models.CharField(max_length=255)
    shop = models.CharField(max_length=255)
    mobile_number = models.CharField(max_length=15)
    business_type = models.CharField(max_length=255)
    google_map_location = models.TextField(blank=True, null=True) # Made optional for backward compatibility
    business_address = models.TextField()
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    city = models.CharField(max_length=100, null=True, blank=True)
    district = models.CharField(max_length=100, null=True, blank=True)
    state = models.CharField(max_length=100, null=True, blank=True)
    postal_code = models.CharField(max_length=20, null=True, blank=True)
    country = models.CharField(max_length=100, null=True, blank=True)
    landmark = models.CharField(max_length=255, null=True, blank=True) # New field
    proof_of_business = models.FileField(upload_to='proof/', null=True, blank=True) # Proof of business ownership
    description = models.TextField(blank=True, null=True)  # New field
    hours_of_operation = models.CharField(max_length=255, blank=True, null=True)  # Legacy field, kept for compatibility
    approval_status = models.BooleanField(default=False)
    likes = models.ManyToManyField(CustomUser, related_name='liked_businesses', blank=True)  # Users who liked

    def total_likes(self):
        return self.likes.count()

    @property
    def average_rating(self):
        from django.db.models import Avg
        avg_rtg = self.reviews.filter(rating__isnull=False).aggregate(Avg('rating'))['rating__avg']
        return round(float(avg_rtg), 1) if avg_rtg else 0.0

    def __str__(self):
        return self.name

class SocialMediaLink(models.Model):
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name='social_media_links')
    platform = models.CharField(max_length=50) # e.g., Facebook, Instagram, Twitter
    url = models.URLField()

    def __str__(self):
        return f"{self.platform} link for {self.business.name}"

class OperatingHour(models.Model):
    DAYS = [
        (0, 'Monday'),
        (1, 'Tuesday'),
        (2, 'Wednesday'),
        (3, 'Thursday'),
        (4, 'Friday'),
        (5, 'Saturday'),
        (6, 'Sunday'),
    ]
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name='operating_hours')
    day_of_week = models.IntegerField(choices=DAYS)
    open_time = models.TimeField(null=True, blank=True)
    close_time = models.TimeField(null=True, blank=True)
    is_closed = models.BooleanField(default=False)

    class Meta:
        unique_together = ('business', 'day_of_week')
        ordering = ['day_of_week']

    def __str__(self):
        return f"{self.get_day_of_week_display()} hours for {self.business.name}"

class BusinessImage(models.Model):
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='business_images/')
    likes_count = models.IntegerField(default=0)

    def __str__(self):
        return f"Image for {self.business.name}"

class Visitor(models.Model):
    business = models.ForeignKey('Business', on_delete=models.CASCADE, related_name='visitors')
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)  # Track user who visited
    visit_time = models.DateTimeField(auto_now_add=True)  # Record when they visited

    class Meta:
        unique_together = ('business', 'user')  # Prevent duplicate visits

    def __str__(self):
        return f"{self.user.username} visited {self.business.name}"
    
class Review(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)  # Reviewer
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="reviews")
    content = models.TextField()
    rating = models.IntegerField(choices=[(i, i) for i in range(1, 6)], null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # New: support replies (threaded under a parent review)
    parent = models.ForeignKey(
        'self', on_delete=models.CASCADE, null=True, blank=True, related_name='replies'
    )

    # New: support likes from users
    likes = models.ManyToManyField(CustomUser, related_name='liked_reviews', blank=True)

    def total_likes(self):
        return self.likes.count()

    def __str__(self):
        return f"Review by {self.user.username} on {self.business.name}"

import os
from django.db.models.signals import post_delete
from django.dispatch import receiver

@receiver(post_delete, sender=BusinessImage)
def delete_business_image_file(sender, instance, **kwargs):
    """
    Deletes the image file from the filesystem when the BusinessImage object is deleted.
    """
    if instance.image:
        if os.path.isfile(instance.image.path):
            os.remove(instance.image.path)

@receiver(post_delete, sender=Business)
def delete_business_proof_file(sender, instance, **kwargs):
    """
    Deletes the proof_of_business file from the filesystem when the Business object is deleted.
    """
    if instance.proof_of_business:
        if os.path.isfile(instance.proof_of_business.path):
            os.remove(instance.proof_of_business.path)

class Message(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='messages')
    content = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)
    is_from_owner = models.BooleanField(default=True)  # True: Owner -> Admin, False: Admin -> Owner
    is_seen = models.BooleanField(default=False)

    def __str__(self):
        return f"Msg: {self.owner.email} - {'Owner' if self.is_from_owner else 'Admin'}"
