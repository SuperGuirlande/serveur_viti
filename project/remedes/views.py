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
from metabolites.models import Metabolite
import math
from django.db.models import Q

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
    
    # Récupérer tous les métabolites de manière optimisée
    metabolites = Metabolite.objects.values('id', 'name').order_by('name').all()
    logger.info(f"Nombre total de métabolites chargés : {metabolites.count()}")
    
    # OPTIMISATION 1 : Éliminer la requête N+1 pour les métabolites sélectionnés
    # Collecter tous les IDs de métabolites d'abord
    metabolite_ids = []
    for i in range(1, 4):
        metabolite_id = request.GET.get(f'metabolite{i}')
        if not metabolite_id and remede.sort_params:
            metabolite_id = remede.sort_params.get(f'metabolite{i}')
        if metabolite_id:
            try:
                metabolite_ids.append(int(metabolite_id))
            except (ValueError, TypeError):
                logger.warning(f"Métabolite {i} ID invalide: {metabolite_id}")
    
    # Récupérer tous les métabolites sélectionnés en une seule requête
    selected_metabolites = []
    if metabolite_ids:
        selected_metabolites_dict = {m.id: m for m in Metabolite.objects.filter(id__in=metabolite_ids)}
        # Maintenir l'ordre original
        for metabolite_id in metabolite_ids:
            if metabolite_id in selected_metabolites_dict:
                selected_metabolites.append(selected_metabolites_dict[metabolite_id])
                logger.info(f"Métabolite sélectionné: {selected_metabolites_dict[metabolite_id].name}")
            else:
                logger.warning(f"Métabolite non trouvé: {metabolite_id}")
    
    if request.method == 'POST':
        # Récupérer les plantes sélectionnées depuis le formulaire
        selected_plants = request.POST.getlist('selected_plants')
        logger.info(f"Plantes sélectionnées: {selected_plants}")
        
        # Récupérer l'option d'exclusion des métabolites ubiquitaires
        exclude_ubiquitous = 'exclude_ubiquitous' in request.POST
        logger.info(f"Exclusion des métabolites ubiquitaires: {exclude_ubiquitous}")
        
        # Sauvegarder les paramètres de tri actuels et l'option d'exclusion
        sort_params_to_save = {'exclude_ubiquitous': exclude_ubiquitous}
        
        # Ajouter les métabolites sélectionnés
        for i in range(1, 4):
            metabolite_id = request.POST.get(f'metabolite{i}')
            if metabolite_id:
                sort_params_to_save[f'metabolite{i}'] = metabolite_id
        
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
    
    # OPTIMISATION 3 : Clé de cache optimisée et stable
    import hashlib
    # Créer un hash stable des paramètres pour éviter les clés trop longues
    params_str = f"{sort_params}_{exclude_ubiquitous}_{[m.id for m in selected_metabolites]}"
    params_hash = hashlib.md5(params_str.encode()).hexdigest()[:8]
    cache_key = f'remede_plants_{remede_id}_{remede.target_plant.id}_{params_hash}'
    logger.debug(f"Clé de cache optimisée: {cache_key}")
    
    plants_by_activity = cache.get(cache_key)
    
    if plants_by_activity is None:
        logger.debug("Cache miss - Exécution des requêtes SQL")
        with connection.cursor() as cursor:
            # Nettoyer les tables temporaires potentiellement existantes
            cursor.execute("DROP TEMPORARY TABLE IF EXISTS temp_target_metabolites")
            cursor.execute("DROP TEMPORARY TABLE IF EXISTS temp_selected_metabolites")
            
            # Créer des tables temporaires pour améliorer les performances
            # 1. Métabolites de la plante cible
            cursor.execute("""
                CREATE TEMPORARY TABLE temp_target_metabolites AS
                SELECT DISTINCT mp.metabolite_id
                FROM metabolites_metaboliteplant mp
                JOIN metabolites_metabolite m ON m.id = mp.metabolite_id
                WHERE mp.plant_name = %s
                AND (%s = FALSE OR m.is_ubiquitous = FALSE)
            """, [remede.target_plant.name, exclude_ubiquitous])
            cursor.execute("CREATE INDEX idx_temp_target_metabolites ON temp_target_metabolites(metabolite_id)")
            
            # 2. Métabolites sélectionnés pour le filtrage
            if selected_metabolites:
                placeholders = ', '.join(['%s'] * len(selected_metabolites))
                cursor.execute(f"""
                    CREATE TEMPORARY TABLE temp_selected_metabolites AS
                    SELECT DISTINCT id as metabolite_id
                    FROM metabolites_metabolite
                    WHERE id IN ({placeholders})
                """, [m.id for m in selected_metabolites])
                cursor.execute("CREATE INDEX idx_temp_selected_metabolites ON temp_selected_metabolites(metabolite_id)")
            
            # Parties de requête communes pour chaque activité
            base_query = """
                WITH plant_metabolites AS (
                    SELECT 
                        p.id,
                        p.name,
                        p.french_name,
                        COUNT(DISTINCT mp.metabolite_id) as total_metabolites_count,
                        COUNT(DISTINCT CASE WHEN ttm.metabolite_id IS NOT NULL THEN mp.metabolite_id END) as common_metabolites_count,
                        COUNT(DISTINCT CASE WHEN ma.activity_id = %s THEN mp.metabolite_id END) as activity_metabolites_count,
                        COUNT(DISTINCT CASE WHEN ttm.metabolite_id IS NOT NULL AND ma.activity_id = %s THEN mp.metabolite_id END) as common_activity_metabolites_count,
                        COALESCE(SUM(CASE 
                            WHEN ma.activity_id = %s 
                            THEN COALESCE(mp.high, mp.low, 0) 
                        END), 0) as total_concentration,
                        GROUP_CONCAT(
                            CASE WHEN ttm.metabolite_id IS NOT NULL AND ma.activity_id = %s 
                            THEN m.name 
                            END
                            ORDER BY m.name
                            SEPARATOR '|||'
                        ) as common_metabolites_names,
                        GROUP_CONCAT(
                            CASE WHEN ma.activity_id = %s AND ttm.metabolite_id IS NULL 
                            THEN m.name 
                            END
                            ORDER BY m.name
                            SEPARATOR '|||'
                        ) as complementary_metabolites_names,
                        ROUND(
                            COUNT(DISTINCT CASE WHEN ttm.metabolite_id IS NOT NULL THEN mp.metabolite_id END) * 100.0 / 
                            NULLIF(COUNT(DISTINCT mp.metabolite_id), 0),
                            1
                        ) as common_percentage,
                        ROUND(
                            COUNT(DISTINCT CASE WHEN ttm.metabolite_id IS NOT NULL THEN mp.metabolite_id END) * 
                            (COUNT(DISTINCT CASE WHEN ttm.metabolite_id IS NOT NULL THEN mp.metabolite_id END) * 100.0 / 
                            NULLIF(COUNT(DISTINCT mp.metabolite_id), 0)) / 100,
                            2
                        ) as meta_percentage_score,
                        ROUND(
                            SQRT(COUNT(DISTINCT CASE WHEN ttm.metabolite_id IS NOT NULL THEN mp.metabolite_id END)) * 
                            (COUNT(DISTINCT CASE WHEN ttm.metabolite_id IS NOT NULL THEN mp.metabolite_id END) * 100.0 / 
                            NULLIF(COUNT(DISTINCT mp.metabolite_id), 0)) / 100,
                            2
                        ) as meta_root_score
                    FROM metabolites_plant p
                    JOIN metabolites_metaboliteplant mp ON mp.plant_name = p.name
                    JOIN metabolites_metabolite m ON m.id = mp.metabolite_id
                    LEFT JOIN temp_target_metabolites ttm ON ttm.metabolite_id = mp.metabolite_id
                    LEFT JOIN metabolites_metaboliteactivity ma ON ma.metabolite_id = mp.metabolite_id
                    WHERE p.name != %s
            """
            
            # Ajouter la condition pour les métabolites sélectionnés
            if selected_metabolites:
                metabolite_condition = """
                    AND (
                        NOT EXISTS (SELECT 1 FROM temp_selected_metabolites)
                        OR NOT EXISTS (
                            SELECT 1 
                            FROM temp_selected_metabolites tsm 
                            WHERE NOT EXISTS (
                                SELECT 1 
                                FROM metabolites_metaboliteplant mp2 
                                WHERE mp2.plant_name = p.name 
                                AND mp2.metabolite_id = tsm.metabolite_id
                            )
                        )
                    )
                """
                base_query += metabolite_condition
            
            base_query += """
                    GROUP BY p.id, p.name, p.french_name
                )
                SELECT *
                FROM plant_metabolites
                ORDER BY 
            """
            
            # Exécuter la requête pour chaque activité
            plants_by_activity = {}
            for activity in remede.activities.all():
                # Construire les paramètres pour cette activité
                activity_params = [
                    activity.id,  # Pour le premier COUNT CASE
                    activity.id,  # Pour le deuxième COUNT CASE
                    activity.id,  # Pour le CASE dans le SUM
                    activity.id,  # Pour le premier GROUP_CONCAT
                    activity.id,  # Pour le deuxième GROUP_CONCAT
                    remede.target_plant.name  # Pour la condition WHERE p.name !=
                ]
                
                # Ajouter l'ordre de tri dynamique
                order_clauses = []
                for field, direction in sort_params:
                    if field == 'name':
                        order_clauses.append(f"name {direction}")
                    elif field == 'common_metabolites':
                        order_clauses.append(f"common_metabolites_count {direction}")
                    elif field == 'common_percentage':
                        order_clauses.append(f"common_percentage {direction}")
                    elif field == 'meta_percentage_score':
                        order_clauses.append(f"meta_percentage_score {direction}")
                    elif field == 'meta_root_score':
                        order_clauses.append(f"meta_root_score {direction}")
                    elif field == 'common_activity_metabolites':
                        order_clauses.append(f"common_activity_metabolites_count {direction}")
                    elif field == 'total_activity_metabolites':
                        order_clauses.append(f"activity_metabolites_count {direction}")
                    elif field == 'total_concentration':
                        order_clauses.append(f"total_concentration {direction}")
                
                query = base_query + (", ".join(order_clauses) if order_clauses else "common_activity_metabolites_count DESC")
                query += " LIMIT 20"  # Augmentation à 20 pour avoir plus de plantes par activité
                
                try:
                    cursor.execute(query, activity_params)
                    
                    # Traiter les résultats
                    columns = [col[0] for col in cursor.description]
                    results = [dict(zip(columns, row)) for row in cursor.fetchall()]
                    
                    # Traiter les listes de métabolites
                    for result in results:
                        result['common_metabolites_names'] = result['common_metabolites_names'].split('|||') if result['common_metabolites_names'] else []
                        result['complementary_metabolites_names'] = result['complementary_metabolites_names'].split('|||') if result['complementary_metabolites_names'] else []
                        
                        # Déterminer le type de pourcentage
                        target_metabolites_count = cursor.execute("""
                            SELECT COUNT(*) FROM temp_target_metabolites
                        """)
                        target_count = cursor.fetchone()[0]
                        result['percentage_type'] = 'blue' if target_count >= result['total_metabolites_count'] else 'green'
                    
                    plants_by_activity[activity.name] = results
                    
                except Exception as e:
                    logger.error(f"Erreur dans la requête pour l'activité {activity.name}: {str(e)}")
                    plants_by_activity[activity.name] = []
            
            # Nettoyer les tables temporaires
            cursor.execute("DROP TEMPORARY TABLE IF EXISTS temp_target_metabolites")
            cursor.execute("DROP TEMPORARY TABLE IF EXISTS temp_selected_metabolites")
            
            # Mettre en cache pour 12h
            cache.set(cache_key, plants_by_activity, 43200)
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

    # AJOUT : Récupérer les données des plantes déjà sélectionnées qui ne sont pas visibles
    missing_plant_ids = [pid for pid in selected_plants_ids if str(pid) not in all_plants_dict]
    
    if missing_plant_ids:
        logger.info(f"Récupération des données pour {len(missing_plant_ids)} plantes sélectionnées non visibles")
        
        with connection.cursor() as cursor:
            # Recréer les tables temporaires pour cette requête
            cursor.execute("DROP TEMPORARY TABLE IF EXISTS temp_target_metabolites_missing")
            cursor.execute("""
                CREATE TEMPORARY TABLE temp_target_metabolites_missing AS
                SELECT DISTINCT mp.metabolite_id
                FROM metabolites_metaboliteplant mp
                JOIN metabolites_metabolite m ON m.id = mp.metabolite_id
                WHERE mp.plant_name = %s
                AND (%s = FALSE OR m.is_ubiquitous = FALSE)
            """, [remede.target_plant.name, exclude_ubiquitous])
            cursor.execute("CREATE INDEX idx_temp_target_metabolites_missing ON temp_target_metabolites_missing(metabolite_id)")
            
            # Requête pour récupérer les données des plantes manquantes pour chaque activité
            for activity in remede.activities.all():
                missing_query = """
                    SELECT 
                        p.id,
                        p.name,
                        p.french_name,
                        COUNT(DISTINCT mp.metabolite_id) as total_metabolites_count,
                        COUNT(DISTINCT CASE WHEN ttm.metabolite_id IS NOT NULL THEN mp.metabolite_id END) as common_metabolites_count,
                        COUNT(DISTINCT CASE WHEN ma.activity_id = %s THEN mp.metabolite_id END) as activity_metabolites_count,
                        COUNT(DISTINCT CASE WHEN ttm.metabolite_id IS NOT NULL AND ma.activity_id = %s THEN mp.metabolite_id END) as common_activity_metabolites_count,
                        COALESCE(SUM(CASE 
                            WHEN ma.activity_id = %s 
                            THEN COALESCE(mp.high, mp.low, 0) 
                        END), 0) as total_concentration,
                        GROUP_CONCAT(
                            CASE WHEN ttm.metabolite_id IS NOT NULL AND ma.activity_id = %s 
                            THEN m.name 
                            END
                            ORDER BY m.name
                            SEPARATOR '|||'
                        ) as common_metabolites_names,
                        GROUP_CONCAT(
                            CASE WHEN ma.activity_id = %s AND ttm.metabolite_id IS NULL 
                            THEN m.name 
                            END
                            ORDER BY m.name
                            SEPARATOR '|||'
                        ) as complementary_metabolites_names
                    FROM metabolites_plant p
                    JOIN metabolites_metaboliteplant mp ON mp.plant_name = p.name
                    JOIN metabolites_metabolite m ON m.id = mp.metabolite_id
                    LEFT JOIN temp_target_metabolites_missing ttm ON ttm.metabolite_id = mp.metabolite_id
                    LEFT JOIN metabolites_metaboliteactivity ma ON ma.metabolite_id = mp.metabolite_id
                    WHERE p.id IN %s
                    GROUP BY p.id, p.name, p.french_name
                """
                
                missing_params = [
                    activity.id,  # Pour le premier COUNT CASE
                    activity.id,  # Pour le deuxième COUNT CASE
                    activity.id,  # Pour le CASE dans le SUM
                    activity.id,  # Pour le premier GROUP_CONCAT
                    activity.id,  # Pour le deuxième GROUP_CONCAT
                    tuple(missing_plant_ids)  # Pour la clause WHERE IN
                ]
                
                try:
                    cursor.execute(missing_query, missing_params)
                    columns = [col[0] for col in cursor.description]
                    missing_results = [dict(zip(columns, row)) for row in cursor.fetchall()]
                    
                    # Ajouter ces plantes à all_plants_dict
                    for plant in missing_results:
                        plant_id = str(plant['id'])
                        if plant_id not in all_plants_dict:
                            all_plants_dict[plant_id] = {
                                'name': plant['name'],
                                'french_name': plant['french_name'],
                                'activities': {}
                            }
                        
                        # Traiter les listes de métabolites
                        common_metabolites_names = plant['common_metabolites_names'].split('|||') if plant['common_metabolites_names'] else []
                        complementary_metabolites_names = plant['complementary_metabolites_names'].split('|||') if plant['complementary_metabolites_names'] else []
                        
                        all_plants_dict[plant_id]['activities'][activity.name] = {
                            'concentration': plant.get('total_concentration', 0),
                            'metabolites_count': plant.get('activity_metabolites_count', 0),
                            'common_metabolites_names': common_metabolites_names,
                            'complementary_metabolites_names': complementary_metabolites_names
                        }
                        
                except Exception as e:
                    logger.error(f"Erreur lors de la récupération des plantes manquantes pour l'activité {activity.name}: {str(e)}")
            
            # Nettoyer la table temporaire
            cursor.execute("DROP TEMPORARY TABLE IF EXISTS temp_target_metabolites_missing")

    context = {
        'remede': remede,
        'plants_by_activity': plants_by_activity,
        'selected_plants_ids': selected_plants_ids,
        'selected_plants_ids_json': json.dumps(selected_plants_ids, cls=DjangoJSONEncoder),
        'sort_params': sort_params,
        'activities_json': json.dumps([activity.name for activity in remede.activities.all()]),
        'all_plants_data_json': json.dumps(all_plants_dict, cls=DjangoJSONEncoder),
        'exclude_ubiquitous': exclude_ubiquitous,
        'metabolites': metabolites,
        'selected_metabolites': selected_metabolites
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
                        SEPARATOR '|||'
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
                        SEPARATOR '|||'
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
                        result['common_metabolites_names'].split('|||')
                        if result['common_metabolites_names']
                        else []
                    )
                    result['complementary_metabolites_names'] = (
                        result['complementary_metabolites_names'].split('|||')
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

def search_metabolites(request):
    query = request.GET.get('q', '')
    metabolite_id = request.GET.get('id')
    
    if metabolite_id:
        # Recherche par ID
        metabolites = Metabolite.objects.filter(id=metabolite_id).values('id', 'name')
    else:
        # Recherche par nom
        metabolites = Metabolite.objects.filter(
            name__icontains=query
        ).values('id', 'name')[:20]  # Limite à 20 résultats pour la performance
    
    return JsonResponse(list(metabolites), safe=False)
