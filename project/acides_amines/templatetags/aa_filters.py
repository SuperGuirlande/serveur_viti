from django import template

register = template.Library()

@register.filter
def aa_get_item(dictionary, key):
    """Récupère un élément d'un dictionnaire"""
    if dictionary is None:
        return None
    return dictionary.get(key)

@register.filter
def div(value, arg):
    """Divise la valeur par l'argument"""
    try:
        return float(value) / float(arg)
    except (ValueError, ZeroDivisionError):
        return 0

@register.filter
def aa_filter_by_similarity(plant_list, threshold):
    """Filtre les plantes ayant une similarité supérieure au seuil"""
    return [plant for plant in plant_list if not plant.get('is_selected', False) and plant.get('similarity', 0) >= float(threshold)]

@register.filter
def aa_filter_by_similarity_max(plant_list, max_threshold):
    """Filtre les plantes ayant une similarité inférieure au seuil maximum"""
    return [plant for plant in plant_list if not plant.get('is_selected', False) and plant.get('similarity', 0) < float(max_threshold)] 