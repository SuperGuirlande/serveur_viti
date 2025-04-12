from django.shortcuts import render
from django.db.models import Q, F, Sum, Case, When, Value, FloatField
from metabolites.models import Plant, Metabolite, MetabolitePlant
import numpy as np
from scipy.spatial.distance import cosine
from decimal import Decimal
from .utils import calculate_amino_acid_similarity

# Create your views here.

def amino_acid_profile(request):
    # Liste des acides aminés (format mixte pour l'affichage)
    amino_acids_display = [
        'Alanine', 'Arginine', 'Asparagine', 'Aspartic acid', 'Cysteine',
        'Glutamic acid', 'Glutamine', 'Glycine', 'Histidine', 'Isoleucine',
        'Leucine', 'Lysine', 'Methionine', 'Phenylalanine', 'Proline',
        'Serine', 'Threonine', 'Tryptophan', 'Tyrosine', 'Valine'
    ]
    
    # Créer une version uppercase pour la recherche dans la base de données
    amino_acids_upper = [aa.upper() for aa in amino_acids_display]
    
    # Créer un mapping entre le nom d'affichage et le nom uppercase
    amino_acid_mapping = {aa_upper: aa_display for aa_upper, aa_display in zip(amino_acids_upper, amino_acids_display)}
    
    # Récupérer toutes les plantes pour le formulaire de sélection
    plants = Plant.objects.all().order_by('name')
    
    # Récupérer les métabolites correspondant aux acides aminés (recherche insensible à la casse)
    amino_acid_metabolites = Metabolite.objects.filter(name__in=amino_acids_upper)
    
    # Mapping entre les noms des acides aminés en majuscule et leurs IDs
    amino_acid_ids = {m.name: m.id for m in amino_acid_metabolites}
    
    selected_plant_id = request.GET.get('plant_id')
    normalization = request.GET.get('normalization', 'none')
    
    if selected_plant_id:
        selected_plant = Plant.objects.get(id=selected_plant_id)
        
        # Récupérer toutes les plantes sans limitation
        all_plants = Plant.objects.all().order_by('name')
        
        # Récupérer tous les métabolites d'acides aminés en une seule requête, en conservant les parties de plantes
        all_aa_instances = MetabolitePlant.objects.filter(
            metabolite_id__in=amino_acid_ids.values()
        ).values('plant_name', 'metabolite__name', 'plant_part', 'low', 'high', 'reference')
        
        # Organiser les données par plante et par acide aminé
        plant_aa_data = {}
        plants_with_amino_acids = set()
        
        for instance in all_aa_instances:
            plant_name = instance['plant_name']
            plants_with_amino_acids.add(plant_name)
            
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
        
        # Préparer les données pour les plantes
        plant_data = []
        
        for plant in all_plants:
            # Si la plante n'a pas d'acides aminés et n'est pas la plante sélectionnée, skip
            if plant.name not in plants_with_amino_acids and plant.id != int(selected_plant_id):
                continue
            
            # Dictionnaire pour stocker les concentrations et les détails pour chaque acide aminé
            amino_acid_concentrations = {}
            mean_concentrations = {}
            has_missing_data = False
            has_any_value = False
            
            # Pour chaque acide aminé, calculer la moyenne des concentrations de toutes les parties
            for aa in amino_acids_display:
                if plant.name in plant_aa_data and aa in plant_aa_data[plant.name]:
                    # La plante a des données pour cet acide aminé
                    instances = plant_aa_data[plant.name][aa]
                    aa_avg_value = 0
                    count = 0
                    
                    # Stocker les détails par partie de plante
                    details = []
                    
                    for inst in instances:
                        # Convertir en float
                        low = float(inst['low']) if inst['low'] is not None else 0.0
                        high = float(inst['high']) if inst['high'] is not None else (low if low > 0.0 else 0.0)
                        
                        if low == 0.0 and high == 0.0:
                            # Ignorer les instances sans valeurs
                            continue
                        
                        # Calculer la moyenne pour cette instance
                        instance_avg = (low + high) / 2.0 if high > 0.0 else low
                        
                        # Ajouter à la moyenne globale
                        aa_avg_value += instance_avg
                        count += 1
                        
                        # Ajouter aux détails
                        details.append({
                            'plant_part': inst['plant_part'],
                            'low': low,
                            'high': high,
                            'reference': inst['reference']
                        })
                    
                    if count > 0:
                        # Il y a au moins une valeur non nulle
                        has_any_value = True
                        mean_value = aa_avg_value / count
                    else:
                        mean_value = 0.0
                        has_missing_data = True
                    
                    # Stocker la concentration moyenne et les détails
                    amino_acid_concentrations[aa] = {
                        'average': mean_value,
                        'details': details,
                        'count': count
                    }
                    mean_concentrations[aa] = mean_value
                    
                else:
                    # La plante n'a pas de données pour cet acide aminé
                    has_missing_data = True
                    amino_acid_concentrations[aa] = {
                        'average': 0.0,
                        'details': [],
                        'count': 0
                    }
                    mean_concentrations[aa] = 0.0
            
            # Si c'est la plante sélectionnée, on l'ajoute toujours
            # Sinon, on ajoute seulement si elle a au moins une valeur
            if plant.id == int(selected_plant_id) or has_any_value:
                plant_data.append({
                    'plant': plant,
                    'concentrations': amino_acid_concentrations,
                    'mean_concentrations': mean_concentrations,
                    'has_missing_data': has_missing_data,
                    'is_selected': plant.id == int(selected_plant_id)
                })
        
        # Utiliser la fonction commune pour calculer les similarités
        similarities = calculate_amino_acid_similarity(
            plant_aa_data=plant_aa_data,
            plants_data=all_plants,
            amino_acids=amino_acids_display,
            ref_plant_id=int(selected_plant_id),
            normalization=normalization
        )
        
        # Trier les plantes par similarité (du plus proche au plus éloigné)
        # et ajouter la similarité à chaque plante
        for plant_data_item in plant_data:
            plant_id = plant_data_item['plant'].id
            if plant_id in similarities:
                plant_data_item['similarity'] = similarities[plant_id]
        
        # Tri des plantes par similarité, en gardant la plante sélectionnée en premier
        sorted_plant_data = [item for item in plant_data if item['is_selected']]
        other_plants = sorted(
            [item for item in plant_data if not item['is_selected']], 
            key=lambda x: x.get('similarity', 0), 
            reverse=True
        )
        sorted_plant_data.extend(other_plants)
        
        # Pour l'affichage, ajouter les valeurs normalisées
        raw_concentrations = {}
        for plant_data_item in plant_data:
            plant_id = plant_data_item['plant'].id
            raw_concentrations[plant_id] = [float(plant_data_item['mean_concentrations'].get(aa, 0.0)) for aa in amino_acids_display]
        
        # Appliquer la normalisation pour l'affichage
        normalized_concentrations = {}
        for plant_id, concentrations in raw_concentrations.items():
            if normalization == 'sum':
                # Normalisation par somme pour que la somme = 1 (100%)
                total = sum(concentrations)
                if total > 0:
                    normalized_concentrations[plant_id] = [float(c) / total for c in concentrations]
                else:
                    normalized_concentrations[plant_id] = concentrations
            elif normalization == 'zscore':
                # Standardisation (centrer-réduire)
                mean = np.mean(concentrations)
                std = np.std(concentrations)
                if std > 0:
                    normalized_concentrations[plant_id] = [(float(c) - mean) / std for c in concentrations]
                else:
                    normalized_concentrations[plant_id] = [0] * len(concentrations)
            else:
                # Pas de normalisation
                normalized_concentrations[plant_id] = [float(c) for c in concentrations]
        
        # Préparer les données normalisées pour l'affichage
        for plant_data_item in sorted_plant_data:
            plant_id = plant_data_item['plant'].id
            if plant_id in normalized_concentrations:
                plant_data_item['normalized_values'] = dict(zip(amino_acids_display, normalized_concentrations[plant_id]))
        
        context = {
            'plants': plants,
            'selected_plant': selected_plant,
            'amino_acids': amino_acids_display,
            'plant_data': sorted_plant_data,
            'total_plants': Plant.objects.count(),
            'displayed_plants': len(sorted_plant_data),
            'normalization': normalization,
            'debug_mode': True  # Pour afficher les informations de débogage
        }
    else:
        context = {
            'plants': plants,
            'amino_acids': amino_acids_display,
            'normalization': normalization
        }
    
    return render(request, 'acides_amines/profile.html', context)
