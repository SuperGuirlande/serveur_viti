from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static


urlpatterns = [
    path('admin/', admin.site.urls),
    path('compte/', include('accounts.urls')),
    path('', include('main.urls')),
    path('metabolites/', include('metabolites.urls')),
    path('remedes/', include('remedes.urls')),
    path('acides-amines/', include('acides_amines.urls')),
    path("ckeditor5/", include('django_ckeditor_5.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

