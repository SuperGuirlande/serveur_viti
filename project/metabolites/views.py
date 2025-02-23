from django.shortcuts import render, get_object_or_404
from django.db.models import Count, Subquery, OuterRef
from metabolites.models import Metabolite, MetaboliteActivity, MetabolitePlant, Plant, Activity
from django.core.paginator import Paginator
from django.contrib.auth.decorators import login_required
from django.db import models


@login_required
def metabolite_detail(request, id):
    metabolite = get_object_or_404(Metabolite, id=id)

    context = {
        'metabolite': metabolite
    }

    return render(request, 'metabolites/metabolite_detail.html', context)


@login_required
def all_plants(request):
    # Récupération des paramètres
    search = request.GET.get('search')
    sort = request.GET.get('sort', 'name_asc')

    # Requête de base avec annotation pour le comptage
    plants_list = Plant.objects.annotate(
        metabolites_count=Count(
            'name',
            filter=models.Q(name=models.F('name')),
            distinct=True
        )
    ).annotate(
        metabolites_count=Subquery(
            MetabolitePlant.objects.filter(
                plant_name=models.OuterRef('name')
            ).values('plant_name')
            .annotate(count=Count('metabolite_id', distinct=True))
            .values('count')
        )
    )

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
    paginator = Paginator(plants_list, 50)
    page_number = request.GET.get('page')
    plants_list = paginator.get_page(page_number)

    for plant in plants_list:
        all_metabolites = MetabolitePlant.objects.filter(plant_name=plant.name)
        count = all_metabolites.count()
        plant.all_metabolites_count = count
    
    context = {
        'plants': plants_list,
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
    paginator = Paginator(metabolites_list, 50)
    try:
        page_number = int(request.GET.get('page', 1))
    except (ValueError, TypeError):
        page_number = 1
    
    start_number = (page_number - 1) * 50
    metabolites = paginator.get_page(page_number)
    
    context = {
        'metabolites': metabolites,
    }

    return render(request, 'metabolites/all_metabolites.html', context)


@login_required
def plant_detail(request, plant_id):
    """
    Vue pour afficher les détails d'une plante spécifique.
    Inclut la liste des métabolites associés avec leurs parties de plante.
    """
    plant = get_object_or_404(Plant, id=plant_id)
    activity_filter = request.GET.get('activity', None)

    # Récupérer les métabolites avec pagination
    metabolites_list = plant.get_metabolites_with_parts()
    paginator = Paginator(metabolites_list, 50)  # 20 métabolites par page
    page_number = request.GET.get('page', 1)
    start_number = (int(page_number) - 1) * 50
    metabolites = paginator.get_page(page_number)
    
    # Compter les métabolites
    count_metabolites = MetabolitePlant.objects.filter(plant_name=plant.name).count()
    
    # Récupère les plantes communes en fonction du filtre d'activité
    common_plants = plant.get_common_plants(activity_filter)
    
    if activity_filter:
        metabolite_count_by_activity = plant.get_metabolites_by_activity(activity_filter)
    else:
        metabolite_count_by_activity = 0

    context = {
        'activities': Activity.objects.all(),
        'plant': plant,
        'count_metabolites': count_metabolites,
        'start_number': int(start_number),
        'metabolites': metabolites,
        'common_plants': common_plants,
        'metabolite_count_by_activity': metabolite_count_by_activity,
        'activity_filter': activity_filter,
        'selected_activity': activity_filter,
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
    paginator = Paginator(activities_list, 50)
    page_number = request.GET.get('page')
    activities_list = paginator.get_page(page_number)
    
    context = {
        'activities': activities_list,
    }

    return render(request, 'metabolites/all_activities.html', context)


@login_required
def activity_detail(request, activity_id):
    activity = get_object_or_404(Activity, id=activity_id)

    # Récupération des paramètres
    search = request.GET.get('search')
    sort = request.GET.get('sort', 'name_asc')

    # Requête de base pour les métabolites de cette activité
    metabolites_list = activity.metaboliteactivity_set.all()

    # Appliquer la recherche si nécessaire
    if search:
        metabolites_list = metabolites_list.filter(metabolite__name__icontains=search)

    # Appliquer le tri
    if sort == 'name_asc':
        metabolites_list = metabolites_list.order_by('metabolite__name')
    elif sort == 'name_desc':
        metabolites_list = metabolites_list.order_by('-metabolite__name')

    # Pagination
    paginator = Paginator(metabolites_list, 50)
    try:
        page_number = int(request.GET.get('page', 1))
    except (ValueError, TypeError):
        page_number = 1
    
    start_number = (page_number - 1) * 50
    metabolites = paginator.get_page(page_number)
    
    context = {
        'activity': activity,
        'metabolites': metabolites,
        'start_number': start_number,
    }
    
    return render(request, 'metabolites/activity_detail.html', context)
