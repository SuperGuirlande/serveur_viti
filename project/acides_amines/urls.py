from django.urls import path
from . import views

urlpatterns = [
    path('profil-acides-amines/', views.amino_acid_profile, name='amino_acid_profile'),
] 