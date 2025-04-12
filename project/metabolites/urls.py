from .views import metabolite_detail, all_plants, all_metabolites, plant_detail, all_activities, activity_detail, plant_metabolites, plant_common_metabolites, plant_common_metabolites_pdf
from django.urls import path

urlpatterns = [
    path('tous/', all_metabolites, name='all_metabolites'),
    path('rechercher/', all_metabolites, name='metabolite_search'),
    path('details/<int:id>/', metabolite_detail, name='metabolite_detail'),

    path('plantes/toutes/', all_plants, name='all_plants'),
    path('plantes/rechercher/', all_plants, name='plant_search'),
    path('plant/<int:plant_id>/', plant_detail, name='plant_detail'),
    path('plant/<int:plant_id>/metabolites/', plant_metabolites, name='plant_metabolites'),
    path('plant/<int:plant_id>/common-metabolites/', plant_common_metabolites, name='plant_common_metabolites'),
    path('plant/<int:plant_id>/common-metabolites/pdf/', plant_common_metabolites_pdf, name='plant_common_metabolites_pdf'),

    path('activites/toutes/', all_activities, name='all_activities'),
    path('activites/rechercher/', all_activities, name='activity_search'),
    path('activite/<int:activity_id>/', activity_detail, name='activity_detail'),
]

