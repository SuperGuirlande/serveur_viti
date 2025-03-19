from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('remedes/', include('remedes.urls')),
    path('api/metabolites/search/', include('remedes.urls')),
] 