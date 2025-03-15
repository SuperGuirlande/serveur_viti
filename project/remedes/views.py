from django.shortcuts import render, redirect, get_object_or_404
from django.core.serializers.json import DjangoJSONEncoder
from django.urls import reverse
from django.core.cache import cache
import json
import logging
from .models import Remede, Plant
from .forms import RemedeForm
from django.http import HttpResponse, JsonResponse
from django.db import connection
from metabolites.utils import log_execution_time
import math

logger = logging.getLogger('remedes')

def all_remedes(request):
    remedes = Remede.objects.all().order_by('-updated_at')

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
                remede.created_by = request.user
                remede.save()
                
                # Réassigner les plantes
                remede.plants.set(current_plants)
                remede.save()
                
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
                remede.created_by = request.user
                remede.save()
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

@log_execution_time
def select_plants_for_remede(request, remede_id):
    logger.info(f"Sélection des plantes pour le remède {remede_id}")
    remede = get_object_or_404(Remede.objects.prefetch_related('plants', 'activities'), id=remede_id)
    
    if request.method == 'POST':
        # Récupérer les plantes sélectionnées depuis le formulaire
        selected_plants = request.POST.getlist('selected_plants')
        logger.info(f"Plantes sélectionnées: {selected_plants}")
        
        # Récupérer l'option d'exclusion des métabolites ubiquitaires
        exclude_ubiquitous = 'exclude_ubiquitous' in request.POST
        logger.info(f"Exclusion des métabolites ubiquitaires: {exclude_ubiquitous}")
        
        # Sauvegarder les paramètres de tri actuels et l'option d'exclusion
        sort_params_to_save = {'exclude_ubiquitous': exclude_ubiquitous}
        for i in range(4):
            field = request.POST.get(f'sort{i}')
            direction = request.POST.get(f'direction{i}')
            if field and direction:
                sort_params_to_save[f'sort{i}'] = field
                sort_params_to_save[f'direction{i}'] = direction
        
        # Sauvegarder dans le modèle Remede
        remede.sort_params = sort_params_to_save
        remede.save()
        
        # Mettre à jour les plantes du remède
        remede.plants.set(Plant.objects.filter(id__in=selected_plants))
        logger.info(f"Remède mis à jour avec {len(selected_plants)} plantes")
            
        return redirect('all_remedes')
    
    # Récupérer les paramètres de tri
    sort_params = []
    exclude_ubiquitous = False
    
    # Vérifier si des paramètres de tri sont dans l'URL
    has_url_sort_params = False
    for i in range(4):
        field = request.GET.get(f'sort{i}')
        direction = request.GET.get(f'direction{i}')
        if field and direction:
            has_url_sort_params = True
            sort_params.append((field, direction))
    
    # Vérifier si l'option d'exclusion est dans l'URL
    if 'exclude_ubiquitous' in request.GET:
        exclude_ubiquitous = request.GET.get('exclude_ubiquitous') == 'true'
        has_url_sort_params = True
    
    # Si aucun paramètre dans l'URL, utiliser ceux sauvegardés dans le modèle
    if not has_url_sort_params and remede.sort_params:
        for i in range(4):
            field = remede.sort_params.get(f'sort{i}')
            direction = remede.sort_params.get(f'direction{i}')
            if field and direction:
                sort_params.append((field, direction))
        
        # Récupérer l'option d'exclusion sauvegardée
        if 'exclude_ubiquitous' in remede.sort_params:
            exclude_ubiquitous = remede.sort_params['exclude_ubiquitous']
    
    # Si toujours aucun paramètre de tri, utiliser la valeur par défaut
    if not sort_params:
        sort_params = [('common_activity_metabolites', 'desc')]
    
    selected_plants_ids = list(remede.plants.values_list('id', flat=True))
    plants_by_activity = {}
    
    # Clé de cache unique pour chaque combinaison de paramètres
    cache_key = f'remede_plants_{remede_id}_{remede.target_plant.name}_{json.dumps(sort_params)}_{exclude_ubiquitous}'
    logger.debug(f"Clé de cache: {cache_key}")
    
    # Forcer l'invalidation du cache pour le débogage
    cache.delete(cache_key)
    
    plants_by_activity = cache.get(cache_key)
    
    if plants_by_activity is None:
        logger.debug("Cache miss - Exécution des requêtes SQL")
        plants_by_activity = {}
        
        for activity in remede.activities.all():
            with connection.cursor() as cursor:
                query = """
                    SELECT 
                        p.id,
                        p.name,
                        p.french_name,
                        COUNT(DISTINCT mp.metabolite_id) as total_metabolites_count,
                        COUNT(DISTINCT CASE 
                            WHEN mp_target.metabolite_id IS NOT NULL 
                            THEN mp.metabolite_id 
                        END) as common_metabolites_count,
                        COUNT(DISTINCT CASE 
                            WHEN ma.activity_id = %s 
                            THEN mp.metabolite_id 
                        END) as activity_metabolites_count,
                        COUNT(DISTINCT CASE 
                            WHEN mp_target.metabolite_id IS NOT NULL AND ma.activity_id = %s 
                            THEN mp.metabolite_id 
                        END) as common_activity_metabolites_count,
                        COALESCE(SUM(
                            CASE 
                                WHEN ma.activity_id = %s
                                THEN 
                                    CASE 
                                        WHEN mp.high IS NOT NULL THEN mp.high
                                        WHEN mp.low IS NOT NULL THEN mp.low
                                        ELSE 0 
                                    END
                                ELSE 0
                            END
                        ), 0) as total_concentration,
                        GROUP_CONCAT(DISTINCT 
                            CASE 
                                WHEN mp_target.metabolite_id IS NOT NULL AND ma.activity_id = %s 
                                THEN m.name 
                            END
                        ) as common_metabolites_names,
                        GROUP_CONCAT(DISTINCT 
                            CASE 
                                WHEN ma.activity_id = %s 
                                AND mp_target.metabolite_id IS NULL
                                AND EXISTS (
                                    SELECT 1 
                                    FROM metabolites_metaboliteactivity ma2 
                                    WHERE ma2.metabolite_id = mp.metabolite_id 
                                    AND ma2.activity_id = %s
                                )
                                THEN m.name 
                            END
                        ) as complementary_metabolites_names
                    FROM metabolites_plant p
                    JOIN metabolites_metaboliteplant mp ON mp.plant_name = p.name
                    JOIN metabolites_metabolite m ON m.id = mp.metabolite_id
                    LEFT JOIN metabolites_metaboliteplant mp_target ON 
                        mp_target.metabolite_id = mp.metabolite_id AND 
                        mp_target.plant_name = %s
                    LEFT JOIN metabolites_metaboliteactivity ma ON ma.metabolite_id = mp.metabolite_id
                    WHERE p.name != %s
                """
                
                if exclude_ubiquitous:
                    query += " AND m.is_ubiquitous = FALSE"
                
                query += """
                    GROUP BY p.id, p.name
                """
                
                # Ajouter la condition HAVING seulement si nécessaire
                if not exclude_ubiquitous:
                    query += " HAVING activity_metabolites_count > 0 OR common_activity_metabolites_count > 0"
                else:
                    # Condition moins restrictive lorsque les métabolites ubiquitaires sont exclus
                    query += " HAVING total_metabolites_count > 0"
                
                # Construire la clause ORDER BY dynamiquement
                order_by_clauses = []
                for field, direction in sort_params:
                    if field == 'name':
                        order_by_clauses.append(f"name {direction}")
                    elif field == 'common_metabolites':
                        order_by_clauses.append(f"common_metabolites_count {direction}")
                    elif field == 'common_percentage':
                        order_by_clauses.append(f"(common_metabolites_count * 100.0 / NULLIF(total_metabolites_count, 0)) {direction}")
                    elif field == 'meta_percentage_score':
                        order_by_clauses.append(f"(common_metabolites_count * (common_metabolites_count * 100.0 / NULLIF(total_metabolites_count, 0)) / 100) {direction}")
                    elif field == 'meta_root_score':
                        order_by_clauses.append(f"(SQRT(common_metabolites_count) * (common_metabolites_count * 100.0 / NULLIF(total_metabolites_count, 0)) / 100) {direction}")
                    elif field == 'common_activity_metabolites':
                        order_by_clauses.append(f"common_activity_metabolites_count {direction}")
                    elif field == 'total_activity_metabolites':
                        order_by_clauses.append(f"activity_metabolites_count {direction}")
                    elif field == 'total_concentration':
                        order_by_clauses.append(f"total_concentration {direction}")
                
                if order_by_clauses:
                    query += f" ORDER BY {', '.join(order_by_clauses)}"
                
                query += " LIMIT 20"
                
                logger.debug(f"Requête SQL pour l'activité {activity.name}: {query}")
                
                cursor.execute(query, [
                    activity.id,  # Pour le premier COUNT CASE
                    activity.id,  # Pour le deuxième COUNT CASE
                    activity.id,  # Pour le CASE dans le SUM
                    activity.id,  # Pour le premier GROUP_CONCAT
                    activity.id,  # Pour le premier CASE dans le deuxième GROUP_CONCAT
                    activity.id,  # Pour le EXISTS dans le deuxième GROUP_CONCAT
                    remede.target_plant.name,  # Pour le JOIN avec mp_target
                    remede.target_plant.name,  # Pour WHERE p.name != %s
                ])
                
                columns = [col[0] for col in cursor.description]
                results = [dict(zip(columns, row)) for row in cursor.fetchall()]
                
                # Traiter les noms des métabolites
                for result in results:
                    result['common_metabolites_names'] = (
                        result['common_metabolites_names'].split(',')
                        if result['common_metabolites_names']
                        else []
                    )
                    result['complementary_metabolites_names'] = (
                        result['complementary_metabolites_names'].split(',')
                        if result['complementary_metabolites_names']
                        else []
                    )
                    
                    # Récupérer le nombre de métabolites de la plante cible
                    target_plant_metabolites_count = None
                    with connection.cursor() as count_cursor:
                        count_query = """
                            SELECT COUNT(DISTINCT mp.metabolite_id)
                            FROM metabolites_metaboliteplant mp
                            JOIN metabolites_metabolite m ON m.id = mp.metabolite_id
                            WHERE mp.plant_name = %s
                        """
                        
                        if exclude_ubiquitous:
                            count_query += " AND m.is_ubiquitous = FALSE"
                        
                        logger.debug(f"Requête SQL pour compter les métabolites de la plante cible: {count_query}")
                        
                        count_cursor.execute(count_query, [remede.target_plant.name])
                        target_plant_metabolites_count = count_cursor.fetchone()[0]
                    
                    # Calculer le pourcentage en commun avec la nouvelle méthode
                    common_count = result['common_metabolites_count']
                    plant_total = result['total_metabolites_count']
                    
                    # Toujours calculer par rapport à la plante affichée dans le tableau
                    percentage = (common_count * 100.0) / plant_total if plant_total > 0 else 0
                    
                    # Conserver la distinction visuelle entre les cas
                    if target_plant_metabolites_count >= plant_total:
                        result['percentage_type'] = 'blue'
                    else:
                        result['percentage_type'] = 'green'
                    
                    result['common_percentage'] = round(percentage, 1)
                    
                    # Calcul du score Meta% (S1) : Nombre de métabolites communs × Pourcentage de métabolites communs
                    result['meta_percentage_score'] = round(common_count * (percentage / 100), 2)
                    
                    # Calcul du score MetaRacine (S2) : Racine carrée du nombre de métabolites communs × Pourcentage de métabolites communs
                    result['meta_root_score'] = round(math.sqrt(common_count) * (percentage / 100), 2) if common_count > 0 else 0
                
                plants_by_activity[activity.name] = results
                logger.debug(f"Activité {activity.name}: {len(results)} plantes récupérées")

        # Mettre en cache pour 1 heure
        cache.set(cache_key, plants_by_activity, 3600)
        logger.debug("Résultats mis en cache")
    else:
        logger.debug("Cache hit - Utilisation des données en cache")

    # Créer un dictionnaire temporaire pour stocker toutes les plantes
    all_plants_dict = {}
    
    # Parcourir toutes les plantes de toutes les activités
    for activity_name, plants_list in plants_by_activity.items():
        for plant in plants_list:
            plant_id = str(plant['id'])
            if plant_id not in all_plants_dict:
                all_plants_dict[plant_id] = {
                    'name': plant['name'],
                    'french_name': plant['french_name'],
                    'activities': {}
                }
            all_plants_dict[plant_id]['activities'][activity_name] = {
                'concentration': plant.get('total_concentration', 0),
                'metabolites_count': plant.get('activity_metabolites_count', 0),
                'common_metabolites_names': plant.get('common_metabolites_names', []),
                'complementary_metabolites_names': plant.get('complementary_metabolites_names', [])
            }

    context = {
        'remede': remede,
        'plants_by_activity': plants_by_activity,
        'selected_plants_ids': selected_plants_ids,
        'sort_params': sort_params,
        'activities_json': json.dumps([activity.name for activity in remede.activities.all()]),
        'all_plants_data_json': json.dumps(all_plants_dict, cls=DjangoJSONEncoder),
        'exclude_ubiquitous': exclude_ubiquitous
    }
    
    return render(request, 'remedes/select_plants.html', context)

def remede_detail(request, remede_id):
    logger.info(f"Affichage des détails du remède {remede_id}")
    remede = get_object_or_404(
        Remede.objects.prefetch_related(
            'plants',
            'activities',
        ),
        id=remede_id
    )
    
    # Récupérer les plantes pour chaque activité avec leurs concentrations
    plants_by_activity = {}
    activity_recaps = {}
    
    # Pour chaque activité, récupérer les plantes et leurs concentrations
    for activity in remede.activities.all():
        with connection.cursor() as cursor:
            query = """
                SELECT 
                    p.id,
                    p.name,
                    p.french_name,
                    COUNT(DISTINCT mp.metabolite_id) as total_metabolites_count,
                    COUNT(DISTINCT CASE 
                        WHEN mp_target.metabolite_id IS NOT NULL 
                        THEN mp.metabolite_id 
                    END) as common_metabolites_count,
                    COUNT(DISTINCT CASE 
                        WHEN ma.activity_id = %s 
                        THEN mp.metabolite_id 
                    END) as activity_metabolites_count,
                    COUNT(DISTINCT CASE 
                        WHEN mp_target.metabolite_id IS NOT NULL AND ma.activity_id = %s 
                        THEN mp.metabolite_id 
                    END) as common_activity_metabolites_count,
                    COALESCE(SUM(
                        CASE 
                            WHEN ma.activity_id = %s
                            THEN 
                                CASE 
                                    WHEN mp.high IS NOT NULL THEN mp.high
                                    WHEN mp.low IS NOT NULL THEN mp.low
                                    ELSE 0 
                                END
                            ELSE 0
                        END
                    ), 0) as total_concentration,
                    GROUP_CONCAT(DISTINCT 
                        CASE 
                            WHEN mp_target.metabolite_id IS NOT NULL AND ma.activity_id = %s 
                            THEN m.name 
                        END
                    ) as common_metabolites_names,
                    GROUP_CONCAT(DISTINCT 
                        CASE 
                            WHEN ma.activity_id = %s 
                            AND mp_target.metabolite_id IS NULL
                            AND EXISTS (
                                SELECT 1 
                                FROM metabolites_metaboliteactivity ma2 
                                WHERE ma2.metabolite_id = mp.metabolite_id 
                                AND ma2.activity_id = %s
                            )
                            THEN m.name 
                        END
                    ) as complementary_metabolites_names
                FROM metabolites_plant p
                JOIN metabolites_metaboliteplant mp ON mp.plant_name = p.name
                JOIN metabolites_metabolite m ON m.id = mp.metabolite_id
                LEFT JOIN metabolites_metaboliteplant mp_target ON 
                    mp_target.metabolite_id = mp.metabolite_id AND 
                    mp_target.plant_name = %s
                LEFT JOIN metabolites_metaboliteactivity ma ON ma.metabolite_id = mp.metabolite_id
                WHERE p.id IN (SELECT id FROM metabolites_plant WHERE id IN %s)
                GROUP BY p.id, p.name
            """
            
            # Récupérer les IDs des plantes
            plant_ids = list(remede.plants.values_list('id', flat=True))
            
            if plant_ids:  # Vérifier s'il y a des plantes
                params = [
                    activity.id,  # Pour le premier COUNT CASE
                    activity.id,  # Pour le deuxième COUNT CASE
                    activity.id,  # Pour le CASE dans le SUM
                    activity.id,  # Pour le premier GROUP_CONCAT
                    activity.id,  # Pour le premier CASE dans le deuxième GROUP_CONCAT
                    activity.id,  # Pour le EXISTS dans le deuxième GROUP_CONCAT
                    remede.target_plant.name,  # Pour le JOIN avec mp_target
                    tuple(plant_ids),  # Pour la clause WHERE IN
                ]
                
                cursor.execute(query, params)
                
                columns = [col[0] for col in cursor.description]
                results = [dict(zip(columns, row)) for row in cursor.fetchall()]
                
                # Traiter les résultats
                for result in results:
                    # Calculer le pourcentage en commun
                    if result['total_metabolites_count'] > 0:
                        result['common_percentage'] = round(
                            (result['common_metabolites_count'] * 100.0) / result['total_metabolites_count'], 
                            1
                        )
                    else:
                        result['common_percentage'] = 0.0
                    
                    # Traiter les noms des métabolites
                    result['common_metabolites_names'] = (
                        result['common_metabolites_names'].split(',')
                        if result['common_metabolites_names']
                        else []
                    )
                    result['complementary_metabolites_names'] = (
                        result['complementary_metabolites_names'].split(',')
                        if result['complementary_metabolites_names']
                        else []
                    )
                
                plants_by_activity[activity.name] = results

                # Calculer le récapitulatif pour cette activité
                activity_recap = {
                    'plants': [],
                    'total_concentration': 0,
                    'common_metabolites': {},
                    'complementary_metabolites': {}
                }

                # Ajouter les plantes et calculer les totaux
                for plant_data in results:
                    activity_recap['plants'].append(plant_data['name'])
                    activity_recap['total_concentration'] += plant_data['total_concentration']

                    # Compter les occurrences des métabolites communs
                    for metabolite in plant_data['common_metabolites_names']:
                        activity_recap['common_metabolites'][metabolite] = activity_recap['common_metabolites'].get(metabolite, 0) + 1

                    # Compter les occurrences des métabolites complémentaires
                    for metabolite in plant_data['complementary_metabolites_names']:
                        activity_recap['complementary_metabolites'][metabolite] = activity_recap['complementary_metabolites'].get(metabolite, 0) + 1

                activity_recaps[activity.name] = activity_recap

    context = {
        'remede': remede,
        'plants_by_activity': plants_by_activity,
        'activity_recaps': activity_recaps,
        'activities_json': json.dumps([activity.name for activity in remede.activities.all()])
    }
    
    return render(request, 'remedes/remede_detail.html', context)

def delete_remede(request, remede_id):
    if request.method == 'POST':
        remede = get_object_or_404(Remede, id=remede_id)
        remede.delete()
        return JsonResponse({'status': 'success', 'redirect_url': reverse('all_remedes')})
    return JsonResponse({'status': 'error'}, status=400)
