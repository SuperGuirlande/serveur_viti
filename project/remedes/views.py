from django.shortcuts import render, redirect, get_object_or_404
from django.core.serializers.json import DjangoJSONEncoder
from django.urls import reverse
import json
from .models import Remede, Plant
from .forms import RemedeForm
from django.http import HttpResponse, JsonResponse

def all_remedes(request):
    remedes = Remede.objects.all()

    context = {
        'remedes': remedes
    }

    return render(request, 'remedes/all_remedes.html', context)


def remede_form(request, id=None):
    remede = None
    if id:
        remede = get_object_or_404(Remede.objects.prefetch_related('plants'), id=id)
        if request.method == 'POST':
            form = RemedeForm(request.POST, instance=remede)
            if form.is_valid():
                # Sauvegarder les plantes actuelles
                current_plants = list(remede.plants.all())
                
                # Sauvegarder le formulaire
                remede = form.save()
                
                # Réassigner les plantes
                remede.plants.set(current_plants)
                
                url = reverse('all_remedes')
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return HttpResponse(url)
                return redirect(url)
        else:
            form = RemedeForm(instance=remede)
    else:
        if request.method == 'POST':
            form = RemedeForm(request.POST)
            if form.is_valid():
                remede = form.save()
                url = reverse('select_plants_for_remede', kwargs={'remede_id': remede.id})
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return HttpResponse(url)
                return redirect(url)
        else:
            form = RemedeForm()

    context = {
        'remede': remede,
        'form': form
    }

    return render(request, 'remedes/create_remede.html', context)

def select_plants_for_remede(request, remede_id):
    remede = get_object_or_404(Remede.objects.prefetch_related('plants', 'activities'), id=remede_id)
    
    if request.method == 'POST':
        selected_plants = request.POST.getlist('selected_plants')
        remede.plants.set(Plant.objects.filter(id__in=selected_plants))
        return redirect('all_remedes')
    
    # Récupérer les IDs des plantes déjà sélectionnées
    selected_plants_ids = list(remede.plants.values_list('id', flat=True))
    
    # Récupérer les plantes pour chaque activité avec leurs concentrations
    plants_by_activity = {}
    all_plants_data = {}  # Stockage des données complètes pour chaque plante
    
    # Pour chaque activité, récupérer les plantes et leurs concentrations
    for activity in remede.activities.all():
        plants_data = activity.get_plants_by_total_concentration(
            page=1,
            per_page=20,
            sort='concentration_desc'
        )
        plants_by_activity[activity.name] = plants_data['results']
        
        # Stocker les données complètes pour chaque plante
        for plant in plants_data['results']:
            if plant['id'] not in all_plants_data:
                all_plants_data[plant['id']] = {
                    'name': plant['name'],
                    'activities': {}
                }
            all_plants_data[plant['id']]['activities'][activity.name] = {
                'concentration': float(plant['total_concentration']) if plant['total_concentration'] is not None else None,
                'metabolites_count': plant['metabolites_count']
            }
    
    # Sérialiser les données en JSON
    all_plants_data_json = json.dumps(all_plants_data, cls=DjangoJSONEncoder)
    activities_json = json.dumps([a.name for a in remede.activities.all()], cls=DjangoJSONEncoder)
    
    context = {
        'remede': remede,
        'plants_by_activity': plants_by_activity,
        'selected_plants_ids': selected_plants_ids,
        'all_plants_data_json': all_plants_data_json,
        'activities_json': activities_json,
    }
    
    return render(request, 'remedes/select_plants.html', context)

def remede_detail(request, remede_id):
    remede = get_object_or_404(
        Remede.objects.prefetch_related(
            'plants',
            'activities',
        ),
        id=remede_id
    )
    
    # Récupérer les plantes pour chaque activité avec leurs concentrations
    all_plants_data = {}
    
    # Pour chaque activité, récupérer les plantes et leurs concentrations
    for activity in remede.activities.all():
        plants_data = activity.get_plants_by_total_concentration(
            page=1,
            per_page=20,
            sort='concentration_desc'
        )
        
        # Stocker les données complètes pour chaque plante
        for plant in plants_data['results']:
            if plant['id'] not in all_plants_data:
                all_plants_data[plant['id']] = {
                    'name': plant['name'],
                    'activities': {}
                }
            all_plants_data[plant['id']]['activities'][activity.name] = {
                'concentration': float(plant['total_concentration']) if plant['total_concentration'] is not None else None
            }
    
    context = {
        'remede': remede,
        'plants_data': all_plants_data
    }
    
    return render(request, 'remedes/remede_detail.html', context)
