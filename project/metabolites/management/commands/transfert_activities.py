from django.core.management.base import BaseCommand
import csv
from metabolites.models import Metabolite, MetaboliteActivity
from tqdm import tqdm

# Chemin relatif depuis le dossier project/
csv_file = "ressources/datas/all_chemicals_activities.csv"

class Command(BaseCommand):
    help = "Importe les activités des métabolites depuis le fichier CSV"

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("Début de l'import des activités..."))

        try:
            activities_created = 0
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
                            self.stdout.write(self.style.WARNING(
                                f"Ligne ignorée - nombre incorrect de colonnes : {row}"
                            ))
                            problematic_rows += 1
                            continue

                        name, activity_type, dosage, reference = row

                        if not name or not activity_type:
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
                            self.stdout.write(self.style.WARNING(
                                f"Métabolite non trouvé : {name}"
                            ))
                            metabolites_not_found += 1
                            continue

                        # Crée l'activité
                        MetaboliteActivity.objects.create(
                            metabolite=metabolite,
                            activity_type=activity_type,
                            dosage=dosage,
                            reference=reference
                        )
                        activities_created += 1

                    except Exception as row_error:
                        self.stdout.write(self.style.WARNING(
                            f"Erreur sur la ligne : {row} - {str(row_error)}"
                        ))
                        problematic_rows += 1

            # Affichage du résumé
            self.stdout.write(self.style.SUCCESS(
                f"\nImport terminé !"
                f"\n- Activités créées : {activities_created}"
                f"\n- Métabolites non trouvés : {metabolites_not_found}"
                f"\n- Lignes problématiques : {problematic_rows}"
            ))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Erreur lors de l'import : {str(e)}")) 