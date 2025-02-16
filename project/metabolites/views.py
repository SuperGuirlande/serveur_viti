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
    paginator = Paginator(plants_list, 100)
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
    paginator = Paginator(metabolites_list, 100)
    page_number = request.GET.get('page')
    metabolites_list = paginator.get_page(page_number)
    
    context = {
        'metabolites': metabolites_list,
    }

    return render(request, 'metabolites/all_metabolites.html', context)


@login_required
def metabolites_en_communs(request, plant_id):
    target_plant = get_object_or_404(Plant, id=plant_id)

    plants = Plant.objects.all()
    activities = Activity.objects.all()
    metabolites = Metabolite.objects.all()
    metabolite_plants = MetabolitePlant.objects.all()

    communs = []

    for meta in metabolite_plants:
        if meta.plant_name == target_plant.name:
            communs.append(meta)



    context = {
        'metabolites': metabolites,
        'plants': plants,
        'activities': activities,
        'communs': communs,
    }

    return render(request, 'metabolites/communs_plants.html', context)


def plant_detail(request, plant_id):
    """
    Vue pour afficher les détails d'une plante spécifique.
    Inclut la liste des métabolites associés avec leurs parties de plante.
    """
    plant = get_object_or_404(Plant, id=plant_id)

    count_metabolites = MetabolitePlant.objects.filter(plant_name=plant.name).count()
    
    context = {
        'plant': plant,
        'count_metabolites': count_metabolites,
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
    paginator = Paginator(activities_list, 100)
    page_number = request.GET.get('page')
    activities_list = paginator.get_page(page_number)
    
    context = {
        'activities': activities_list,
    }

    return render(request, 'metabolites/all_activities.html', context)


@login_required
def activity_detail(request, activity_id):
    activity = get_object_or_404(Activity, id=activity_id)
    
    context = {
        'activity': activity,
    }
    
    return render(request, 'metabolites/activity_detail.html', context)
