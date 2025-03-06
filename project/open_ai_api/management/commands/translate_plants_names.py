import time
import logging
import sys
import asyncio
from datetime import datetime
from openai import AsyncOpenAI
from django.core.management.base import BaseCommand
from metabolites.models import Plant
from django.conf import settings
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor
from asgiref.sync import sync_to_async

client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

BATCH_SIZE = 10  # Taille du lot pour bulk_update
MAX_CONCURRENT_REQUESTS = 5  # Réduit le nombre de requêtes parallèles
TPM_LIMIT = 30000  # Limite de tokens par minute
TPM_BUFFER = 1000  # Buffer de sécurité

class TokenBucket:
    def __init__(self, tokens_per_minute):
        self.capacity = tokens_per_minute
        self.tokens = tokens_per_minute
        self.last_update = time.time()
        self.tokens_per_second = tokens_per_minute / 60

    async def consume(self, tokens):
        now = time.time()
        time_passed = now - self.last_update
        self.tokens = min(self.capacity, self.tokens + time_passed * self.tokens_per_second)
        self.last_update = now

        if self.tokens < tokens:
            wait_time = (tokens - self.tokens) / self.tokens_per_second
            await asyncio.sleep(wait_time)
            self.tokens = tokens
            return True

        self.tokens -= tokens
        return False

class Command(BaseCommand):
    help = "Traduit les noms de plantes en français via OpenAI"

    def __init__(self):
        super().__init__()
        self.token_bucket = TokenBucket(TPM_LIMIT - TPM_BUFFER)

    def setup_logger(self):
        # Création du nom de fichier avec la date
        log_filename = f"logs/translation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        
        # Configuration du logger
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_filename, encoding='utf-8'),
            ]
        )
        return logging.getLogger(__name__)

    async def translate_plant(self, plant, safe_print, logger):
        max_retries = 5
        retry_delay = 5  # Augmenté à 5 secondes
        
        for attempt in range(max_retries):
            try:
                # Estimation des tokens nécessaires (prompt + réponse potentielle)
                estimated_tokens = len(plant.name) * 2 + 500
                
                # Attendre si nécessaire pour respecter le quota de tokens
                await self.token_bucket.consume(estimated_tokens)
                
                response = await client.chat.completions.create(
                    model="gpt-4o-mini",
                    temperature=0,
                    messages=[
                        {"role": "system", "content": f"""Tu es un traducteur expert en botanique. Règles ABSOLUES : 

1️⃣ Si tu es 100% certain du nom français officiel (source : POWO, Tela Botanica, The Plant List) :
   - Retourne uniquement ce nom

2️⃣ Si tu n'es pas 100% certain mais as des suggestions basées sur des sources fiables :
   - Retourne les suggestions entre parenthèses, séparées par des virgules
   - Format : (suggestion1, suggestion2, ...)

3️⃣ Si tu ne trouves pas de nom officiel :
   - Retourne une chaîne vide

🔴 INTERDIT :
- Inventer un nom
- Proposer des noms basés uniquement sur des ressemblances linguistiques
- Utiliser des synonymes non officiels
- Ajouter des commentaires ou explications hors parenthèses
- Renvoyer une chaine de caractère de plus de 220 caractères

📌 Exemples EXACTS de réponses acceptées :
Aloe vera → Aloès vera
Malus domestica → Pommier domestique
Acacia confusa → (Acacia confus, Petit acacia philippin)
Plante inconnue →"""},
                        {"role": "user", "content": f"Traduis ce nom de plante en français : {plant.name}"}
                    ]
                )
                translated_name = response.choices[0].message.content.strip()

                # Ajout de logging détaillé
                logger.debug(f"Réponse brute de l'API pour {plant.name}: '{translated_name}'")

                # Vérifie si c'est une suggestion (entre parenthèses) ou une traduction certaine
                is_suggestion = translated_name.startswith('(') and translated_name.endswith(')')

                if translated_name:
                    if is_suggestion:
                        safe_print(f"? {plant.name:<40} → {translated_name}")
                        logger.info(f"Suggestions de traduction : {plant.name} → {translated_name}")
                        self.error_count += 1  # On compte comme une "erreur" car pas 100% sûr
                    else:
                        safe_print(f"+ {plant.name:<40} → {translated_name}")
                        logger.info(f"Nouvelle traduction : {plant.name} → {translated_name}")
                        self.success_count += 1
                    
                    plant.french_name = translated_name
                    return plant
                else:
                    safe_print(f"- {plant.name:<40} → Non trouvé")
                    logger.warning(f"Traduction non trouvée : {plant.name}")
                    self.error_count += 1
                    return None

            except Exception as e:
                if "rate_limit" in str(e).lower():
                    if attempt < max_retries - 1:
                        wait_time = retry_delay * (3 ** attempt)  # backoff plus agressif (3 au lieu de 2)
                        safe_print(f"Rate limit atteint, attente de {wait_time}s avant réessai ({attempt + 1}/{max_retries})...")
                        await asyncio.sleep(wait_time)
                        continue
                
                error_message = f"❌ Erreur sur {plant.name} : {str(e)}"
                safe_print(error_message)
                logger.error(error_message)
                self.error_count += 1
                await asyncio.sleep(1)  # Délai doublé entre les requêtes
                return None

            # Si on arrive ici, la requête a réussi
            break

    @staticmethod
    async def save_plants_batch(plants_to_update):
        """Sauvegarde un lot de plantes en utilisant bulk_update"""
        if plants_to_update:
            await sync_to_async(Plant.objects.bulk_update)(plants_to_update, ['french_name'])

    async def handle_async(self, *args, **kwargs):
        # Initialisation des compteurs
        self.success_count = 0
        self.error_count = 0
        self.skipped_count = 0
        
        # Setup du logger
        logger = self.setup_logger()
        logger.info("Démarrage de la traduction des plantes")

        self.stdout.write(self.style.SUCCESS("\n🌿 TRADUCTION DES NOMS DES PLANTES"))

        plants_count = input("\nCombien de plantes voulez-vous traduire ? (0 pour toutes) : ")
        plants_count = int(plants_count)

        # Récupération des plantes de manière asynchrone
        if plants_count == 0:
            plants = await sync_to_async(list)(Plant.objects.filter().order_by('name'))
        else:
            plants = await sync_to_async(list)(Plant.objects.filter().order_by('name')[:plants_count])

        already_translated = sum(1 for plant in plants if plant.french_name)
        to_translate = len(plants) - already_translated

        stats_message = f"""
📊 Statistiques :
   • Total : {len(plants)} plantes
   • Déjà traduites : {already_translated} plantes
   • À traduire : {to_translate} plantes
"""
        self.stdout.write(self.style.SUCCESS(stats_message))
        logger.info(stats_message)

        print("\n")  # Ajoute de l'espace avant de commencer
        
        # Configuration de la barre de progression
        pbar = tqdm(total=len(plants), 
                   desc="🔄 Traduction", 
                   bar_format='{desc} |{bar:30}| {percentage:3.0f}% [{n_fmt}/{total_fmt}]',
                   colour='green',
                   position=0,
                   leave=True,
                   file=sys.stdout,
                   dynamic_ncols=True)

        # Fonction pour afficher les messages au-dessus de la barre
        def safe_print(message):
            # Efface la ligne de la barre de progression
            sys.stdout.write('\033[1A\033[K')
            # Affiche le message
            print(message)
            # Réaffiche la barre de progression
            pbar.refresh()

        plants_to_update = []
        tasks = []

        for plant in plants:
            if plant.french_name:
                safe_print(f"✓ {plant.name:<40} → {plant.french_name}")
                logger.info(f"Déjà traduit : {plant.name} → {plant.french_name}")
                self.skipped_count += 1
                pbar.update(1)
            else:
                tasks.append(self.translate_plant(plant, safe_print, logger))
                
                # Traitement par lots quand on atteint MAX_CONCURRENT_REQUESTS
                if len(tasks) >= MAX_CONCURRENT_REQUESTS:
                    # Exécute les traductions en parallèle
                    completed_plants = await asyncio.gather(*tasks)
                    
                    # Filtre les None (erreurs) et ajoute au lot
                    plants_to_update.extend([p for p in completed_plants if p])
                    
                    # Si le lot est assez grand, sauvegarde
                    if len(plants_to_update) >= BATCH_SIZE:
                        await self.save_plants_batch(plants_to_update)
                        plants_to_update = []
                    
                    tasks = []
                    pbar.update(MAX_CONCURRENT_REQUESTS)

        # Traite les plantes restantes
        if tasks:
            completed_plants = await asyncio.gather(*tasks)
            plants_to_update.extend([p for p in completed_plants if p])
            pbar.update(len(tasks))

        # Sauvegarde le dernier lot
        if plants_to_update:
            await self.save_plants_batch(plants_to_update)

        # Affichage du récapitulatif final
        final_stats = f"""
✨ Récapitulatif de la traduction :
   • Plantes déjà traduites : {self.skipped_count}
   • Nouvelles traductions : {self.success_count}
   • Échecs : {self.error_count}
   • Total traité : {self.skipped_count + self.success_count + self.error_count}
"""
        print("\n")  # Ajoute de l'espace après la barre de progression
        self.stdout.write(self.style.SUCCESS(final_stats))
        logger.info("Fin de la traduction" + final_stats)

    def handle(self, *args, **kwargs):
        asyncio.run(self.handle_async(*args, **kwargs))
