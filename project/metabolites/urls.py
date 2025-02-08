from .views import metabolite_detail
from django.urls import path

urlpatterns = [
    path('details/<int:id>/', metabolite_detail, name='metabolite_detail'),
]

