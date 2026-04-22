from django.contrib import admin
from .models import CustomUser

class CustomUserAdmin(admin.ModelAdmin):
    list_display = ('id', 'username', 'email')  # Display these fields in the admin panel
    search_fields = ('username', 'email')  # Add search functionality
    list_filter = ('username',)  # Filter by username

admin.site.register(CustomUser, CustomUserAdmin)
