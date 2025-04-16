from django.urls import path
from . import views

app_name = 'tabs_numbering'

urlpatterns = [
    path('api/numbering/create-temp/<int:plant_id>/', views.create_temp_numbering, name='create_temp_numbering'),
    path('api/numbering/save/', views.save_numbering, name='save_numbering'),
    path('api/numbering/load/<int:numbering_id>/', views.load_numbering, name='load_numbering'),
    path('api/numbering/delete/<int:numbering_id>/', views.delete_numbering, name='delete_numbering'),
    path('api/numbering/list/', views.list_numberings, name='list_numberings'),
] 