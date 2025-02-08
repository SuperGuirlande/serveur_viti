from django.core.management.base import BaseCommand
import pandas as pd
from metabolites.models import Metabolite

# Correction du chemin relatif depuis le dossier project/
csv_file = "ressources/datas/chemicals_ubiquitous.csv"

class Command(BaseCommand):
    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("Début de l'import..."))

        # Charge le csv avec les noms de colonnes
        df_ubi = pd.read_csv(csv_file, names=['name', 'is_ubiquitous'])

        for _, row in df_ubi.iterrows():
            metab, created = Metabolite.objects.get_or_create(name=row['name'])
            metab.is_ubiquitous = row['is_ubiquitous'] == 'Yes'  # Convertit 'Yes'/'No' en True/False
            metab.save()

        self.stdout.write(self.style.SUCCESS("Objets créés avec succès !"))

        print('Tranfert effectué')