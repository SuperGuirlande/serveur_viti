from django.core.management.base import BaseCommand
import csv
from metabolites.models import Metabolite, MetabolitePlant, Plant
from tqdm import tqdm
from decimal import Decimal, InvalidOperation
import logging
from datetime import datetime
import os

# Chemin relatif depuis le dossier project/
csv_file = "ressources/datas/all_chemicals_plants.csv"

class Command(BaseCommand):
    help = "Importe les données plantes-métabolites depuis le fichier CSV"

    def handle(self, *args, **options):
        # Création du dossier logs s'il n'existe pas
        logs_dir = "logs"
        if not os.path.exists(logs_dir):
            os.makedirs(logs_dir)
            
        # Configuration des logs
        log_filename = f"{logs_dir}/plants_import_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        logging.basicConfig(
            filename=log_filename,
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )

        self.stdout.write(self.style.SUCCESS("Début de l'import des données plantes..."))
        logging.info("Début de l'import des données plantes")

        try:
            plants_created = 0
            plant_objects_created = 0
            metabolites_not_found = 0
            problematic_rows = 0

            # Compte le nombre total de lignes pour la barre de progression
            with open(csv_file, 'r', encoding='latin-1') as f:
                total_rows = sum(1 for _ in f) - 1  # -1 pour l'en-tête si présent

            # Lecture du fichier CSV
            with open(csv_file, 'r', encoding='latin-1') as f:
                reader = csv.reader(f, quotechar='"', doublequote=True, delimiter=',')
                next(reader, None)  # Skip header if exists
                
                self.stdout.write(f"Nombre total de données à traiter : {total_rows}")
                logging.info(f"Nombre total de données à traiter : {total_rows}")

                # Utilisation de tqdm pour afficher une barre de progression
                for row in tqdm(reader, total=total_rows, desc="Traitement des données plantes"):
                    try:
                        # Vérification du nombre de colonnes
                        if len(row) != 7:
                            error_msg = (
                                f"Ligne ignorée - nombre incorrect de colonnes ({len(row)} au lieu de 7) : \n"
                                f"Contenu de la ligne : {row}"
                            )
                            logging.error(error_msg)
                            problematic_rows += 1
                            continue

                        chemical_name, plant_name, plant_part, low, high, deviation, reference = row

                        # Récupère le métabolite
                        try:
                            metabolite = Metabolite.objects.get(name=chemical_name.strip())
                        except Metabolite.DoesNotExist:
                            error_msg = f"Métabolite non trouvé : {chemical_name}"
                            logging.error(error_msg)
                            metabolites_not_found += 1
                            continue

                        # Nettoyage et préparation des données
                        plant_name = plant_name.strip()
                        plant_part = plant_part.strip()
                        
                        # Conversion des valeurs numériques avec gestion des "not available"
                        try:
                            low = Decimal(low.strip()) if low.strip() and low.strip().lower() != "not available" else None
                            high = Decimal(high.strip()) if high.strip() and high.strip().lower() != "not available" else None
                            deviation = Decimal(deviation.strip()) if deviation.strip() and deviation.strip().lower() != "not available" else None
                        except InvalidOperation:
                            error_msg = f"Valeur numérique invalide pour {chemical_name} dans {plant_name}: low={low}, high={high}, deviation={deviation}"
                            logging.warning(error_msg)
                            low = high = deviation = None

                        # Créé l'entrée Plant
                        plant, created = Plant.objects.get_or_create(name=plant_name)
                        if created:
                            plant_objects_created += 1
                            logging.info(f"Nouvelle plante créée : {plant_name}")

                        # Crée l'entrée MetabolitePlant
                        metabolite_plant, created = MetabolitePlant.objects.get_or_create(
                            metabolite=metabolite,
                            plant_name=plant_name,
                            plant_part=plant_part,
                            defaults={  # Utiliser defaults pour les champs qui peuvent varier
                                'low': low,
                                'high': high,
                                'deviation': deviation,
                                'reference': reference.strip() if reference else None
                            }
                        )

                        if not created and any([
                            metabolite_plant.low != low,
                            metabolite_plant.high != high,
                            metabolite_plant.deviation != deviation,
                            metabolite_plant.reference != (reference.strip() if reference else None)
                        ]):
                            logging.warning(
                                f"Doublon détecté avec des valeurs différentes pour {metabolite.name} - {plant_name} ({plant_part})"
                            )

                        if created:
                            plants_created += 1
                            logging.debug(f"Association créée : {metabolite.name} - {plant_name} ({plant_part})")

                    except Exception as row_error:
                        error_msg = (
                            f"Erreur sur la ligne : \n"
                            f"Contenu : {row}\n"
                            f"Erreur : {str(row_error)}"
                        )
                        logging.error(error_msg)
                        problematic_rows += 1

            # Affichage du résumé
            summary = (
                f"\nImport terminé !"
                f"\n- Associations plantes-métabolites créées : {plants_created}"
                f"\n- Nouvelles plantes créées : {plant_objects_created}"
                f"\n- Métabolites non trouvés : {metabolites_not_found}"
                f"\n- Lignes problématiques : {problematic_rows}"
            )
            self.stdout.write(self.style.SUCCESS(summary))
            logging.info(summary)

        except Exception as e:
            error_msg = f"Erreur lors de l'import : {str(e)}"
            self.stdout.write(self.style.ERROR(error_msg))
            logging.error(error_msg)