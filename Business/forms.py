from django import forms
from Business.models import User, Business, BusinessImage
import re


class LoginForm(forms.Form):
    email = forms.CharField(label="Email or Phone")

class BusinessImageForm(forms.ModelForm):
    class Meta:
        model = BusinessImage
        fields = ['image']

    def __init__(self, *args, **kwargs):
        super(BusinessImageForm, self).__init__(*args, **kwargs)
        self.fields['image'].required = False  # If images are handled separately in view

class BusinessForm(forms.ModelForm):
    class Meta:
        model = Business
        fields = [
            'name', 'shop', 'mobile_number', 'business_type', 
            'google_map_location', 'business_address', 'description', 'hours_of_operation',
            'latitude', 'longitude', 'city', 'district', 'state', 'postal_code', 'country', 'landmark', 'proof_of_business'
        ]
        widgets = {
            'google_map_location': forms.Textarea(attrs={'rows': 3, 'style': 'display:none;'}), # Hide the old field or keep it hidden
            'business_address': forms.Textarea(attrs={'rows': 3, 'id': 'id_business_address'}),
            'description': forms.Textarea(attrs={'rows': 3}),
            'hours_of_operation': forms.TextInput(attrs={'placeholder': 'e.g., Mon-Fri: 9 AM - 6 PM'}),
            'latitude': forms.HiddenInput(),
            'longitude': forms.HiddenInput(),
            'city': forms.TextInput(attrs={'id': 'id_city'}),
            'district': forms.TextInput(attrs={'id': 'id_district'}),
            'state': forms.TextInput(attrs={'id': 'id_state'}),
            'postal_code': forms.TextInput(attrs={'id': 'id_postal_code'}),
            'country': forms.TextInput(attrs={'id': 'id_country'}),
        }
    
    def __init__(self, *args, **kwargs):
        super(BusinessForm, self).__init__(*args, **kwargs)
        self.fields['name'].required = False  # Allow empty name (handled in view)

    def clean_name(self):
        name = self.cleaned_data.get('name')
        if name and any(char.isdigit() for char in name):
            raise forms.ValidationError("Name should not contain any numbers")
        return name
    
    def clean_mobile_number(self):
        mobile_number = self.cleaned_data.get('mobile_number')
        if mobile_number and len(mobile_number) > 10:
            raise forms.ValidationError("Mobile number should not exceed 10 digits")
        return mobile_number
