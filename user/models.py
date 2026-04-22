from django.db import models

class CustomUser(models.Model):
    username = models.CharField(max_length=100, unique=True)
    email = models.EmailField(unique=True)
    phone_number = models.CharField(max_length=15, blank=True, null=True)  # Optional phone number
    phone_verified = models.BooleanField(default=False)
    profile = models.ImageField(upload_to='profile_pics/', blank=True, null=True)  # Profile photo
    google_profile_image = models.URLField(max_length=500, blank=True, null=True) # Google Profile Image URL
    saved_businesses = models.ManyToManyField('Business.Business', blank=True, related_name='saved_by')

    def _str_(self):
        return self.username
