from django.core.management.base import BaseCommand
import pandas as pd
from metabolites.models import Metabolite
from tqdm import tqdm
import logging
from datetime import datetime
import os

csv_file = "ressources/datas/chemicals_ubiquitous.csv"

class Command(BaseCommand):
    help = "Importe les données d'ubiquité des métabolites depuis le fichier CSV"

    def handle(self, *args, **options):
        # Création du dossier logs s'il n'existe pas
        logs_dir = "logs"
        if not os.path.exists(logs_dir):
            os.makedirs(logs_dir)
            
        # Configuration des logs
        log_filename = f"{logs_dir}/ubiquitous_import_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        logging.basicConfig(
            filename=log_filename,
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )

        self.stdout.write(self.style.SUCCESS("Début de l'import des données d'ubiquité..."))
        logging.info("Début de l'import des données d'ubiquité")

        try:
            updates_count = 0
            created_count = 0
            problematic_rows = 0

            # Charge le csv
            try:
                df_ubi = pd.read_csv(csv_file, names=['name', 'is_ubiquitous'])
                total_rows = len(df_ubi)
                
                # Nettoie les données
                df_ubi['name'] = df_ubi['name'].str.strip()
                df_ubi['is_ubiquitous'] = df_ubi['is_ubiquitous'].str.strip()
                
                # Convertit 'No'/'Yes' en False/True et gère les NaN
                df_ubi['is_ubiquitous'] = df_ubi['is_ubiquitous'].map({
                    'No': False, 
                    'Yes': True
                })
                df_ubi['is_ubiquitous'] = df_ubi['is_ubiquitous'].fillna(False)
                df_ubi = df_ubi.infer_objects(copy=False)  # Approche recommandée pour les versions futures
                
                self.stdout.write(f"Nombre total de données à traiter : {total_rows}")
                logging.info(f"Nombre total de données à traiter : {total_rows}")

                # Traitement des données avec barre de progression
                for _, row in tqdm(df_ubi.iterrows(), total=total_rows, desc="Traitement des données d'ubiquité"):
                    try:
                        metab, created = Metabolite.objects.get_or_create(
                            name=row['name']
                        )
                        
                        if created:
                            created_count += 1
                            logging.info(f"Création - Métabolite: {metab.name} (is_ubiquitous: {row['is_ubiquitous']})")
                        else:
                            updates_count += 1
                            logging.info(
                                f"Mise à jour - Métabolite: {metab.name} "
                                f"(ancien is_ubiquitous: {metab.is_ubiquitous}, "
                                f"nouveau is_ubiquitous: {row['is_ubiquitous']})"
                            )
                        
                        metab.is_ubiquitous = row['is_ubiquitous']
                        metab.save()

                    except Exception as row_error:
                        error_msg = f"Erreur sur la ligne : {row.to_dict()} - {str(row_error)}"
                        self.stdout.write(self.style.WARNING(error_msg))
                        logging.error(error_msg)
                        problematic_rows += 1

                # Affichage du résumé
                summary = (
                    f"\nImport terminé !"
                    f"\n- Métabolites créés : {created_count}"
                    f"\n- Métabolites mis à jour : {updates_count}"
                    f"\n- Lignes problématiques : {problematic_rows}"
                )
                self.stdout.write(self.style.SUCCESS(summary))
                logging.info(summary)

            except pd.errors.EmptyDataError:
                error_msg = "Le fichier CSV est vide"
                self.stdout.write(self.style.ERROR(error_msg))
                logging.error(error_msg)
            except Exception as e:
                error_msg = f"Erreur lors de la lecture du CSV : {str(e)}"
                self.stdout.write(self.style.ERROR(error_msg))
                logging.error(error_msg)

        except Exception as e:
            error_msg = f"Erreur lors de l'import : {str(e)}"
            self.stdout.write(self.style.ERROR(error_msg))
            logging.error(error_msg)

        print('Tranfert effectué')