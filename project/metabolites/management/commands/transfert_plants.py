from django.core.management.base import BaseCommand
import csv
from metabolites.models import Metabolite, MetabolitePlant
from tqdm import tqdm
from decimal import Decimal, InvalidOperation

# Chemin relatif depuis le dossier project/
csv_file = "ressources/datas/all_chemicals_plants.csv"

class Command(BaseCommand):
    help = "Importe les données plantes-métabolites depuis le fichier CSV"

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("Début de l'import des données plantes..."))

        try:
            plants_created = 0
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

                # Utilisation de tqdm pour afficher une barre de progression
                for row in tqdm(reader, total=total_rows, desc="Traitement des données plantes"):
                    try:
                        # Vérification du nombre de colonnes
                        if len(row) != 7:
                            self.stdout.write(self.style.WARNING(
                                f"Ligne ignorée - nombre incorrect de colonnes : {row}"
                            ))
                            problematic_rows += 1
                            continue

                        chemical_name, plant_name, plant_part, low, high, deviation, reference = row

                        # Récupère le métabolite
                        try:
                            metabolite = Metabolite.objects.get(name=chemical_name.strip())
                        except Metabolite.DoesNotExist:
                            self.stdout.write(self.style.WARNING(
                                f"Métabolite non trouvé : {chemical_name}"
                            ))
                            metabolites_not_found += 1
                            continue

                        # Nettoyage et préparation des données
                        plant_part = f"{plant_name.strip()} - {plant_part.strip()}"
                        
                        # Conversion des valeurs numériques avec gestion des "not available"
                        try:
                            low = Decimal(low.strip()) if low.strip() and low.strip().lower() != "not available" else None
                            high = Decimal(high.strip()) if high.strip() and high.strip().lower() != "not available" else None
                            deviation = Decimal(deviation.strip()) if deviation.strip() and deviation.strip().lower() != "not available" else None
                        except InvalidOperation:
                            low = high = deviation = None

                        # Crée l'entrée MetabolitePlant
                        MetabolitePlant.objects.create(
                            metabolite=metabolite,
                            plant_part=plant_part,
                            low=low,
                            high=high,
                            deviation=deviation,
                            reference=reference.strip() if reference else None
                        )
                        plants_created += 1

                    except Exception as row_error:
                        self.stdout.write(self.style.WARNING(
                            f"Erreur sur la ligne : {row} - {str(row_error)}"
                        ))
                        problematic_rows += 1

            # Affichage du résumé
            self.stdout.write(self.style.SUCCESS(
                f"\nImport terminé !"
                f"\n- Données plantes créées : {plants_created}"
                f"\n- Métabolites non trouvés : {metabolites_not_found}"
                f"\n- Lignes problématiques : {problematic_rows}"
            ))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Erreur lors de l'import : {str(e)}"))