from django import template

register = template.Library()

@register.filter
def multiply(value, arg):
    return float(value) * float(arg)

@register.filter
def divide(value, arg):
    try:
        return float(value) / float(arg)
    except (ValueError, ZeroDivisionError):
        return 0

@register.filter
def get_metabolite_concentration(plant, metabolite_id):
    """Récupère la concentration d'un métabolite spécifique pour une plante."""
    metabolite_id = int(metabolite_id)
    
    # Si plant est un dictionnaire et contient metabolite_concentrations
    if isinstance(plant, dict) and 'metabolite_concentrations' in plant:
        return plant['metabolite_concentrations'].get(metabolite_id)
    
    # Si plant est un objet avec un attribut metabolite_concentrations
    elif hasattr(plant, 'metabolite_concentrations'):
        return plant.metabolite_concentrations.get(metabolite_id)
    
    return None

@register.filter
def format_concentration_range(concentration_data):
    """
    Formate les données de concentration pour afficher low → high avec des ? pour les valeurs manquantes.
    
    Args:
        concentration_data: Un dictionnaire contenant 'low' et 'high'
    
    Returns:
        Une chaîne formatée avec la plage complète et ? pour les valeurs manquantes
    """
    if not concentration_data or not isinstance(concentration_data, dict):
        return "-"
    
    low = concentration_data.get('low')
    high = concentration_data.get('high')
    
    if low is None and high is None:
        return "? → ?"
    
    if low is not None and high is not None:
        # Arrondir en entiers
        low_int = int(round(float(low)))
        high_int = int(round(float(high)))
        return f"{low_int} → {high_int}"
    elif low is not None:
        # Seulement low disponible
        low_int = int(round(float(low)))
        return f"{low_int} → ?"
    else:
        # Seulement high disponible
        high_int = int(round(float(high)))
        return f"? → {high_int}"

@register.filter
def unique(items):
    """
    Filtre qui élimine les doublons dans une liste.
    
    Args:
        items: Une liste ou un itérable contenant potentiellement des doublons
    
    Returns:
        Une liste sans doublons, préservant l'ordre original autant que possible
    """
    seen = set()
    result = []
    
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
            
    return result

@register.filter
def safe_urlencode(value):
    """
    Encode une chaîne ou un dictionnaire pour une URL de manière sécurisée.
    Conserve l'esperluette (&) pour les paramètres d'URL.
    
    Args:
        value: Une chaîne ou un dictionnaire à encoder pour une URL
    
    Returns:
        Une chaîne encodée pour une URL
    """
    if value:
        if not value.startswith('?'):
            return '?' + value
        return value
    return '' 