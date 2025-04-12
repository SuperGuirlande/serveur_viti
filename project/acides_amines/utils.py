import numpy as np
from scipy.spatial.distance import cosine
import logging

logger = logging.getLogger('metabolites')

def calculate_amino_acid_similarity(plant_aa_data, plants_data, amino_acids, ref_plant_id, normalization='sum'):
    """
    Calcule la similarité cosinus entre les profils d'acides aminés des plantes.
    
    Args:
        plant_aa_data: Dictionnaire {plant_name: {acide_aminé: [instances]}} contenant les données d'acides aminés
        plants_data: Liste de dictionnaires ou d'objets représentant les plantes
        amino_acids: Liste des acides aminés à considérer
        ref_plant_id: ID de la plante de référence
        normalization: Type de normalisation à appliquer ('sum', 'zscore' ou 'none')
    
    Returns:
        Un dictionnaire {plant_id: similarité} avec les valeurs de similarité calculées
    """
    # Dictionnaire pour stocker les concentrations brutes
    raw_concentrations = {}
    
    # Dictionnaire pour stocker le profil de référence
    ref_amino_acid_profile = {}
    ref_plant_name = None
    
    # Identifier la plante de référence
    for plant_data in plants_data:
        if isinstance(plant_data, dict):
            plant_id = plant_data['id']
            plant_name = plant_data['name']
        else:
            plant_id = plant_data.id
            plant_name = plant_data.name
            
        if plant_id == ref_plant_id:
            ref_plant_name = plant_name
            break
    
    if not ref_plant_name:
        logger.warning(f"Plante de référence avec ID {ref_plant_id} non trouvée")
        return {}
    
    logger.debug(f"Calcul de similarité avec plante de référence: {ref_plant_name} (ID: {ref_plant_id})")
    
    # Nombre de plantes traitées
    plant_count = 0
    plant_with_aa_count = 0
    
    # Calculer les concentrations moyennes pour chaque plante
    for plant_data in plants_data:
        if isinstance(plant_data, dict):
            plant_id = plant_data['id']
            plant_name = plant_data['name']
        else:
            plant_id = plant_data.id
            plant_name = plant_data.name
        
        plant_count += 1
        
        # Créer un profil pour cette plante
        mean_concentrations = {}
        has_amino_acid_data = False
        
        if plant_name in plant_aa_data:
            has_amino_acid_data = True
            plant_with_aa_count += 1
            
            for aa in amino_acids:
                if aa in plant_aa_data[plant_name]:
                    instances = plant_aa_data[plant_name][aa]
                    aa_avg_value = 0
                    count = 0
                    
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
                    
                    if count > 0:
                        mean_concentrations[aa] = aa_avg_value / count
                    else:
                        mean_concentrations[aa] = 0.0
                else:
                    mean_concentrations[aa] = 0.0
        
        # Stocker les concentrations brutes pour cette plante
        raw_concentrations[plant_id] = [float(mean_concentrations.get(aa, 0.0)) for aa in amino_acids]
        
        # Stocker le profil de référence
        if plant_id == ref_plant_id:
            ref_amino_acid_profile = mean_concentrations
            logger.debug(f"Profil de la plante de référence {plant_name}: {mean_concentrations}")
    
    logger.info(f"Traitement des plantes terminé: {plant_count} plantes traitées, {plant_with_aa_count} avec des données d'acides aminés")
    
    # Vérifier si le profil de référence contient des données
    has_ref_profile = any(value > 0 for value in ref_amino_acid_profile.values())
    
    if not has_ref_profile:
        logger.warning(f"Aucune donnée d'acide aminé pour la plante de référence {ref_plant_name}")
        return {}
    
    # Appliquer la normalisation
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
    
    # Calculer la similarité cosinus
    similarities = {}
    
    if ref_plant_id in normalized_concentrations:
        ref_vector = normalized_concentrations[ref_plant_id]
        
        for plant_id, vector in normalized_concentrations.items():
            if plant_id == ref_plant_id:
                similarities[plant_id] = 1.0  # Similarité avec soi-même
                continue
                
            # Vérifier si les vecteurs ont des valeurs
            if sum(ref_vector) == 0 or sum(vector) == 0:
                similarities[plant_id] = 0.0
                continue
                
            try:
                similarity = 1 - cosine(ref_vector, vector)
                similarities[plant_id] = float(similarity)
            except Exception as e:
                logger.error(f"Erreur dans le calcul de similarité cosinus: {e}")
                logger.error(f"ref_vector: {ref_vector}, vector: {vector}")
                similarities[plant_id] = 0.0
    
    logger.info(f"Calcul de similarité terminé: {len(similarities)} similarités calculées")
    
    # Afficher les 10 premières similarités pour le débogage
    top_similarities = sorted([(k, v) for k, v in similarities.items() if v > 0], key=lambda x: x[1], reverse=True)[:10]
    if top_similarities:
        logger.debug(f"Top 10 des similarités: {top_similarities}")
    
    return similarities 