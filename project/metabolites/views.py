from django.shortcuts import render, get_object_or_404
from django.db.models import Count, Subquery, OuterRef, Prefetch
from metabolites.models import Metabolite, MetaboliteActivity, MetabolitePlant, Plant, Activity
from django.core.paginator import Paginator
from django.contrib.auth.decorators import login_required
from django.db import models
from .utils import log_execution_time
import logging

logger = logging.getLogger('metabolites')

@login_required
def metabolite_detail(request, id):
    metabolite = get_object_or_404(Metabolite, id=id)
    activities = metabolite.activities.all()

    count_per_page = 20
    paginator = Paginator(activities, count_per_page)
    activities_page_number = request.GET.get('activities_page', 1)
    activities = paginator.get_page(activities_page_number)
    activities_page_count = paginator.num_pages
    activities_start_number = (int(activities_page_number) - 1) * count_per_page

    plants = metabolite.get_plants_with_parts()
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


@login_required
def all_metabolites(request):
    # Récupération des paramètres
    search = request.GET.get('search')
    sort = request.GET.get('sort', 'name_asc')

    # Requête de base avec annotations pour les comptages
    metabolites_list = Metabolite.objects.annotate(
        activities_count=Count('activities', distinct=True),
        plants_count=Count('plants', distinct=True)
    )

    # Appliquer la recherche si nécessaire
    if search:
        metabolites_list = metabolites_list.filter(name__icontains=search)

    # Appliquer le tri
    if sort == 'name_asc':
        metabolites_list = metabolites_list.order_by('name')
    elif sort == 'name_desc':
        metabolites_list = metabolites_list.order_by('-name')
    elif sort == 'activities_asc':
        metabolites_list = metabolites_list.order_by('activities_count')
    elif sort == 'activities_desc':
        metabolites_list = metabolites_list.order_by('-activities_count')
    elif sort == 'plants_asc':
        metabolites_list = metabolites_list.order_by('plants_count')
    elif sort == 'plants_desc':
        metabolites_list = metabolites_list.order_by('-plants_count')

    # Pagination
    count_by_page = 50
    paginator = Paginator(metabolites_list, count_by_page)
    try:
        page_number = int(request.GET.get('page', 1))
    except (ValueError, TypeError):
        page_number = 1
    
    start_number = (page_number - 1) * count_by_page
    metabolites = paginator.get_page(page_number)
    
    context = {
        'metabolites': metabolites,
        'count_by_page': count_by_page,
        'start_number': start_number,
    }

    return render(request, 'metabolites/all_metabolites.html', context)


@log_execution_time
@login_required
def plant_detail(request, plant_id):
    logger.info(f"Accès aux détails de la plante {plant_id}")
    
    plant = get_object_or_404(Plant, id=plant_id)
    activity_filter = request.GET.get('activity', None)
    
    logger.debug(f"Récupération des métabolites pour la plante {plant.name}")
    metabolites_list = plant.get_metabolites_with_parts()
    
    # Pagination des métabolites
    count_by_page = 20
    metabolites_paginator = Paginator(metabolites_list, count_by_page)
    metabolites_page = request.GET.get('metabolites_page', 1)
    metabolites = metabolites_paginator.get_page(metabolites_page)
    
    # Récupère les plantes communes avec pagination SQL
    common_page = int(request.GET.get('common_page', 1))
    common_plants_data = plant.get_common_plants(
        activity_filter=activity_filter,
        page=common_page,
        per_page=count_by_page
    )
    
    # Calcul des pourcentages pour les plantes de la page courante
    for plant_data in common_plants_data['results']:
        try:
            if activity_filter:
                total = plant_data.get('total_metabolites_count', 0)
            else:
                total = plant_data.get('total_metabolites_count', 0)
            common = plant_data.get('common_metabolites_count', 0)
            if total > 0:
                percentage = (common * 100.0) / total
                plant_data['common_metabolites_percentage'] = round(percentage, 1)
            else:
                plant_data['common_metabolites_percentage'] = 0.0
        except (KeyError, TypeError):
            plant_data['common_metabolites_percentage'] = 0.0

    # Paramètres pour la pagination
    query_params = request.GET.copy()
    if 'metabolites_page' in query_params:
        del query_params['metabolites_page']
    if 'common_page' in query_params:
        del query_params['common_page']
    
    # Ajout du compte des métabolites avec l'activité spécifique
    metabolite_count_by_activity = plant.get_metabolites_by_activity(activity_filter) if activity_filter else None
    
    logger.info(f"Fin du traitement pour la plante {plant.name}")
    context = {
        'activities': Activity.objects.all(),
        'plant': plant,
        'count_metabolites': plant.all_metabolites_count,
        'metabolites_start': (int(metabolites_page) - 1) * count_by_page,
        'common_start': (common_page - 1) * count_by_page,
        'metabolites': metabolites,
        'common_plants': common_plants_data,
        'activity_filter': activity_filter,
        'selected_activity': activity_filter,
        'query_params': query_params.urlencode(),
        'count_by_page': count_by_page,
        'metabolite_count_by_activity': metabolite_count_by_activity,
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

    count_per_page = 20
    
    # Pagination des métabolites
    metabolites_page = request.GET.get('metabolites_page', 1)
    metabolites_list = activity.metaboliteactivity_set.all()
    metabolites_paginator = Paginator(metabolites_list, count_per_page)
    metabolites = metabolites_paginator.get_page(metabolites_page)
    metabolite_page_count = metabolites_paginator.num_pages
    print(f"Nombre de pages: {metabolite_page_count}")

    # Pagination des plantes par concentration - on garde la pagination SQL
    concentration_page = int(request.GET.get('concentration_page', 1))
    plants_by_concentration = activity.get_plants_by_total_concentration(
        page=concentration_page,
        per_page=count_per_page
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
    }
    
    return render(request, 'metabolites/activity_detail.html', context)
