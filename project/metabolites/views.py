from django.shortcuts import render, get_object_or_404, redirect
from django.db.models import Count, Subquery, OuterRef, Prefetch
from metabolites.models import Metabolite, MetaboliteActivity, MetabolitePlant, Plant, Activity
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.contrib.auth.decorators import login_required
from django.db import models, connection
from .utils import log_execution_time
import logging
import time
from django.core.cache import cache
from django.conf import settings
from django.http import JsonResponse
from django.urls import reverse
import json
import numpy as np
from scipy import spatial
from acides_amines.utils import calculate_amino_acid_similarity
import datetime
import re

logger = logging.getLogger('metabolites')

@login_required
def metabolite_detail(request, id):
    metabolite = get_object_or_404(Metabolite, id=id)
    activities = metabolite.activities.all()

    # Récupération des paramètres de tri pour les plantes
    sort_field = request.GET.get('sort')
    sort_direction = request.GET.get('direction')
    
    # Récupération des paramètres de tri pour les activités
    activities_sort_field = request.GET.get('activities_sort')
    activities_sort_direction = request.GET.get('activities_direction')
    
    # Récupération des paramètres de recherche pour les plantes
    search_text = request.GET.get('search_text', '')
    search_type = request.GET.get('search_type', 'contains')
    
    # Récupération des paramètres de recherche pour les activités
    activity_search_text = request.GET.get('activity_search_text', '')
    activity_search_type = request.GET.get('activity_search_type', 'contains')
    
    # Filtrer les activités par nom si un critère de recherche est fourni
    if activity_search_text:
        if activity_search_type == 'contains':
            activities = activities.filter(activity__name__icontains=activity_search_text)
        elif activity_search_type == 'starts_with':
            activities = activities.filter(activity__name__istartswith=activity_search_text)
    
    # Trier les activités si demandé
    if activities_sort_field and activities_sort_direction:
        if activities_sort_field == 'activity_name':
            order_by = f"{'' if activities_sort_direction == 'asc' else '-'}activity__name"
            activities = activities.order_by(order_by)

    count_per_page = 20
    paginator = Paginator(activities, count_per_page)
    activities_page_number = request.GET.get('activities_page', 1)
    activities = paginator.get_page(activities_page_number)
    activities_page_count = paginator.num_pages
    activities_start_number = (int(activities_page_number) - 1) * count_per_page

    # Récupérer les plantes avec filtrage par nom directement dans la requête SQL
    plants = metabolite.get_plants_with_parts(
        sort_field=sort_field, 
        sort_direction=sort_direction,
        search_text=search_text,
        search_type=search_type
    )
    
    paginator = Paginator(plants, count_per_page)
    plants_page_number = request.GET.get('plants_page', 1)
    plants = paginator.get_page(plants_page_number)
    plants_page_count = paginator.num_pages
    plants_start_number = (int(plants_page_number) - 1) * count_per_page

    context = {
        'metabolite': metabolite,
        'activities': activities,
        'count_per_page': count_per_page,
        'activities_page_number': activities_page_number,
        'activities_page_count': activities_page_count,
        'plants': plants,
        'plants_page_number': plants_page_number,
        'plants_page_count': plants_page_count,
        'plants_start_number': plants_start_number,
        'activities_start_number': activities_start_number,
        'search_text': search_text,
        'search_type': search_type,
        'activity_search_text': activity_search_text,
        'activity_search_type': activity_search_type,
    }

    return render(request, 'metabolites/metabolite_detail.html', context)


@login_required
def all_plants(request):
    # Récupération des paramètres
    search = request.GET.get('search', '')
    sort = request.GET.get('sort', 'name_asc')

    # Requête de base avec annotation pour le comptage (gardons la logique d'origine)
    plants_list = Plant.objects.annotate(
        metabolites_count=Subquery(
            MetabolitePlant.objects.filter(
                plant_name=models.OuterRef('name')
            ).values('plant_name')
            .annotate(count=Count('metabolite_id', distinct=True))
            .values('count')
        )
    ).select_related()  # Ajout de select_related pour optimiser

    # Appliquer la recherche si nécessaire
    if search:
        plants_list = plants_list.filter(name__icontains=search)

    # Appliquer le tri
    if sort == 'name_asc':
        plants_list = plants_list.order_by('name')
    elif sort == 'name_desc':
        plants_list = plants_list.order_by('-name')
    elif sort == 'metabolites_asc':
        plants_list = plants_list.order_by('metabolites_count')
    elif sort == 'metabolites_desc':
        plants_list = plants_list.order_by('-metabolites_count')

    # Pagination
    count_by_page = 50  
    paginator = Paginator(plants_list, count_by_page)
    page_number = request.GET.get('page', 1)
    plants_list = paginator.get_page(page_number)
    start_number = (int(page_number) - 1) * count_by_page

    # Ajouter les paramètres actuels pour la pagination
    query_params = request.GET.copy()
    if 'page' in query_params:
        del query_params['page']
    
    context = {
        'plants': plants_list,
        'current_sort': sort,
        'current_search': search,
        'query_params': query_params.urlencode(),
        'start_number': start_number,
        'count_by_page': count_by_page,
    }

    return render(request, 'metabolites/all_plants.html', context)


@log_execution_time
@login_required
def all_metabolites(request):
    logger.info("Début de la vue all_metabolites")
    
    search = request.GET.get('search')
    sort = request.GET.get('sort', 'name_asc')
    page_number = int(request.GET.get('page', 1))
    count_by_page = 20

    logger.debug(f"Paramètres reçus - search: {search}, sort: {sort}")
    
    # Utilisation de Django ORM pour annoter les champs nécessaires
    metabolites = Metabolite.objects.annotate(
        activities_count=Count('activities', distinct=True),
        plants_count=Count('plants', distinct=True)
    )
    
    if search:
        metabolites = metabolites.filter(name__icontains=search)
    
    # Mapping de tri
    sort_mapping = {
        'name_asc': 'name',
        'name_desc': '-name',
        'activities_asc': 'activities_count',
        'activities_desc': '-activities_count',
        'plants_asc': 'plants_count',
        'plants_desc': '-plants_count'
    }
    order_by = sort_mapping.get(sort, 'name')
    
    # Appliquer le tri
    metabolites = metabolites.order_by(order_by)
    
    # Pagination
    paginator = Paginator(metabolites, count_by_page)
    metabolites_page = paginator.get_page(page_number)
    
    context = {
        'metabolites': metabolites_page,
        'page': {
            'has_next': metabolites_page.has_next(),
            'has_previous': metabolites_page.has_previous(),
            'next_page_number': metabolites_page.next_page_number() if metabolites_page.has_next() else None,
            'previous_page_number': metabolites_page.previous_page_number() if metabolites_page.has_previous() else None,
            'number': page_number,
            'num_pages': paginator.num_pages
        },
        'count_by_page': count_by_page,
        'start_number': (page_number - 1) * count_by_page,
        'current_sort': sort,
        'current_search': search,
        'total_count': paginator.count
    }
    
    logger.info("Fin de la vue all_metabolites")
    return render(request, 'metabolites/all_metabolites.html', context)


@log_execution_time
@login_required
def plant_detail(request, plant_id):
    logger.info(f"Accès aux détails de la plante {plant_id}")
    
    plant = get_object_or_404(Plant, id=plant_id)
    
    context = {
        'plant': plant,
        'count_metabolites': plant.all_metabolites_count,
    }
    
    return render(request, 'metabolites/plant_detail.html', context)


@log_execution_time
@login_required
def plant_metabolites(request, plant_id):
    logger.info(f"Accès aux métabolites de la plante {plant_id}")
    
    plant = get_object_or_404(Plant, id=plant_id)
    
    # Récupérer les paramètres de tri et de pagination
    metabolites_page = request.GET.get('metabolites_page', 1)
    search_text = request.GET.get('search_text', '')
    search_type = request.GET.get('search_type', 'contains')
    exclude_ubiquitous = request.GET.get('exclude_ubiquitous') == 'true'
    
    # Récupérer les paramètres de tri
    sort_params = []
    for i in range(3):  # Jusqu'à 3 niveaux de tri possibles
        field = request.GET.get(f'sort{i}')
        direction = request.GET.get(f'direction{i}')
        if field and direction:
            sort_params.append((field, direction))
    
    # Récupérer les métabolites de la plante
    metabolites = plant.get_metabolites_with_parts()
    
    # Appliquer le filtre de recherche par nom si nécessaire
    if search_text:
        if search_type == 'contains':
            metabolites = [m for m in metabolites if search_text.lower() in m['metabolite__name'].lower()]
        elif search_type == 'starts_with':
            metabolites = [m for m in metabolites if m['metabolite__name'].lower().startswith(search_text.lower())]
    
    # Exclure les métabolites ubiquitaires si demandé
    if exclude_ubiquitous:
        metabolites = [m for m in metabolites if not m['metabolite__is_ubiquitous']]
    
    # Appliquer les tris
    for field, direction in sort_params:
        reverse = direction == 'desc'
        if field in ['metabolite__name', 'plant_part', 'reference']:
            # Tri alphabétique
            metabolites = sorted(metabolites, key=lambda m: str(m.get(field, '')).lower(), reverse=reverse)
        elif field in ['low', 'high', 'deviation']:
            # Tri numérique avec gestion des valeurs None
            metabolites = sorted(metabolites, key=lambda m: (m.get(field) is None, m.get(field, 0)), reverse=reverse)
        elif field == 'metabolite__is_ubiquitous':
            # Tri booléen
            metabolites = sorted(metabolites, key=lambda m: bool(m.get(field, False)), reverse=reverse)
    
    # Paginer les résultats
    paginator = Paginator(metabolites, 20)
    try:
        metabolites = paginator.page(metabolites_page)
    except (PageNotAnInteger, EmptyPage):
        metabolites = paginator.page(1)
    
    # Construire les paramètres de requête pour la pagination
    query_params = request.GET.copy()
    if 'metabolites_page' in query_params:
        del query_params['metabolites_page']
    
    context = {
        'plant': plant,
        'metabolites': metabolites,
        'metabolites_start': (metabolites.number - 1) * 20,
        'count_metabolites': plant.all_metabolites_count,
        'query_params': query_params.urlencode(),
        'debug_mode': False,
        'search_text': search_text,
        'search_type': search_type,
        'exclude_ubiquitous': exclude_ubiquitous,
    }
    
    return render(request, 'metabolites/plant_metabolites.html', context)


@log_execution_time
@login_required
def plant_common_metabolites(request, plant_id):
    logger.info(f"Accès aux métabolites en commun de la plante {plant_id}")
    
    plant = get_object_or_404(Plant, id=plant_id)
    
    # Récupérer les paramètres de tri et de pagination
    common_page = request.GET.get('common_page', 1)
    activity_filter = request.GET.get('activity')
    exclude_ubiquitous = request.GET.get('exclude_ubiquitous') == 'true'
    search_text = request.GET.get('search_text', '')
    search_type = request.GET.get('search_type', 'contains')
    metabolite_filter_1 = request.GET.get('metabolite_filter_1')
    metabolite_filter_2 = request.GET.get('metabolite_filter_2')
    metabolite_filter_3 = request.GET.get('metabolite_filter_3')
    
    # Construire les paramètres de tri pour les métabolites en commun
    common_sort_params = []
    metabolite_concentration_sort = None
    amino_acid_similarity_sort = None
    
    for i in range(5):
        field = request.GET.get(f'common_sort{i}')
        direction = request.GET.get(f'common_direction{i}')
        if field and direction:
            # Vérifier si c'est un tri par concentration de métabolite
            if field.startswith('metabolite_concentration_'):
                metabolite_id = field.replace('metabolite_concentration_', '')
                metabolite_concentration_sort = (metabolite_id, direction)
            # Vérifier si c'est un tri par similarité d'acides aminés
            elif field == 'amino_acid_similarity':
                amino_acid_similarity_sort = direction
            else:
                common_sort_params.append((field, direction))
    
    # Récupérer les métabolites filtrés
    metabolite_ids = []
    filtered_metabolites = []
    if metabolite_filter_1:
        metabolite_ids.append(int(metabolite_filter_1))
    if metabolite_filter_2:
        metabolite_ids.append(int(metabolite_filter_2))
    if metabolite_filter_3:
        metabolite_ids.append(int(metabolite_filter_3))
    
    if metabolite_ids:
        for metabolite_id in metabolite_ids:
            try:
                metabolite = Metabolite.objects.get(id=metabolite_id)
                filtered_metabolites.append({
                    'id': metabolite.id,
                    'name': metabolite.name
                })
            except Metabolite.DoesNotExist:
                logger.warning(f"Métabolite {metabolite_id} non trouvé")
    
    # Récupérer les métabolites filtrés pour trouver les plantes qui les contiennent
    metabolite_plants = {}
    if metabolite_ids:
        # Récupérer toutes les relations MetabolitePlant pour les métabolites sélectionnés
        all_metabolite_plants = MetabolitePlant.objects.filter(
            metabolite_id__in=metabolite_ids
        ).select_related('metabolite')
        
        # Organiser par plante
        for mp in all_metabolite_plants:
            if mp.plant_name not in metabolite_plants:
                metabolite_plants[mp.plant_name] = {}
            
            if mp.metabolite_id not in metabolite_plants[mp.plant_name]:
                metabolite_plants[mp.plant_name][mp.metabolite_id] = []
                
            metabolite_plants[mp.plant_name][mp.metabolite_id].append(mp)
    
    # Récupérer les plantes ayant des métabolites en commun (sans pagination)
    full_common_plants = plant.get_common_plants(
        activity_filter=activity_filter,
        page=1,
        per_page=10000,  # Valeur élevée pour récupérer toutes les plantes
        sort_params=None,  # Pas de tri ici, on le fera manuellement
        exclude_ubiquitous=exclude_ubiquitous,
        search_text=search_text,
        search_type=search_type,
        metabolite_filters=metabolite_ids
    )
    
    # Si nous avons des métabolites filtrés, récupérer leurs concentrations pour chaque plante
    if metabolite_ids and filtered_metabolites:
        # Pour chaque plante dans les résultats
        for plant_data in full_common_plants['results']:
            plant_name = plant_data['name'] if isinstance(plant_data, dict) else plant_data.name
            
            # Ajouter un dictionnaire pour stocker les concentrations
            if isinstance(plant_data, dict):
                plant_data['metabolite_concentrations'] = {}
            else:
                plant_data.metabolite_concentrations = {}
            
            # Pour chaque métabolite filtré
            for metabolite_id in metabolite_ids:
                # Valeurs par défaut
                concentration_data = {
                    'average': 0,
                    'details': [],
                    'count': 0
                }
                
                # Si la plante a ce métabolite
                if plant_name in metabolite_plants and int(metabolite_id) in metabolite_plants[plant_name]:
                    mp_instances = metabolite_plants[plant_name][int(metabolite_id)]
                    
                    # Calculer la moyenne sur toutes les instances
                    total_value = 0
                    count = 0
                    details = []
                    
                    for mp in mp_instances:
                        low_value = float(mp.low) if mp.low is not None else 0
                        high_value = float(mp.high) if mp.high is not None else (low_value if low_value > 0 else 0)
                        
                        # Ignorer les instances sans valeur
                        if low_value == 0 and high_value == 0:
                            continue
                            
                        instance_avg = (low_value + high_value) / 2 if high_value > 0 else low_value
                        total_value += instance_avg
                        count += 1
                        
                        details.append({
                            'plant_part': mp.plant_part or 'Non spécifié',
                            'low': low_value,
                            'high': high_value,
                            'reference': mp.reference
                        })
                    
                    if count > 0:
                        concentration_data = {
                            'average': total_value / count,
                            'details': details,
                            'count': count
                        }
                
                # Si plant_data est un dictionnaire, nous devons ajouter l'attribut metabolite_concentrations
                if isinstance(plant_data, dict):
                    plant_data['metabolite_concentrations'][int(metabolite_id)] = concentration_data
                else:
                    plant_data.metabolite_concentrations[int(metabolite_id)] = concentration_data
    
    # Récupérer les informations des acides aminés
    amino_acids = ['Alanine', 'Arginine', 'Asparagine', 'Aspartic acid', 'Cysteine', 
                  'Glutamic acid', 'Glutamine', 'Glycine', 'Histidine', 'Isoleucine', 
                  'Leucine', 'Lysine', 'Methionine', 'Phenylalanine', 'Proline', 
                  'Serine', 'Threonine', 'Tryptophan', 'Tyrosine', 'Valine']
    
    # Créer une version uppercase pour la recherche dans la base de données (comme dans acides_amines/views.py)
    amino_acids_upper = [aa.upper() for aa in amino_acids]
    
    # Créer un mapping entre le nom d'affichage et le nom uppercase
    amino_acid_mapping = {aa_upper: aa_display for aa_upper, aa_display in zip(amino_acids_upper, amino_acids)}
    
    # Récupérer les métabolites correspondant aux acides aminés (recherche exacte comme dans acides_amines/views.py)
    amino_acid_metabolites = Metabolite.objects.filter(name__in=amino_acids_upper)
    
    # Mapping entre les noms des acides aminés en majuscule et leurs IDs
    amino_acid_ids = {m.name: m.id for m in amino_acid_metabolites}
    
    logger.info(f"Acides aminés trouvés: {len(amino_acid_ids)}")
    logger.info(f"Correspondances: {amino_acid_ids}")
    
    if not amino_acid_ids:
        # Aucun acide aminé trouvé, définir les similarités à 0
        logger.warning("Aucun acide aminé trouvé dans la base de données")
        for plant_data in full_common_plants['results']:
            if isinstance(plant_data, dict):
                plant_data['amino_acid_similarity'] = 0.0
            else:
                plant_data.amino_acid_similarity = 0.0
    else:
        # Récupérer tous les métabolites d'acides aminés en une seule requête, en conservant les parties de plantes
        all_aa_instances = MetabolitePlant.objects.filter(
            metabolite_id__in=list(amino_acid_ids.values())
        ).values('plant_name', 'metabolite__name', 'plant_part', 'low', 'high', 'reference')
        
        # Organiser les données par plante et par acide aminé
        plant_aa_data = {}
        
        for instance in all_aa_instances:
            plant_name = instance['plant_name']
            
            if plant_name not in plant_aa_data:
                plant_aa_data[plant_name] = {}
                
            metabolite_name = instance['metabolite__name']
            display_name = amino_acid_mapping.get(metabolite_name)
            
            if display_name not in plant_aa_data[plant_name]:
                plant_aa_data[plant_name][display_name] = []
                
            plant_aa_data[plant_name][display_name].append({
                'plant_part': instance['plant_part'] or 'Non spécifié',
                'low': instance['low'],
                'high': instance['high'],
                'reference': instance['reference']
            })
        
        # Récupérer toutes les plantes (exactement comme dans acides_amines/views.py)
        all_plants = Plant.objects.all().order_by('name')
        
        # Calculer les similarités d'acides aminés avec toutes les plantes
        similarities = calculate_amino_acid_similarity(
            plant_aa_data=plant_aa_data,
            plants_data=all_plants,
            amino_acids=amino_acids,
            ref_plant_id=plant.id,
            normalization='sum'  # Toujours utiliser la normalisation par somme pour comparer
        )
        
        # Ajouter les similarités aux plantes dans les résultats
        similarity_found = 0
        similarity_missing = 0
        
        for plant_data in full_common_plants['results']:
            if isinstance(plant_data, dict):
                plant_id = plant_data['id']
                if plant_id in similarities:
                    plant_data['amino_acid_similarity'] = similarities[plant_id]
                    similarity_found += 1
                    logger.info(f"Similarité assignée - Plante {plant_data['name']} (id={plant_id}): similarité = {similarities[plant_id]}")
                else:
                    plant_data['amino_acid_similarity'] = 0.0
                    similarity_missing += 1
                    logger.warning(f"Similarité manquante - Plante {plant_data['name']} (id={plant_id})")
            else:
                plant_id = plant_data.id
                if plant_id in similarities:
                    plant_data.amino_acid_similarity = similarities[plant_id]
                    similarity_found += 1
                    logger.info(f"Similarité assignée - Plante {plant_data.name} (id={plant_id}): similarité = {similarities[plant_id]}")
                else:
                    plant_data.amino_acid_similarity = 0.0
                    similarity_missing += 1
                    logger.warning(f"Similarité manquante - Plante {plant_data.name} (id={plant_id})")
        
        logger.info(f"Résumé des similarités : {similarity_found} trouvées, {similarity_missing} manquantes")
        logger.info(f"Similarités calculées pour {len(similarities)} plantes")
    
    # Tri spécifique par similarité des acides aminés si demandé
    if amino_acid_similarity_sort:
        reverse = amino_acid_similarity_sort == 'desc'
        
        # Définir une fonction clé pour le tri
        def get_amino_acid_similarity(plant_data):
            if isinstance(plant_data, dict):
                return plant_data.get('amino_acid_similarity', 0) or 0
            else:
                return getattr(plant_data, 'amino_acid_similarity', 0) or 0
        
        # Trier l'ensemble des résultats
        full_common_plants['results'] = sorted(full_common_plants['results'], key=get_amino_acid_similarity, reverse=reverse)
    
    # Tri spécifique par concentration moyenne d'un métabolite si demandé
    elif metabolite_concentration_sort and metabolite_ids:
        metabolite_id, direction = metabolite_concentration_sort
        reverse = direction == 'desc'
        
        # Définir une fonction clé pour le tri
        def get_concentration_average(plant_data):
            if isinstance(plant_data, dict):
                concentrations = plant_data.get('metabolite_concentrations', {})
                if int(metabolite_id) in concentrations:
                    return concentrations[int(metabolite_id)].get('average', 0) or 0
            else:
                concentrations = getattr(plant_data, 'metabolite_concentrations', {})
                if int(metabolite_id) in concentrations:
                    return concentrations[int(metabolite_id)].get('average', 0) or 0
            return 0
        
        # Trier l'ensemble des résultats
        full_common_plants['results'] = sorted(full_common_plants['results'], key=get_concentration_average, reverse=reverse)
    
    # Tri standard suivant les paramètres communs
    elif common_sort_params:
        logger.info(f"Application des tris standards: {common_sort_params}")
        
        # Appliquer les tris en séquence (du plus prioritaire au moins prioritaire)
        for field, direction in common_sort_params:
            reverse = direction.lower() == 'desc'
            
            if field == 'name':
                # Tri par nom
                full_common_plants['results'] = sorted(
                    full_common_plants['results'], 
                    key=lambda x: x['name'].lower() if isinstance(x, dict) else x.name.lower(), 
                    reverse=reverse
                )
            elif field == 'common_metabolites':
                # Tri par nombre de métabolites en commun
                full_common_plants['results'] = sorted(
                    full_common_plants['results'], 
                    key=lambda x: x['common_metabolites_count'] if isinstance(x, dict) else x.common_metabolites_count, 
                    reverse=reverse
                )
            elif field == 'common_percentage':
                # Tri par pourcentage de métabolites en commun
                full_common_plants['results'] = sorted(
                    full_common_plants['results'], 
                    key=lambda x: x['common_metabolites_percentage'] if isinstance(x, dict) else x.common_metabolites_percentage, 
                    reverse=reverse
                )
            elif field == 'meta_percentage_score':
                # Tri par score Meta%
                full_common_plants['results'] = sorted(
                    full_common_plants['results'], 
                    key=lambda x: x['meta_percentage_score'] if isinstance(x, dict) else x.meta_percentage_score, 
                    reverse=reverse
                )
            elif field == 'meta_root_score':
                # Tri par score MetaRacine
                full_common_plants['results'] = sorted(
                    full_common_plants['results'], 
                    key=lambda x: x['meta_root_score'] if isinstance(x, dict) else x.meta_root_score, 
                    reverse=reverse
                )
    
    # Appliquer la pagination manuellement
    start_idx = (int(common_page) - 1) * 20
    end_idx = min(start_idx + 20, len(full_common_plants['results']))
    
    # Recréer la structure de pagination
    paginated_results = {
        'results': full_common_plants['results'][start_idx:end_idx],
        'total_count': full_common_plants['total_count'],
        'page': int(common_page),
        'per_page': 20,
        'total_pages': (full_common_plants['total_count'] + 20 - 1) // 20
    }
    
    logger.info(f"Pagination manuelle: Affichage des plantes {start_idx+1}-{end_idx} sur {full_common_plants['total_count']}")
    
    # Vérification des valeurs de similarité avant envoi à la template
    not_found = 0
    has_value = 0
    
    for plant_data in paginated_results['results']:
        if isinstance(plant_data, dict):
            # Vérifier si la clé existe
            if 'amino_acid_similarity' in plant_data:
                similarity = plant_data['amino_acid_similarity']
                has_value += 1
                logger.info(f"Avant envoi à template - Plante {plant_data['name']} (id={plant_data['id']}): similarité = {similarity}")
            else:
                not_found += 1
                logger.warning(f"Clé 'amino_acid_similarity' MANQUANTE pour la plante {plant_data['name']} (id={plant_data['id']})")
                # Ajouter la clé manquante
                plant_data['amino_acid_similarity'] = 0.0
        else:
            # Vérifier si l'attribut existe
            if hasattr(plant_data, 'amino_acid_similarity'):
                similarity = plant_data.amino_acid_similarity
                has_value += 1
                logger.info(f"Avant envoi à template - Plante {plant_data.name} (id={plant_data.id}): similarité (obj) = {similarity}")
            else:
                not_found += 1
                logger.warning(f"Attribut 'amino_acid_similarity' MANQUANT pour la plante {plant_data.name} (id={plant_data.id})")
                # Ajouter l'attribut manquant
                setattr(plant_data, 'amino_acid_similarity', 0.0)
    
    logger.info(f"Résumé des valeurs : {has_value} plantes ont des valeurs, {not_found} plantes n'ont pas de valeurs")
    
    # Construire les paramètres de requête pour la pagination
    query_params = request.GET.copy()
    if 'common_page' in query_params:
        del query_params['common_page']
    
    context = {
        'plant': plant,
        'common_plants': paginated_results,
        'common_start': (paginated_results['page'] - 1) * 20,
        'activities': Activity.objects.all(),
        'selected_activity': activity_filter,
        'count_metabolites': plant.all_metabolites_count,
        'metabolite_count_by_activity': plant.get_metabolites_by_activity(activity_filter) if activity_filter else 0,
        'query_params': query_params.urlencode(),
        'debug_mode': False,
        'exclude_ubiquitous': exclude_ubiquitous,
        'activity_filter': activity_filter,
        'common_plants_count': paginated_results['total_count'],
        'search_text': search_text,
        'search_type': search_type,
        'all_metabolites': Metabolite.objects.all().order_by('name'),
        'selected_metabolite_1': metabolite_filter_1,
        'selected_metabolite_2': metabolite_filter_2,
        'selected_metabolite_3': metabolite_filter_3,
        'filtered_metabolites': filtered_metabolites,
        'amino_acids': amino_acids,
    }
    
    return render(request, 'metabolites/plant_common_metabolites.html', context)


@log_execution_time
@login_required
def plant_common_metabolites_pdf(request, plant_id):
    """Génère un PDF des métabolites en commun avec la plante spécifiée."""
    logger.info(f"Génération du PDF des métabolites en commun de la plante {plant_id}")
    
    # Import des modules nécessaires
    from django.http import HttpResponse
    from django.template.loader import get_template
    
    # On récupère la plante
    plant = get_object_or_404(Plant, id=plant_id)
    
    # On va d'abord générer le HTML normal avec la vue standard
    # en lui passant les mêmes paramètres
    from django.template.response import SimpleTemplateResponse
    
    # Garder une trace des requêtes originales
    request_copy = request.GET.copy()
    
    # Modifier la pagination pour tout récupérer (jusqu'à 100 entrées)
    request_copy['common_page'] = '1'
    # Créer une nouvelle QueryDict avec les paramètres modifiés
    request.GET = request_copy
    
    # Appeler la vue normale sans renvoyer le résultat au navigateur
    response = plant_common_metabolites(request, plant_id)
    
    # Si c'est une TemplateResponse, on récupère le contenu rendu
    if isinstance(response, SimpleTemplateResponse):
        response.render()
        html_content = response.content.decode('utf-8')
    else:
        # Si c'est déjà rendu, on a déjà le contenu HTML
        html_content = response.content.decode('utf-8')
    
    # Extraire le tableau du HTML complet à l'aide de marqueurs
    # Utiliser des expressions régulières pour extraire seulement le tableau et ses contenus
    table_pattern = re.compile(r'<table class="min-w-full table-auto">(.*?)</table>', re.DOTALL)
    table_match = table_pattern.search(html_content)
    table_html = table_match.group(0) if table_match else "<p>Impossible d'extraire le tableau</p>"
    
    # Appliquer des modifications au HTML pour une meilleure compatibilité avec xhtml2pdf
    # Remplacer les spans avec des classes par des spans avec des styles inline
    table_html = table_html.replace('class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full blue-percentage"', 
                                 'style="display:inline-block; color:#2563eb; font-weight:bold;"')
    
    table_html = table_html.replace('class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full green-percentage"', 
                                 'style="display:inline-block; color:#16a34a; font-weight:bold;"')
    
    # Améliorer l'affichage des similitudes AA
    table_html = table_html.replace('class="pill-aa similarity-value text-green-600"', 
                                 'style="display:inline-block; color:#16a34a; font-weight:bold;"')
    
    table_html = table_html.replace('class="pill-aa similarity-value text-yellow-600"', 
                                 'style="display:inline-block; color:#ca8a04; font-weight:bold;"')
    
    table_html = table_html.replace('class="pill-aa similarity-value text-red-600"', 
                                 'style="display:inline-block; color:#dc2626; font-weight:bold;"')
    
    # Améliorer l'affichage des autres pills
    table_html = table_html.replace('class="pill-purple"', 
                                 'style="display:inline-block; color:#8b5cf6;"')
    
    table_html = table_html.replace('class="pill-pink"', 
                                 'style="display:inline-block; color:#ec4899;"')
    
    # Supprimer le background de la pill orange (concentrations des métabolites)
    table_html = table_html.replace('class="pill-orange"', 
                                 'style="display:inline-block; color:#f59e0b; background-color:transparent; border:none;"')
    
    table_html = table_html.replace('class="pill-blue"', 
                                 'style="display:inline-block; color:#2563eb;"')
    
    # Améliorer les styles des cellules du tableau
    table_html = table_html.replace('class="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider"', 
                                 'style="background-color:#f9fafb; padding:5px; text-align:left; font-size:7pt; font-weight:bold; color:#6b7280; text-transform:uppercase; border:1px solid #e5e7eb;"')
    
    table_html = table_html.replace('class="px-6 py-4 whitespace-nowrap"', 
                                 'style="padding:5px; border:1px solid #e5e7eb;"')
    
    table_html = table_html.replace('class="px-6 py-4 whitespace-nowrap text-sm text-gray-500"', 
                                 'style="padding:5px; border:1px solid #e5e7eb; color:#6b7280; font-size:8pt;"')
    
    table_html = table_html.replace('class="px-6 py-4 whitespace-nowrap text-sm"', 
                                 'style="padding:5px; border:1px solid #e5e7eb; font-size:8pt;"')
    
    # Améliorations des styles pour les cellules contenant les noms de plantes - en vert et compactés
    table_html = table_html.replace('class="text-sm font-medium text-gray-900"', 
                                 'style="font-size:8pt; font-weight:bold; color:#166534; margin:0; padding:0; line-height:1.1;"')
    
    table_html = table_html.replace('class="text-sm text-gray-500"', 
                                 'style="font-size:7pt; color:#6b7280; margin:0; padding:0; line-height:1.1;"')
    
    # Réduire l'espace dans la div flex-items-center
    table_html = table_html.replace('class="flex items-center"', 'style="display:block; margin:0; padding:0; line-height:1;"')
    
    # Modifier la div ml-0 pour réduire l'espace
    table_html = table_html.replace('class="ml-0"', 'style="margin:0; padding:0; line-height:1;"')
    
    # Ajouter un attribut border explicite au tableau pour s'assurer qu'il s'affiche correctement
    table_html = table_html.replace('<table class="min-w-full table-auto">', 
                                 '<table border="1" style="width:100%; border-collapse:collapse; border:1px solid #e5e7eb;">')
    
    # Suppression des contrôles de tri dans les en-têtes
    # Rechercher et remplacer les balises select dans les en-têtes
    table_html = re.sub(r'<select[^>]*>.*?</select>', '', table_html, flags=re.DOTALL)

    # Suppression des liens hypertextes pour les noms de plantes
    # Rechercher et remplacer les balises <a> par leur contenu
    pattern_links = re.compile(r'<a [^>]*href="[^"]*"[^>]*>(.*?)</a>', re.DOTALL)
    for match in pattern_links.finditer(table_html):
        link_content = match.group(1)
        table_html = table_html.replace(match.group(0), link_content)
    
    # Nettoyer les div flex-col gap-1 qui contiennent maintenant uniquement les titres
    pattern_flex_col = re.compile(r'<div class="flex flex-col gap-1.*?"><span>(.*?)</span>.*?</div>', re.DOTALL)
    for match in pattern_flex_col.finditer(table_html):
        title_text = match.group(1)
        table_html = table_html.replace(match.group(0), title_text)
    
    # Nettoyer les titres qui ont un saut de ligne <br>
    table_html = table_html.replace('<br>', ' ')
    
    # Suppression des infobulles de détail (tooltips au survol)
    # Repérer et supprimer les divs qui sont des infobulles
    pattern_tooltip = re.compile(r'<div class="absolute left-0 bottom-full mb-2.*?</div>\s*<div class="absolute -bottom-2.*?</div>', re.DOTALL)
    table_html = pattern_tooltip.sub('', table_html)
    
    # Supprimer les attributs group et les classes group-hover
    table_html = table_html.replace('group', '')
    table_html = table_html.replace('hover:opacity-100', '')
    table_html = table_html.replace('hover:visible', '')
    table_html = re.sub(r'opacity-0\s*invisible', '', table_html)
    
    # Supprimer explicitement la couleur rouge qui reste
    table_html = table_html.replace('text-red-600', 'text-gray-600')
    
    # Rechercher tous les attributs style contenant "background" + un rouge quelconque
    pattern_bg_color = re.compile(r'style="([^"]*background[^"]*red[^"]*)"')
    for match in pattern_bg_color.finditer(table_html):
        style_content = match.group(1)
        # Supprimer la partie contenant "background" et "red" mais garder le reste
        new_style = re.sub(r'background[^;]*;?', '', style_content)
        table_html = table_html.replace(style_content, new_style)
    
    # Éliminer tous les fonds rouges par une approche plus générale
    colors = ["#FF0000", "#DC2626", "#EF4444", "#F87171", "#FCA5A5", "red", "rgb(220,38,38)", "rgb(255,0,0)"]
    
    for color in colors:
        table_html = table_html.replace(f'background-color:{color}', '')
        table_html = table_html.replace(f'background:{color}', '')
        
    # Supprimer tous les background-color qui restent (approche radicale si nécessaire)
    if "background-color:#f" in table_html.lower() or "background-color:#e" in table_html.lower() or "background-color:#d" in table_html.lower() or "background-color:red" in table_html.lower():
        # Supprimer tous les attributs background-color
        table_html = re.sub(r'background-color:[^;]*;?', '', table_html)
    
    # Suppression explicite des arrière-plans pour les pill-orange (concentrations des métabolites)
    pattern_pill_orange = re.compile(r'<span [^>]*pill-orange[^>]*>')
    for match in pattern_pill_orange.finditer(table_html):
        span_content = match.group(0)
        # Supprimer tout attribut background-color
        clean_span = re.sub(r'background-color:[^;]*;?', 'background-color:transparent;', span_content)
        table_html = table_html.replace(span_content, clean_span)
        
    # Récupérer les filtres appliqués pour les afficher dans le PDF
    filters_description = []
    activity_filter = request.GET.get('activity')
    exclude_ubiquitous = request.GET.get('exclude_ubiquitous') == 'true'
    search_text = request.GET.get('search_text', '')
    search_type = request.GET.get('search_type', 'contains')
    
    if activity_filter:
        filters_description.append(f"Activité: {activity_filter}")
    if exclude_ubiquitous:
        filters_description.append("Métabolites ubiquitaires exclus")
    if search_text:
        filters_description.append(f"Recherche: {search_text} ({search_type})")
    
    # Récupérer les informations de tri pour les afficher dans le PDF
    sorting_description = []
    for i in range(5):
        field = request.GET.get(f'common_sort{i}')
        direction = request.GET.get(f'common_direction{i}')
        if field and direction:
            field_label = {
                'name': 'Nom de plante', 
                'common_metabolites': 'Nb métabolites commun',
                'common_percentage': '% en commun',
                'amino_acid_similarity': 'Similarité AA',
                'meta_percentage_score': 'Meta%',
                'meta_root_score': 'MetaRacine',
            }.get(field, field)
            if field.startswith('metabolite_concentration_'):
                metabolite_id = field.replace('metabolite_concentration_', '')
                try:
                    metabolite = Metabolite.objects.get(id=metabolite_id)
                    field_label = f"Concentration {metabolite.name}"
                except:
                    pass
            direction_label = 'décroissant' if direction == 'desc' else 'croissant'
            sorting_description.append(f"{field_label} ({direction_label})")
    
    # Créer un nouveau HTML minimal pour le PDF, qui inclut le tableau extrait et les styles nécessaires
    context = {
        'plant': plant,
        'table_html': table_html,
        'filters_description': filters_description,
        'sorting_description': sorting_description,
        'today': datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
    }
    
    # Générer le PDF
    try:
        # Import xhtml2pdf seulement si nécessaire
        from xhtml2pdf import pisa
        
        template = get_template('metabolites/plant_common_metabolites_pdf_extracted.html')
        html = template.render(context)
        
        # Créer une réponse HTTP pour PDF
        response = HttpResponse(content_type='application/pdf')
        filename = f"metabolites_communs_{plant.name.replace(' ', '_')}.pdf"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        # Convertir HTML en PDF
        pisa_status = pisa.CreatePDF(html, dest=response)
        
        # Si la conversion échoue, afficher un message d'erreur
        if pisa_status.err:
            logger.error('Erreur lors de la génération du PDF')
            return HttpResponse('Une erreur est survenue lors de la génération du PDF.')
        
        return response
    except ImportError:
        # Si xhtml2pdf n'est pas installé, afficher un message d'erreur
        logger.error('La bibliothèque xhtml2pdf n\'est pas installée')
        return HttpResponse(
            'Pour utiliser cette fonctionnalité, veuillez installer xhtml2pdf :<br>'
            '<code>pip install xhtml2pdf</code>'
        )

def calculate_average_concentration(low, high):
    """Calcule la concentration moyenne en gérant les valeurs None."""
    if low is not None and high is not None:
        return (low + high) / 2
    elif low is not None:
        return low
    elif high is not None:
        return high
    return 0

@login_required
def all_activities(request):
    # Récupération des paramètres
    search = request.GET.get('search')
    sort = request.GET.get('sort', 'name_asc')

    # Requête de base avec annotations pour les comptages
    activities_list = Activity.objects.annotate(
        metabolites_count=Count('metaboliteactivity', distinct=True)
    )

    # Appliquer la recherche si nécessaire
    if search:
        activities_list = activities_list.filter(name__icontains=search)

    # Appliquer le tri
    if sort == 'name_asc':
        activities_list = activities_list.order_by('name')
    elif sort == 'name_desc':
        activities_list = activities_list.order_by('-name')
    elif sort == 'metabolites_asc':
        activities_list = activities_list.order_by('metabolites_count')
    elif sort == 'metabolites_desc':
        activities_list = activities_list.order_by('-metabolites_count')

    # Pagination
    count_by_page = 50
    paginator = Paginator(activities_list, count_by_page)
    page_number = request.GET.get('page', 1)
    activities_list = paginator.get_page(page_number)
    start_number = (int(page_number) - 1) * count_by_page
    page_count = paginator.count
    print(f"Nombre de pages: {page_count}")
    context = {
        'activities': activities_list,
        'count_by_page': count_by_page,
        'start_number': start_number,
        'page_count': page_count,
    }

    return render(request, 'metabolites/all_activities.html', context)


@login_required
def activity_detail(request, activity_id):
    activity = get_object_or_404(Activity, id=activity_id)
    
    # Récupération des paramètres de tri, recherche et type de recherche pour les plantes
    sort = request.GET.get('plants_sort', 'concentration_desc')
    search = request.GET.get('search', '')
    search_type = request.GET.get('search_type', 'contains')
    
    # Récupération des paramètres de tri, recherche et type de recherche pour les métabolites
    metabolites_sort = request.GET.get('metabolites_sort')
    metabolites_direction = request.GET.get('metabolites_direction')
    metabolite_search_text = request.GET.get('metabolite_search_text', '')
    metabolite_search_type = request.GET.get('metabolite_search_type', 'contains')

    count_per_page = 20
    
    # Pagination des métabolites avec tri et recherche
    metabolites_page = request.GET.get('metabolites_page', 1)
    metabolites_list = activity.metaboliteactivity_set.select_related('metabolite').all()
    
    # Filtrage des métabolites par nom
    if metabolite_search_text:
        if metabolite_search_type == 'contains':
            metabolites_list = metabolites_list.filter(metabolite__name__icontains=metabolite_search_text)
        elif metabolite_search_type == 'starts_with':
            metabolites_list = metabolites_list.filter(metabolite__name__istartswith=metabolite_search_text)
    
    # Application du tri pour les métabolites
    if metabolites_sort and metabolites_direction:
        if metabolites_sort == 'metabolite_name':
            order_by = f"{'' if metabolites_direction == 'asc' else '-'}metabolite__name"
            metabolites_list = metabolites_list.order_by(order_by)
    else:
        # Tri par défaut pour les métabolites si aucun tri n'est spécifié
        if sort == 'name_asc':
            metabolites_list = metabolites_list.order_by('metabolite__name')
        elif sort == 'name_desc':
            metabolites_list = metabolites_list.order_by('-metabolite__name')
        elif sort == 'dosage_asc':
            metabolites_list = metabolites_list.order_by('dosage')
        elif sort == 'dosage_desc':
            metabolites_list = metabolites_list.order_by('-dosage')
    
    metabolites_paginator = Paginator(metabolites_list, count_per_page)
    metabolites = metabolites_paginator.get_page(metabolites_page)
    metabolite_page_count = metabolites_paginator.num_pages

    # Convertir le tri pour le format attendu par get_plants_by_total_concentration
    sort_params = []
    if sort == 'name_asc':
        sort_params = [('name', 'asc')]
    elif sort == 'name_desc':
        sort_params = [('name', 'desc')]
    elif sort == 'concentration_asc':
        sort_params = [('total_concentration', 'asc')]
    elif sort == 'concentration_desc':
        sort_params = [('total_concentration', 'desc')]
    elif sort == 'metabolites_asc':
        sort_params = [('metabolites_count', 'asc')]
    elif sort == 'metabolites_desc':
        sort_params = [('metabolites_count', 'desc')]

    # Pagination des plantes par concentration avec le nouveau format de tri
    concentration_page = int(request.GET.get('concentration_page', 1))
    plants_by_concentration = activity.get_plants_by_total_concentration(
        page=concentration_page,
        per_page=count_per_page,
        sort_params=sort_params,
        search=search,
        search_type=search_type
    )
    
    # Paramètres pour la pagination
    query_params = request.GET.copy()
    if 'metabolites_page' in query_params:
        del query_params['metabolites_page']
    if 'concentration_page' in query_params:
        del query_params['concentration_page']
    
    context = {
        'activity': activity,
        'metabolites': metabolites,
        'start_number': (int(metabolites_page) - 1) * count_per_page,
        'plants_by_concentration': plants_by_concentration,
        'concentration_start': (concentration_page - 1) * count_per_page,
        'query_params': query_params.urlencode(),
        'metabolite_page_count': metabolite_page_count,
        'current_sort': sort,
        'current_search': search,
        'search_type': search_type,
        'metabolites_page': metabolites_page,
        'metabolite_search_text': metabolite_search_text,
        'metabolite_search_type': metabolite_search_type,
    }
    
    return render(request, 'metabolites/activity_detail.html', context)
