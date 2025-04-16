from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.urls import reverse
import json
import logging
from .models import PlantNumbering
from metabolites.models import Plant

logger = logging.getLogger('tabs_numbering')

@login_required
def create_temp_numbering(request, plant_id):
    """Crée une numérotation temporaire pour les plantes en commun avec la plante spécifiée"""
    # Gérer la suppression de la numérotation temporaire
    if request.method == 'DELETE':
        request.session.pop(f'plant_{plant_id}_numbering', None)
        request.session.pop(f'plant_{plant_id}_numbering_id', None)
        request.session.pop(f'plant_{plant_id}_numbering_name', None)
        request.session.pop(f'plant_{plant_id}_numbering_params', None)
        return JsonResponse({'success': True, 'message': 'Numérotation supprimée'})
    
    if request.method != 'POST':
        return JsonResponse({'error': 'Méthode non autorisée'}, status=405)
    
    # Récupérer les paramètres de la requête
    data = json.loads(request.body)
    
    # Récupérer la numérotation directement depuis le client
    numbering = data.get('numbering', {})
    if not numbering:
        return JsonResponse({'error': 'Aucune numérotation fournie'}, status=400)
    
    # Récupérer les paramètres de filtrage pour les stocker
    activity_filter = data.get('activity')
    exclude_ubiquitous = data.get('exclude_ubiquitous', False)
    search_text = data.get('search_text', '')
    search_type = data.get('search_type', 'contains')
    
    # Récupérer les paramètres de tri pour les stocker
    sort_params = []
    for i in range(5):  # Jusqu'à 5 niveaux de tri
        sort_field = data.get(f'common_sort{i}')
        sort_direction = data.get(f'common_direction{i}')
        if sort_field and sort_direction:
            sort_params.append((sort_field, sort_direction))
    
    # Récupérer les filtres de métabolites
    metabolite_filters = []
    for i in range(1, 4):
        filter_key = f'metabolite_filter_{i}'
        if filter_key in data and data[filter_key]:
            try:
                metabolite_filters.append(int(data[filter_key]))
            except (ValueError, TypeError):
                pass
    
    # Sauvegarder la numérotation en session
    request.session[f'plant_{plant_id}_numbering'] = numbering
    request.session[f'plant_{plant_id}_numbering_id'] = None
    request.session[f'plant_{plant_id}_numbering_name'] = 'Temporaire'
    
    # Sauvegarder les paramètres de filtrage et de tri en session
    request.session[f'plant_{plant_id}_numbering_params'] = {
        'activity': activity_filter,
        'exclude_ubiquitous': exclude_ubiquitous,
        'search_text': search_text,
        'search_type': search_type,
        'metabolite_filters': metabolite_filters,
        'sort_params': sort_params
    }
    
    return JsonResponse({
        'success': True, 
        'message': 'Numérotation temporaire créée',
        'count': len(numbering)
    })

@login_required
def save_numbering(request):
    """Sauvegarde une numérotation temporaire en base de données"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Méthode non autorisée'}, status=405)
    
    data = json.loads(request.body)
    plant_id = data.get('plant_id')
    name = data.get('name')
    
    if not plant_id or not name:
        return JsonResponse({'error': 'Paramètres manquants'}, status=400)
    
    # Vérifier si une numérotation temporaire existe
    numbering = request.session.get(f'plant_{plant_id}_numbering')
    params = request.session.get(f'plant_{plant_id}_numbering_params')
    
    if not numbering or not params:
        return JsonResponse({'error': 'Aucune numérotation temporaire trouvée'}, status=404)
    
    # Créer une nouvelle entrée dans la base de données
    numbering_obj = PlantNumbering.objects.create(
        user=request.user,
        name=name,
        plant_id=plant_id,
        query_params=json.dumps(params),
        numbering_data=numbering
    )
    
    # Mettre à jour la session avec l'ID de la numérotation sauvegardée
    request.session[f'plant_{plant_id}_numbering_id'] = numbering_obj.id
    request.session[f'plant_{plant_id}_numbering_name'] = name
    
    return JsonResponse({
        'success': True,
        'message': 'Numérotation sauvegardée',
        'id': numbering_obj.id,
        'name': name
    })

@login_required
def load_numbering(request, numbering_id):
    """Charge une numérotation sauvegardée"""
    try:
        numbering_obj = PlantNumbering.objects.get(id=numbering_id, user=request.user)
    except PlantNumbering.DoesNotExist:
        return JsonResponse({'error': 'Numérotation non trouvée'}, status=404)
    
    plant_id = numbering_obj.plant_id
    
    # Charger la numérotation et les paramètres en session
    request.session[f'plant_{plant_id}_numbering'] = numbering_obj.numbering_data
    request.session[f'plant_{plant_id}_numbering_id'] = numbering_id
    request.session[f'plant_{plant_id}_numbering_name'] = numbering_obj.name
    request.session[f'plant_{plant_id}_numbering_params'] = json.loads(numbering_obj.query_params)
    
    # Créer l'URL avec les paramètres d'origine
    params = json.loads(numbering_obj.query_params)
    query_params = {}
    
    if params.get('activity'):
        query_params['activity'] = params['activity']
    if params.get('exclude_ubiquitous'):
        query_params['exclude_ubiquitous'] = 'true'
    if params.get('search_text'):
        query_params['search_text'] = params['search_text']
        query_params['search_type'] = params.get('search_type', 'contains')
    
    for i, metabolite_id in enumerate(params.get('metabolite_filters', []), start=1):
        if i <= 3:
            query_params[f'metabolite_filter_{i}'] = str(metabolite_id)
    
    # Ajouter les paramètres de tri sauvegardés
    if params.get('sort_params'):
        for i, (field, direction) in enumerate(params['sort_params']):
            query_params[f'common_sort{i}'] = field
            query_params[f'common_direction{i}'] = direction
    
    url = reverse('plant_common_metabolites', args=[plant_id])
    query_string = '&'.join([f"{k}={v}" for k, v in query_params.items()])
    
    return JsonResponse({
        'success': True,
        'message': f'Numérotation "{numbering_obj.name}" chargée',
        'redirect_url': f"{url}?{query_string}"
    })

@login_required
def delete_numbering(request, numbering_id):
    """Supprime une numérotation sauvegardée"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Méthode non autorisée'}, status=405)
    
    try:
        numbering_obj = PlantNumbering.objects.get(id=numbering_id, user=request.user)
    except PlantNumbering.DoesNotExist:
        return JsonResponse({'error': 'Numérotation non trouvée'}, status=404)
    
    plant_id = numbering_obj.plant_id
    numbering_name = numbering_obj.name
    
    # Supprimer l'objet
    numbering_obj.delete()
    
    # Si la numérotation active était celle-ci, la retirer de la session
    if request.session.get(f'plant_{plant_id}_numbering_id') == numbering_id:
        request.session.pop(f'plant_{plant_id}_numbering', None)
        request.session.pop(f'plant_{plant_id}_numbering_id', None)
        request.session.pop(f'plant_{plant_id}_numbering_name', None)
        request.session.pop(f'plant_{plant_id}_numbering_params', None)
    
    return JsonResponse({
        'success': True,
        'message': f'Numérotation "{numbering_name}" supprimée'
    })

@login_required
def list_numberings(request):
    """Liste les numérotations sauvegardées pour l'utilisateur"""
    plant_id = request.GET.get('plant_id')
    
    if not plant_id:
        return JsonResponse({'error': 'ID de plante manquant'}, status=400)
    
    numberings = PlantNumbering.objects.filter(
        user=request.user,
        plant_id=plant_id
    ).values('id', 'name', 'created_at')
    
    return JsonResponse({
        'success': True,
        'numberings': list(numberings)
    })
