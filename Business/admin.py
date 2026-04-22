from django.contrib import admin
from .models import User
from .models import Business, BusinessImage

@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('id', 'email', 'created_at')
    search_fields = ('email',)
    list_filter = ('created_at',)
    ordering = ('-created_at',)

class BusinessImageInline(admin.TabularInline):
    model = BusinessImage
    extra = 1  # Number of extra blank image fields to show in admin
    fields = ['image']  # Fields to display in the inline admin

@admin.register(Business)
class BusinessAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'shop', 'mobile_number', 'business_type',
        'city', 'state', 'approval_status'
    )
    list_filter = ('approval_status', 'business_type', 'city', 'state')  # Filters in the admin sidebar
    search_fields = (
        'name', 'shop', 'mobile_number', 'business_type',
        'city', 'district', 'state', 'postal_code', 'country'
    )  # Searchable fields
    fields = (
        'owner',
        'name', 'shop', 'mobile_number', 'business_type',
        'google_map_location', 'business_address',
        'description', 'hours_of_operation',
        'latitude', 'longitude',
        'city', 'district', 'state', 'postal_code', 'country',
        'landmark',
        'approval_status',
    )
    inlines = [BusinessImageInline]  # Include BusinessImage inline
    actions = ['approve_businesses', 'reject_businesses']  # Custom actions for bulk management

    def approve_businesses(self, request, queryset):
        queryset.update(approval_status=True)
        self.message_user(request, f"{queryset.count()} businesses have been approved.")
    approve_businesses.short_description = "Approve selected businesses"

    def reject_businesses(self, request, queryset):
        count = queryset.count()
        queryset.delete()
        self.message_user(request, f"{count} businesses have been rejected.")
    reject_businesses.short_description = "Reject selected businesses"

@admin.register(BusinessImage)
class BusinessImageAdmin(admin.ModelAdmin):
    list_display = ('business', 'image')  # Fields displayed in the list view
    search_fields = ('business__name',)  # Allow searching by business name