from django import forms
from user.models import CustomUser
from django.core.exceptions import ValidationError


class LoginForm(forms.Form):
    email = forms.CharField(label="Email or Phone")
