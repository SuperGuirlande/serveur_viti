from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('compte/', include('accounts.urls')),
    path('', include('main.urls')),
    path('metabolites/', include('metabolites.urls')),
]
