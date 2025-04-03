from django.shortcuts import render
from django.db.models import Q, F, Sum, Case, When, Value, FloatField
from metabolites.models import Plant, Metabolite, MetabolitePlant
import numpy as np
from scipy.spatial.distance import cosine
from decimal import Decimal

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
    normalization = request.GET.get('normalization', 'none')  # Options: none, sum, zscore
    
    if selected_plant_id:
        selected_plant = Plant.objects.get(id=selected_plant_id)
        
        # Récupérer toutes les plantes sans limitation
        all_plants = Plant.objects.all().order_by('name')
        
        # Récupérer les plantes qui ont au moins un acide aminé
        plants_with_amino_acids = set(MetabolitePlant.objects.filter(
            metabolite_id__in=amino_acid_ids.values()
        ).values_list('plant_name', flat=True).distinct())
        
        # Récupérer tous les métabolites d'acides aminés en une seule requête
        all_plant_metabolites = MetabolitePlant.objects.filter(
            metabolite_id__in=amino_acid_ids.values()
        ).select_related('metabolite')
        
        # Organiser les métabolites par plante
        plant_metabolites = {}
        for pm in all_plant_metabolites:
            if pm.plant_name not in plant_metabolites:
                plant_metabolites[pm.plant_name] = []
            plant_metabolites[pm.plant_name].append(pm)
        
        # Préparer le dictionnaire pour stocker les données de chaque plante
        plant_data = []
        
        # Dictionnaire pour stocker les concentrations brutes de chaque plante pour le calcul de similarité
        raw_concentrations = {}
        
        for plant in all_plants:
            # Si la plante n'a pas d'acides aminés et n'est pas la plante sélectionnée, skip
            if plant.name not in plants_with_amino_acids and plant.id != int(selected_plant_id):
                continue
                
            # Créer un dictionnaire pour stocker les concentrations des acides aminés pour cette plante
            # Utiliser les noms d'affichage comme clés
            amino_acid_concentrations = {aa: {'low': None, 'high': None} for aa in amino_acids_display}
            
            # Pour chaque métabolite trouvé, mettre à jour les concentrations
            has_missing_data = False
            has_any_value = False
            
            if plant.name in plant_metabolites:
                for pm in plant_metabolites[plant.name]:
                    metabolite_name = pm.metabolite.name  # Nom du métabolite en majuscules
                    
                    # Si ce métabolite est un acide aminé que nous suivons
                    if metabolite_name in amino_acid_ids:
                        # Convertir le nom en majuscules vers le nom d'affichage
                        display_name = amino_acid_mapping.get(metabolite_name)
                        if display_name:
                            amino_acid_concentrations[display_name]['low'] = pm.low
                            amino_acid_concentrations[display_name]['high'] = pm.high
                            # Si au moins une valeur n'est pas nulle, marquer comme ayant des données
                            if pm.low or pm.high:
                                has_any_value = True
            
            # Vérifier si des données sont manquantes
            for aa in amino_acids_display:
                if amino_acid_concentrations[aa]['low'] is None and amino_acid_concentrations[aa]['high'] is None:
                    has_missing_data = True
                    # Définir à 0 pour l'affichage
                    amino_acid_concentrations[aa]['low'] = 0
                    amino_acid_concentrations[aa]['high'] = 0
            
            # Calculer les moyennes des valeurs min et max pour chaque acide aminé
            mean_concentrations = {}
            for aa in amino_acids_display:
                # Convertir les valeurs Decimal en float
                low = float(amino_acid_concentrations[aa]['low'] or 0)
                high = float(amino_acid_concentrations[aa]['high'] or 0)
                mean_concentrations[aa] = (low + high) / 2 if high > 0 else low
            
            # Stocker les concentrations moyennes brutes pour le calcul de similarité
            raw_concentrations[plant.id] = [float(mean_concentrations[aa]) for aa in amino_acids_display]
            
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
        
        # Appliquer la normalisation si nécessaire
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
        
        # Calculer la similarité cosinus entre la plante sélectionnée et les autres plantes
        # Note: La similarité est 1 - distance cosinus (car cosine_distance = 1 - cosine_similarity)
        similarities = {}
        if int(selected_plant_id) in normalized_concentrations:
            selected_plant_vector = normalized_concentrations[int(selected_plant_id)]
            for plant_id, vector in normalized_concentrations.items():
                if plant_id != int(selected_plant_id):
                    # Calculer la similarité cosinus (1 - distance cosinus)
                    # Gérer le cas où tous les éléments sont 0
                    if sum(selected_plant_vector) == 0 or sum(vector) == 0:
                        similarities[plant_id] = 0
                    else:
                        similarities[plant_id] = 1 - cosine(selected_plant_vector, vector)
        
        # Trier les plantes par similarité (du plus proche au plus éloigné)
        # et ajouter la similarité à chaque plante
        for plant_data_item in plant_data:
            plant_id = plant_data_item['plant'].id
            if plant_id != int(selected_plant_id) and plant_id in similarities:
                plant_data_item['similarity'] = similarities[plant_id]
        
        # Tri des plantes par similarité, en gardant la plante sélectionnée en premier
        sorted_plant_data = [item for item in plant_data if item['is_selected']]
        other_plants = sorted(
            [item for item in plant_data if not item['is_selected']], 
            key=lambda x: x.get('similarity', 0), 
            reverse=True
        )
        sorted_plant_data.extend(other_plants)
        
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
            'normalization': normalization
        }
    else:
        context = {
            'plants': plants,
            'amino_acids': amino_acids_display,
            'normalization': normalization
        }
    
    return render(request, 'acides_amines/test.html', context)
