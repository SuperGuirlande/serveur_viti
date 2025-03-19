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

logger = logging.getLogger('metabolites')

@login_required
def metabolite_detail(request, id):
    metabolite = get_object_or_404(Metabolite, id=id)
    activities = metabolite.activities.all()

    # Récupération des paramètres de tri
    sort_field = request.GET.get('sort')
    sort_direction = request.GET.get('direction')

    count_per_page = 20
    paginator = Paginator(activities, count_per_page)
    activities_page_number = request.GET.get('activities_page', 1)
    activities = paginator.get_page(activities_page_number)
    activities_page_count = paginator.num_pages
    activities_start_number = (int(activities_page_number) - 1) * count_per_page

    # Passage des paramètres de tri à get_plants_with_parts
    plants = metabolite.get_plants_with_parts(sort_field=sort_field, sort_direction=sort_direction)
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
    
    # Récupérer les paramètres de tri et de pagination
    metabolites_page = request.GET.get('metabolites_page', 1)
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
    for i in range(5):
        field = request.GET.get(f'common_sort{i}')
        direction = request.GET.get(f'common_direction{i}')
        if field and direction:
            common_sort_params.append((field, direction))
    
    # Récupérer les métabolites de la plante
    metabolites = plant.get_metabolites_with_parts()
    
    # Paginer les résultats
    paginator = Paginator(metabolites, 20)
    try:
        metabolites = paginator.page(metabolites_page)
    except (PageNotAnInteger, EmptyPage):
        metabolites = paginator.page(1)
    
    # Récupérer les plantes avec des métabolites en commun
    common_plants = plant.get_common_plants(
        activity_filter=activity_filter,
        page=int(common_page),
        per_page=20,
        sort_params=common_sort_params,
        exclude_ubiquitous=exclude_ubiquitous,
        search_text=search_text,
        search_type=search_type,
        metabolite_filters=[metabolite_filter_1, metabolite_filter_2, metabolite_filter_3]
    )
    
    # Récupérer le nombre de métabolites pour l'activité sélectionnée
    metabolite_count_by_activity = None
    if activity_filter:
        metabolite_count_by_activity = plant.get_metabolites_by_activity(activity_filter)
    
    # Récupérer le nombre total de métabolites
    count_metabolites = plant.all_metabolites_count
    
    # Construire les paramètres de requête pour la pagination
    query_params = request.GET.copy()
    if 'metabolites_page' in query_params:
        del query_params['metabolites_page']
    if 'common_page' in query_params:
        del query_params['common_page']
    
    context = {
        'plant': plant,
        'metabolites': metabolites,
        'metabolites_start': (metabolites.number - 1) * 20,
        'common_plants': common_plants,
        'common_start': (common_plants['page'] - 1) * 20,
        'activities': Activity.objects.all(),
        'selected_activity': activity_filter,
        'count_metabolites': count_metabolites,
        'metabolite_count_by_activity': metabolite_count_by_activity,
        'query_params': query_params.urlencode(),
        'debug_mode': settings.DEBUG,
        'exclude_ubiquitous': exclude_ubiquitous,
        'activity_filter': activity_filter,
        'common_plants_count': common_plants['total_count'],
        'search_text': search_text,
        'search_type': search_type,
        'all_metabolites': Metabolite.objects.all().order_by('name'),
        'selected_metabolite_1': metabolite_filter_1,
        'selected_metabolite_2': metabolite_filter_2,
        'selected_metabolite_3': metabolite_filter_3,
    }
    
    return render(request, 'metabolites/plant_detail.html', context)


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
    sort = request.GET.get('plants_sort', 'name_asc')  
    search = request.GET.get('search', '')  

    count_per_page = 20
    
    # Pagination des métabolites avec tri
    metabolites_page = request.GET.get('metabolites_page', 1)
    metabolites_list = activity.metaboliteactivity_set.select_related('metabolite').all()
    
    # Application du tri pour les métabolites
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
        search=search
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
    }
    
    return render(request, 'metabolites/activity_detail.html', context)
