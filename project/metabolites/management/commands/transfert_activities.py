from django.core.management.base import BaseCommand
import csv
from metabolites.models import Metabolite, MetaboliteActivity, Activity
from tqdm import tqdm
import logging
from datetime import datetime
import os

# Chemin relatif depuis le dossier project/
csv_file = "ressources/datas/all_chemicals_activities.csv"

class Command(BaseCommand):
    help = "Importe les activités des métabolites depuis le fichier CSV"

    def handle(self, *args, **options):
        # Création du dossier logs s'il n'existe pas
        logs_dir = "logs"
        if not os.path.exists(logs_dir):
            os.makedirs(logs_dir)
            
        # Configuration des logs
        log_filename = f"{logs_dir}/activities_import_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        logging.basicConfig(
            filename=log_filename,
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )

        self.stdout.write(self.style.SUCCESS("Début de l'import des activités..."))
        logging.info("Début de l'import des activités")

        try:
            activities_created = 0
            activity_types_created = 0
            metabolites_not_found = 0
            problematic_rows = 0

            # Compte le nombre total de lignes pour la barre de progression
            with open(csv_file, 'r', encoding='utf-8') as f:
                total_rows = sum(1 for _ in f) - 1  # -1 pour l'en-tête si présent

            # Lecture du fichier CSV
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.reader(f, quotechar='"', doublequote=True, delimiter=',')
                next(reader, None)  # Skip header if exists
                
                self.stdout.write(f"Nombre total d'activités à traiter : {total_rows}")

                # Utilisation de tqdm pour afficher une barre de progression
                for row in tqdm(reader, total=total_rows, desc="Traitement des activités"):
                    try:
                        # Vérification du nombre de colonnes
                        if len(row) != 4:
                            error_msg = (
                                f"Ligne ignorée - nombre incorrect de colonnes ({len(row)} au lieu de 4) : \n"
                                f"Contenu de la ligne : {row}"
                            )
                            logging.error(error_msg)
                            problematic_rows += 1
                            continue

                        name, activity_type, dosage, reference = row

                        if not name or not activity_type:
                            error_msg = f"Ligne ignorée - nom ou type d'activité manquant : {row}"
                            logging.error(error_msg)
                            problematic_rows += 1
                            continue

                        # Nettoyage des données
                        name = name.strip()
                        activity_type = activity_type.strip()
                        dosage = dosage.strip() if dosage else None
                        reference = reference.strip() if reference else None

                        # Récupère le métabolite
                        try:
                            metabolite = Metabolite.objects.get(name=name)
                        except Metabolite.DoesNotExist:
                            error_msg = f"Métabolite non trouvé : {name}"
                            logging.error(error_msg)
                            metabolites_not_found += 1
                            continue

                        # Crée ou récupère l'objet Activity
                        activity, created = Activity.objects.get_or_create(
                            name=activity_type
                        )
                        if created:
                            activity_types_created += 1
                            logging.info(f"Nouveau type d'activité créé : {activity_type}")

                        # Crée l'activité
                        _, created = MetaboliteActivity.objects.get_or_create(
                            metabolite=metabolite,
                            activity=activity,
                            dosage=dosage,
                            reference=reference
                        )
                        if created:
                            activities_created += 1
                            logging.debug(f"Activité créée pour {metabolite.name}: {activity_type}")

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
                f"\n- Activités créées : {activities_created}"
                f"\n- Types d'activités créés : {activity_types_created}"
                f"\n- Métabolites non trouvés : {metabolites_not_found}"
                f"\n- Lignes problématiques : {problematic_rows}"
            )
            self.stdout.write(self.style.SUCCESS(summary))
            logging.info(summary)

        except Exception as e:
            error_msg = f"Erreur lors de l'import : {str(e)}"
            self.stdout.write(self.style.ERROR(error_msg))
            logging.error(error_msg) 