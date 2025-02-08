from django import forms
from django.contrib.auth import get_user_model
from project import settings
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from .models import CustomUser
from django.utils.translation import gettext_lazy as _


class UserRegisterForm(UserCreationForm):
    email = forms.EmailField()

    class Meta:
        model = CustomUser
        fields = ['email', 'username', 'password1', 'password2']


class UserLoginForm(AuthenticationForm):
    username = forms.CharField(label=_("Adresse e-mail"), widget=forms.TextInput)
    password = forms.CharField(label=_('Password'), widget=forms.PasswordInput)


class ChangePasswordForm(forms.Form):
    old_password = forms.CharField(widget=forms.PasswordInput())
    new_password = forms.CharField(widget=forms.PasswordInput())
    confirm_password = forms.CharField(widget=forms.PasswordInput())

