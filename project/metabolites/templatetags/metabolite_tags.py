from django import template
from django.db.models import Count
from metabolites.models import MetabolitePlant

register = template.Library()

@register.simple_tag
def get_metabolites_count(plant_name):
    """
    Retourne le nombre de métabolites uniques pour une plante donnée
    """
    return MetabolitePlant.objects.filter(
        plant_name=plant_name
    ).values('metabolite__name').distinct().count() 