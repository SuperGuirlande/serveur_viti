from django.urls import path
from .views import (
    all_remedes,
    remede_form,
    select_plants_for_remede,
    remede_detail,
    delete_remede,
    search_metabolites
)


urlpatterns = [
    path('', all_remedes, name='all_remedes'),
    path('creer-un-remede/', remede_form, name='create_remede'),
    path('modifier-un-remede/<int:id>/', remede_form, name='edit_remede'),
    path('choisir-les-plantes/<int:remede_id>/', select_plants_for_remede, name='select_plants_for_remede'),
    path('detail/<int:remede_id>/', remede_detail, name='remede_detail'),
    path('delete/<int:remede_id>/', delete_remede, name='delete_remede'),
    path('api/metabolites/search/', search_metabolites, name='search_metabolites'),
]

