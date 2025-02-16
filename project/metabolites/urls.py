from .views import metabolite_detail, metabolites_en_communs, all_plants, all_metabolites, plant_detail
from django.urls import path

urlpatterns = [
    path('tous/', all_metabolites, name='all_metabolites'),
    path('rechercher/', all_metabolites, name='metabolite_search'),
    path('details/<int:id>/', metabolite_detail, name='metabolite_detail'),

    path('plantes/toutes/', all_plants, name='all_plants'),
    path('plantes/rechercher/', all_plants, name='plant_search'),
    path('plant/<int:plant_id>/', plant_detail, name='plant_detail'),

    path('metabolites-en-communs/plante/<int:id>/', metabolites_en_communs, name='metabolites_en_communs'),
]

