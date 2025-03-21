from django.db import models
from django.db import connection
from django.utils.functional import cached_property
from django.core.cache import cache
import logging
from .utils import log_execution_time
import math

logger = logging.getLogger('metabolites')

class Metabolite(models.Model):
    name = models.CharField(max_length=255, unique=True, db_index=True)
    is_ubiquitous = models.BooleanField(default=False)

    @cached_property
    def get_unique_activities_count(self):
        """Version optimisée et mise en cache"""
        return self.activities.count()
    
    @cached_property
    def get_unique_plants_count(self):
        """Version optimisée et mise en cache"""
        return self.plants.values('plant_name').distinct().count()
    
    def get_plants_with_parts(self, sort_field=None, sort_direction=None):
        """Version optimisée avec SQL brut et tri dynamique"""
        # Définir l'ordre par défaut
        order_by = "mp.plant_name, mp.plant_part"
        
        # Construire la clause ORDER BY en fonction des paramètres de tri
        if sort_field and sort_direction:
            direction = "ASC" if sort_direction == "asc" else "DESC"
            if sort_field == "plant_name":
                order_by = f"mp.plant_name {direction}, mp.plant_part"
            elif sort_field == "plant_part":
                order_by = f"mp.plant_part {direction}, mp.plant_name"
            elif sort_field in ["low", "high", "deviation"]:
                # Pour les champs numériques, gérer les valeurs NULL
                order_by = f"""
                    CASE 
                        WHEN mp.{sort_field} IS NULL THEN 1 
                        ELSE 0 
                    END,
                    COALESCE(mp.{sort_field}, 0) {direction},
                    mp.plant_name
                """
            elif sort_field == "reference":
                order_by = f"mp.reference {direction}, mp.plant_name"

        with connection.cursor() as cursor:
            cursor.execute(f"""
                SELECT 
                    mp.plant_name,
                    mp.plant_part,
                    mp.low,
                    mp.high,
                    mp.deviation,
                    mp.reference,
                    p.id as plant_id
                FROM metabolites_metaboliteplant mp
                JOIN metabolites_plant p ON p.name = mp.plant_name
                WHERE mp.metabolite_id = %s
                ORDER BY {order_by}
            """, [self.id])
            
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
    
    def get_activities_with_details(self):
        """Version optimisée avec values() et select_related"""
        return (
            self.activities.select_related('activity')
            .values(
                'activity__name',
                'dosage',
                'reference'
            )
            .distinct()
            .order_by('activity__name')  # Ajout d'un ordre explicite
        )

    def __str__(self):
        return self.name
    
    def get_activities_by_plant(self):
        """Version optimisée avec SQL brut"""
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT 
                    mp.plant_name,
                    GROUP_CONCAT(DISTINCT a.name ORDER BY a.name) as activities
                FROM metabolites_metaboliteplant mp
                JOIN metabolites_metaboliteactivity ma ON ma.metabolite_id = %s
                JOIN metabolites_activity a ON a.id = ma.activity_id
                WHERE mp.metabolite_id = %s
                GROUP BY mp.plant_name
                ORDER BY mp.plant_name
            """, [self.id, self.id])
            
            return [
                {'plant_name': row[0], 'activities': row[1].split(',')}
                for row in cursor.fetchall()
            ]
    
    def get_plants_by_activity(self):
        """Version optimisée avec SQL brut"""
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT 
                    a.name as activity_name,
                    GROUP_CONCAT(DISTINCT mp.plant_name ORDER BY mp.plant_name) as plants
                FROM metabolites_activity a
                JOIN metabolites_metaboliteactivity ma ON ma.activity_id = a.id
                JOIN metabolites_metaboliteplant mp ON mp.metabolite_id = ma.metabolite_id
                WHERE ma.metabolite_id = %s
                GROUP BY a.name
                ORDER BY a.name
            """, [self.id])
            
            return [
                {'activity_name': row[0], 'plants': row[1].split(',')}
                for row in cursor.fetchall()
            ]

    @classmethod
    def get_global_matrix(cls):
        """Version optimisée avec SQL brut"""
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT 
                    m.name,
                    m.is_ubiquitous,
                    COUNT(DISTINCT mp.plant_name) as plant_count,
                    COUNT(DISTINCT ma.activity_id) as activity_count
                FROM metabolites_metabolite m
                LEFT JOIN metabolites_metaboliteplant mp ON mp.metabolite_id = m.id
                LEFT JOIN metabolites_metaboliteactivity ma ON ma.metabolite_id = m.id
                GROUP BY m.id, m.name, m.is_ubiquitous
                ORDER BY m.name
            """)
            
            columns = ['name', 'is_ubiquitous', 'plant_count', 'activity_count']
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    class Meta:
        indexes = [
            models.Index(fields=['name']),
            models.Index(fields=['is_ubiquitous']),
        ]

class Activity(models.Model):
    name = models.CharField(max_length=255, unique=True, db_index=True)

    def __str__(self):
        return self.name
    
    def get_plants_by_total_concentration(self, page=1, per_page=50, sort_params=None, search=''):
        with connection.cursor() as cursor:
            # Construction de la clause WHERE pour la recherche
            where_clause = "WHERE ma.activity_id = %s"
            params = [self.id]
            
            if search:
                where_clause += " AND p.name LIKE %s"
                params.append(f"%{search}%")

            # Construction de la clause ORDER BY
            order_by = ""
            if sort_params:
                order_clauses = []
                for field, direction in sort_params:
                    if field == 'name':
                        order_clauses.append(f"name {direction}")
                    elif field == 'total_concentration':
                        order_clauses.append(f"total_concentration {direction}")
                    elif field == 'metabolites_count':
                        order_clauses.append(f"metabolites_count {direction}")
                if order_clauses:
                    order_by = "ORDER BY " + ", ".join(order_clauses)
            else:
                order_by = "ORDER BY name ASC"

            # Requête pour obtenir le compte total
            count_query = f"""
                SELECT COUNT(DISTINCT p.id)
                FROM 
                    metabolites_plant p
                    JOIN metabolites_metaboliteplant mp ON mp.plant_name = p.name
                    JOIN metabolites_metabolite m ON m.id = mp.metabolite_id
                    JOIN metabolites_metaboliteactivity ma ON ma.metabolite_id = m.id
                {where_clause}
            """
            cursor.execute(count_query, params[:2] if search else params[:1])
            total_count = cursor.fetchone()[0]

            # Requête principale
            query = f"""
                WITH plant_concentrations AS (
                    SELECT 
                        p.id,
                        p.name,
                        COUNT(DISTINCT mp.metabolite_id) as metabolites_count,
                        COALESCE(SUM(
                            CASE 
                                WHEN mp.high IS NOT NULL THEN mp.high
                                WHEN mp.low IS NOT NULL THEN mp.low
                                ELSE NULL 
                            END
                        ), 0) as total_concentration,
                        GROUP_CONCAT(
                            CONCAT_WS(':', 
                                m.name,
                                COALESCE(mp.plant_part, 'non spécifié'),
                                CAST(COALESCE(
                                    CASE 
                                        WHEN mp.high IS NOT NULL THEN mp.high
                                        WHEN mp.low IS NOT NULL THEN mp.low
                                        ELSE NULL 
                                    END, 
                                    'NULL'
                                ) AS CHAR)
                            ) SEPARATOR '|'
                        ) as metabolites_details
                    FROM 
                        metabolites_plant p
                        JOIN metabolites_metaboliteplant mp ON mp.plant_name = p.name
                        JOIN metabolites_metabolite m ON m.id = mp.metabolite_id
                        JOIN metabolites_metaboliteactivity ma ON ma.metabolite_id = m.id
                    {where_clause}
                    GROUP BY p.id, p.name
                )
                SELECT 
                    id,
                    name,
                    metabolites_count,
                    total_concentration,
                    metabolites_details
                FROM plant_concentrations
                {order_by}
                LIMIT %s OFFSET %s
            """
            
            # Ajout des paramètres de pagination
            params_main = params.copy()
            params_main.extend([per_page, (page - 1) * per_page])
            
            cursor.execute(query, params_main)
            results = []
            
            # Traitement des résultats
            for row in cursor.fetchall():
                result = {
                    'id': row[0],
                    'name': row[1],
                    'metabolites_count': row[2],
                    'total_concentration': float(row[3]) if row[3] is not None else 0.0,
                    'has_unknown_concentration': row[3] is None or row[3] == 0
                }
                
                # Traitement des détails des métabolites
                if row[4]:  # metabolites_details
                    metabolites = {}
                    for detail in row[4].split('|'):
                        try:
                            parts = detail.split(':')
                            if len(parts) == 3:
                                metabolite, part, concentration = parts
                                if metabolite not in metabolites:
                                    metabolites[metabolite] = []
                                if concentration == 'NULL' or not concentration:
                                    concentration_text = 'inconnu'
                                else:
                                    try:
                                        concentration_text = f"{float(concentration):.1f}"
                                    except ValueError:
                                        concentration_text = 'inconnu'
                                metabolites[metabolite].append(f"{part}: {concentration_text}")
                        except Exception:
                            continue
                    
                    result['metabolites_details'] = [
                        {'name': name, 'parts': parts}
                        for name, parts in metabolites.items()
                    ]
                
                results.append(result)
            
            return {
                'results': results,
                'total_count': total_count,
                'page': page,
                'per_page': per_page,
                'total_pages': (total_count + per_page - 1) // per_page
            }

class Plant(models.Model):
    name = models.CharField(max_length=200, db_index=True)
    french_name = models.CharField(max_length=255, null=True, blank=True)

    def __str__(self):
        return self.name
    
    @cached_property
    def all_metabolites_count(self):
        """Optimisation avec SQL brut"""
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT COUNT(*)
                FROM metabolites_metaboliteplant
                WHERE plant_name = %s
            """, [self.name])
            return cursor.fetchone()[0]
    
    @cached_property
    def get_unique_metabolites_count(self):
        """Optimisation avec une requête SQL directe"""
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT COUNT(DISTINCT metabolite_id) 
                FROM metabolites_metaboliteplant 
                WHERE plant_name = %s
            """, [self.name])
            return cursor.fetchone()[0]
    
    @log_execution_time
    def get_metabolites_with_parts(self):
        logger.info(f"Récupération des métabolites pour {self.name}")
        cache_key = f'plant_metabolites_{self.id}'
        result = cache.get(cache_key)
        if result is None:
            logger.debug("Cache miss - Exécution de la requête SQL")
            result = self._get_metabolites_with_parts_sql()
            cache.set(cache_key, result, 3600)
        else:
            logger.debug("Cache hit - Utilisation des données en cache")
        return result

    def get_common_plants(self, activity_filter=None, page=1, per_page=50, sort_params=None, exclude_ubiquitous=False, search_text='', search_type='contains', metabolite_filters=None):
        """Version optimisée avec matérialisation des CTE et index"""
        logger.info(f"Début get_common_plants pour la plante {self.name}")
        offset = (page - 1) * per_page
        
        # Construction de l'ordre SQL en fonction des paramètres de tri
        order_by = []
        if sort_params:
            logger.info(f"Paramètres de tri reçus: {sort_params}")
            for field, direction in sort_params:
                if field == 'name':
                    order_by.append(f"p.name {direction}")
                elif field == 'common_metabolites':
                    order_by.append(f"common_metabolites_count {direction}")
                elif field == 'common_percentage':
                    order_by.append(f"CASE WHEN reference_count >= metabolites_total THEN (common_metabolites_count * 100.0 / NULLIF(metabolites_total, 0)) ELSE (common_metabolites_count * 100.0 / NULLIF(reference_count, 0)) END {direction}")
                elif field == 'meta_percentage_score':
                    order_by.append(f"(common_metabolites_count * (common_metabolites_count * 100.0 / NULLIF(metabolites_total, 0)) / 100) {direction}")
                elif field == 'meta_root_score':
                    order_by.append(f"(SQRT(common_metabolites_count) * (common_metabolites_count * 100.0 / NULLIF(metabolites_total, 0)) / 100) {direction}")
                elif field == 'common_activity_metabolites' and activity_filter:
                    order_by.append(f"common_activity_metabolites_count {direction}")
                elif field == 'total_activity_metabolites' and activity_filter:
                    order_by.append(f"total_activity_metabolites_count {direction}")
                elif field == 'total_concentration' and activity_filter:
                    order_by.append(f"total_concentration {direction}")
        
        # Ordre par défaut si aucun tri n'est spécifié
        if not order_by:
            if activity_filter:
                order_by = ["common_activity_metabolites_count DESC", "common_metabolites_count DESC"]
            else:
                order_by = ["common_metabolites_count DESC"]
        
        order_by_clause = f"ORDER BY {', '.join(order_by)}"
        logger.info(f"Clause ORDER BY finale: {order_by_clause}")
        
        with connection.cursor() as cursor:
            # Récupérer d'abord le nombre de métabolites de la plante de référence
            query_ref = """
                SELECT COUNT(DISTINCT mp.metabolite_id)
                FROM metabolites_metaboliteplant mp
                JOIN metabolites_metabolite m ON m.id = mp.metabolite_id
                WHERE mp.plant_name = %s
            """
            
            if exclude_ubiquitous:
                query_ref += " AND m.is_ubiquitous = FALSE"
                
            cursor.execute(query_ref, [self.name])
            reference_count = cursor.fetchone()[0]
            logger.info(f"Nombre de métabolites de la plante de référence ({self.name}): {reference_count}")

            # Nettoyer les tables temporaires qui pourraient exister
            cursor.execute("DROP TEMPORARY TABLE IF EXISTS temp_reference_metabolites")
            cursor.execute("DROP TEMPORARY TABLE IF EXISTS temp_activity_metabolites")
            cursor.execute("DROP TEMPORARY TABLE IF EXISTS temp_plant_counts")
            cursor.execute("DROP TEMPORARY TABLE IF EXISTS temp_common_counts")
            cursor.execute("DROP TEMPORARY TABLE IF EXISTS temp_activity_counts")
            
            for i in range(3):  # Pour les 3 filtres possibles de métabolites
                cursor.execute(f"DROP TEMPORARY TABLE IF EXISTS temp_filtered_plants_{i}")

            if activity_filter:
                # Créer la table temporaire des métabolites de référence
                query_temp_ref = """
                    CREATE TEMPORARY TABLE temp_reference_metabolites AS
                    SELECT DISTINCT mp.metabolite_id
                    FROM metabolites_metaboliteplant mp
                    JOIN metabolites_metabolite m ON m.id = mp.metabolite_id
                    WHERE mp.plant_name = %s
                """
                
                if exclude_ubiquitous:
                    query_temp_ref += " AND m.is_ubiquitous = FALSE"
                
                cursor.execute(query_temp_ref, [self.name])
                # Ajouter un index sur la table temporaire
                cursor.execute("CREATE INDEX idx_temp_reference_metabolites ON temp_reference_metabolites(metabolite_id)")

                # Récupérer l'ID de l'activité
                query_activity_id = """
                    SELECT id FROM metabolites_activity WHERE name = %s
                """
                cursor.execute(query_activity_id, [activity_filter])
                activity_id = cursor.fetchone()[0]

                # Pré-filtrer les métabolites avec l'activité demandée
                cursor.execute("""
                    CREATE TEMPORARY TABLE temp_activity_metabolites AS
                    SELECT DISTINCT metabolite_id 
                    FROM metabolites_metaboliteactivity 
                    WHERE activity_id = %s
                """, [activity_id])
                cursor.execute("CREATE INDEX idx_temp_activity_metabolites ON temp_activity_metabolites(metabolite_id)")

                # Ajouter les filtres de métabolites si présents
                if metabolite_filters and any(metabolite_filters):
                    for i, metabolite_id in enumerate(metabolite_filters):
                        if metabolite_id:
                            cursor.execute(f"""
                                CREATE TEMPORARY TABLE temp_filtered_plants_{i} AS
                                SELECT DISTINCT plant_name
                                FROM metabolites_metaboliteplant
                                WHERE metabolite_id = %s
                            """, [metabolite_id])
                            cursor.execute(f"CREATE INDEX idx_temp_filtered_plants_{i} ON temp_filtered_plants_{i}(plant_name)")

                # Requête principale pour les plantes avec des métabolites en commun et l'activité spécifiée
                query = f"""
                    WITH plant_counts AS (
                        SELECT 
                            p.name,
                            COUNT(DISTINCT mp.metabolite_id) as metabolites_total
                        FROM metabolites_plant p
                        JOIN metabolites_metaboliteplant mp ON mp.plant_name = p.name
                        JOIN metabolites_metabolite m ON m.id = mp.metabolite_id
                        WHERE 1=1
                """
                
                if exclude_ubiquitous:
                    query += " AND m.is_ubiquitous = FALSE"
                
                query += f"""
                        GROUP BY p.name
                    )
                    SELECT 
                        p.id,
                        p.name,
                        p.french_name,
                        COUNT(DISTINCT CASE WHEN rm.metabolite_id IS NOT NULL THEN mp.metabolite_id END) as common_metabolites_count,
                        COUNT(DISTINCT CASE WHEN tam.metabolite_id IS NOT NULL THEN mp.metabolite_id END) as total_activity_metabolites_count,
                        COUNT(DISTINCT CASE WHEN rm.metabolite_id IS NOT NULL AND tam.metabolite_id IS NOT NULL THEN mp.metabolite_id END) as common_activity_metabolites_count,
                        COALESCE(SUM(CASE 
                            WHEN tam.metabolite_id IS NOT NULL 
                            THEN COALESCE(mp.high, mp.low, 0) 
                        END), 0) as total_concentration,
                        pc.metabolites_total,
                        COUNT(*) OVER() as pagination_total,
                        {reference_count} as reference_count
                    FROM metabolites_plant p
                    JOIN metabolites_metaboliteplant mp ON mp.plant_name = p.name
                    LEFT JOIN temp_reference_metabolites rm ON rm.metabolite_id = mp.metabolite_id
                    LEFT JOIN temp_activity_metabolites tam ON tam.metabolite_id = mp.metabolite_id
                    JOIN plant_counts pc ON pc.name = p.name
                    WHERE p.name != %s AND pc.metabolites_total > 1
                """
                
                params = [self.name]

                # Ajouter les filtres de métabolites si présents
                if metabolite_filters and any(metabolite_filters):
                    for i, metabolite_id in enumerate(metabolite_filters):
                        if metabolite_id:
                            query += f" AND p.name IN (SELECT plant_name FROM temp_filtered_plants_{i})"

                # Ajouter la condition de recherche
                if search_text:
                    if search_type == 'contains':
                        query += " AND LOWER(p.name) LIKE LOWER(%s)"
                        params.append(f"%{search_text}%")
                    else:  # starts_with
                        query += " AND LOWER(p.name) LIKE LOWER(%s)"
                        params.append(f"{search_text}%")
                
                query += " GROUP BY p.id, p.name, p.french_name, pc.metabolites_total"
                query += " HAVING COUNT(DISTINCT CASE WHEN tam.metabolite_id IS NOT NULL THEN mp.metabolite_id END) > 0"  # Filtrer par activité
                query += f" {order_by_clause}"
                query += " LIMIT %s OFFSET %s"
                
                params.extend([per_page, offset])
                
                try:
                    cursor.execute(query, params)
                    columns = [col[0] for col in cursor.description]
                    results = [dict(zip(columns, row)) for row in cursor.fetchall()]
                    logger.info(f"Nombre de résultats obtenus: {len(results)}")
                except Exception as e:
                    logger.error(f"Erreur SQL: {e}")
                    logger.error(f"Requête: {query}")
                    logger.error(f"Paramètres: {params}")
                    results = []

            else:
                # Version sans activité avec tri dynamique
                query_temp_ref = """
                    CREATE TEMPORARY TABLE temp_reference_metabolites AS
                    SELECT DISTINCT mp.metabolite_id
                    FROM metabolites_metaboliteplant mp
                    JOIN metabolites_metabolite m ON m.id = mp.metabolite_id
                    WHERE mp.plant_name = %s
                """
                
                if exclude_ubiquitous:
                    query_temp_ref += " AND m.is_ubiquitous = FALSE"
                
                cursor.execute(query_temp_ref, [self.name])
                cursor.execute("CREATE INDEX idx_temp_reference_metabolites ON temp_reference_metabolites(metabolite_id)")

                # Ajouter les filtres de métabolites si présents
                if metabolite_filters and any(metabolite_filters):
                    for i, metabolite_id in enumerate(metabolite_filters):
                        if metabolite_id:
                            cursor.execute(f"""
                                CREATE TEMPORARY TABLE temp_filtered_plants_{i} AS
                                SELECT DISTINCT plant_name
                                FROM metabolites_metaboliteplant
                                WHERE metabolite_id = %s
                            """, [metabolite_id])
                            cursor.execute(f"CREATE INDEX idx_temp_filtered_plants_{i} ON temp_filtered_plants_{i}(plant_name)")

                query = f"""
                    WITH plant_counts AS (
                        SELECT plant_name, COUNT(DISTINCT mp.metabolite_id) as metabolites_total
                        FROM metabolites_metaboliteplant mp
                        JOIN metabolites_metabolite m ON m.id = mp.metabolite_id
                        WHERE 1=1
                """
                
                if exclude_ubiquitous:
                    query += " AND m.is_ubiquitous = FALSE"
                
                query += f"""
                        GROUP BY plant_name
                    )
                    SELECT 
                        p.id,
                        p.name,
                        p.french_name,
                        COUNT(DISTINCT mp2.metabolite_id) as common_metabolites_count,
                        pc.metabolites_total,
                        COUNT(*) OVER() as pagination_total,
                        {reference_count} as reference_count
                    FROM metabolites_plant p
                    JOIN metabolites_metaboliteplant mp2 ON mp2.plant_name = p.name
                    JOIN temp_reference_metabolites rm ON rm.metabolite_id = mp2.metabolite_id
                    JOIN plant_counts pc ON pc.plant_name = p.name
                    WHERE p.name != %s AND pc.metabolites_total > 1
                """

                params = [self.name]

                # Ajouter les filtres de métabolites si présents
                if metabolite_filters and any(metabolite_filters):
                    for i, metabolite_id in enumerate(metabolite_filters):
                        if metabolite_id:
                            query += f" AND p.name IN (SELECT plant_name FROM temp_filtered_plants_{i})"

                # Ajouter la condition de recherche
                if search_text:
                    if search_type == 'contains':
                        query += " AND LOWER(p.name) LIKE LOWER(%s)"
                        params.append(f"%{search_text}%")
                    else:  # starts_with
                        query += " AND LOWER(p.name) LIKE LOWER(%s)"
                        params.append(f"{search_text}%")
                
                query += " GROUP BY p.id, p.name, p.french_name, pc.metabolites_total"
                query += " HAVING COUNT(DISTINCT mp2.metabolite_id) > 0"
                query += f" {order_by_clause}"
                query += " LIMIT %s OFFSET %s"
                
                params.extend([per_page, offset])
                
                cursor.execute(query, params)
                columns = [col[0] for col in cursor.description]
                results = [dict(zip(columns, row)) for row in cursor.fetchall()]
                logger.info(f"Nombre de résultats obtenus: {len(results)}")

            # Nettoyer les tables temporaires
            cursor.execute("DROP TEMPORARY TABLE IF EXISTS temp_reference_metabolites")
            cursor.execute("DROP TEMPORARY TABLE IF EXISTS temp_activity_metabolites")
            
            if metabolite_filters and any(metabolite_filters):
                for i in range(len(metabolite_filters)):
                    if i < 3:  # Maximum 3 filtres
                        cursor.execute(f"DROP TEMPORARY TABLE IF EXISTS temp_filtered_plants_{i}")
            
            # Calculer les pourcentages et scores
            for result in results:
                common_count = result['common_metabolites_count']
                plant_total = result['metabolites_total']
                
                # Déterminer quel calcul utiliser
                percentage = (common_count * 100.0) / plant_total if plant_total > 0 else 0
                
                # Conserver la distinction visuelle entre les cas
                if reference_count >= plant_total:
                    result['percentage_type'] = 'blue'
                else:
                    result['percentage_type'] = 'green'
                
                result['common_metabolites_percentage'] = round(percentage, 1)
                
                # Calcul des scores
                result['meta_percentage_score'] = round(common_count * (percentage / 100), 2)
                result['meta_root_score'] = round(math.sqrt(common_count) * (percentage / 100), 2) if common_count > 0 else 0
            
            # Récupérer le total_count pour la pagination
            total_count = results[0]['pagination_total'] if results else 0
            
            return {
                'results': results,
                'total_count': total_count,
                'page': page,
                'per_page': per_page,
                'total_pages': (total_count + per_page - 1) // per_page
            }

    def _sort_cached_results(self, results, order_criteria):
        """Trie les résultats en cache selon les critères spécifiés"""
        if not results or not order_criteria:
            return results
            
        # Créer une fonction de tri en fonction des critères
        def sort_key(item):
            values = []
            for criterion in order_criteria:
                parts = criterion.split()
                field = parts[0]
                direction = parts[-1]
                
                # Extraire la valeur en fonction du champ
                if field == "p.name":
                    value = item['name']
                elif field == "common_metabolites_count":
                    value = item['common_metabolites_count']
                elif "common_percentage" in field:
                    # Calculer le pourcentage
                    common = item['common_metabolites_count']
                    total = item['metabolites_total']
                    ref = item['reference_count']
                    if ref >= total:
                        value = (common * 100.0) / total if total > 0 else 0
                    else:
                        value = (common * 100.0) / ref if ref > 0 else 0
                elif "meta_percentage_score" in field:
                    common = item['common_metabolites_count']
                    total = item['metabolites_total']
                    percentage = (common * 100.0) / total if total > 0 else 0
                    value = common * (percentage / 100)
                elif "meta_root_score" in field:
                    common = item['common_metabolites_count']
                    total = item['metabolites_total']
                    percentage = (common * 100.0) / total if total > 0 else 0
                    value = math.sqrt(common) * (percentage / 100) if common > 0 else 0
                elif field == "common_activity_metabolites_count":
                    value = item.get('common_activity_metabolites_count', 0)
                elif field == "total_activity_metabolites_count":
                    value = item.get('total_activity_metabolites_count', 0)
                elif field == "total_concentration":
                    value = item.get('total_concentration', 0)
                else:
                    value = 0
                
                # Inverser pour le tri DESC
                if direction == "DESC":
                    if isinstance(value, (int, float)):
                        value = -value
                    elif isinstance(value, str):
                        value = value[::-1]  # Inversion de chaîne
                
                values.append(value)
            
            return values
        
        # Trier les résultats
        return sorted(results, key=sort_key)

    def get_metabolites_by_activity(self, activity_name):
        """Optimisation avec index et SQL brut"""
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT COUNT(DISTINCT mp.metabolite_id)
                FROM metabolites_metaboliteplant mp
                JOIN metabolites_metaboliteactivity ma 
                    ON ma.metabolite_id = mp.metabolite_id
                JOIN metabolites_activity a 
                    ON a.id = ma.activity_id
                WHERE mp.plant_name = %s
                    AND a.name = %s
            """, [self.name, activity_name])
            return cursor.fetchone()[0]
            
    def _get_metabolites_with_parts_sql(self):
        """Méthode SQL brute pour récupérer les métabolites avec leurs parties"""
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT 
                    mp.metabolite_id,
                    m.name as metabolite__name,
                    mp.plant_part,
                    mp.low,
                    mp.high,
                    mp.deviation,
                    mp.reference,
                    m.is_ubiquitous as metabolite__is_ubiquitous
                FROM metabolites_metaboliteplant mp
                JOIN metabolites_metabolite m ON m.id = mp.metabolite_id
                WHERE mp.plant_name = %s
                ORDER BY m.name, mp.plant_part
            """, [self.name])
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

class MetaboliteActivity(models.Model):
    metabolite = models.ForeignKey(Metabolite, related_name='activities', on_delete=models.CASCADE)
    activity = models.ForeignKey(Activity, on_delete=models.CASCADE)
    dosage = models.CharField(max_length=255, null=True, blank=True)
    reference = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        unique_together = ['metabolite', 'activity', 'dosage', 'reference']
        indexes = [
            models.Index(fields=['metabolite_id', 'activity_id']),
            models.Index(fields=['activity_id']),
        ]

    def __str__(self):
        return f"{self.metabolite.name} - {self.activity.name}"
    

class MetabolitePlant(models.Model):
    metabolite = models.ForeignKey(Metabolite, related_name='plants', on_delete=models.CASCADE)
    plant_name = models.CharField(max_length=255, db_index=True)
    plant_part = models.CharField(max_length=255)
    low = models.DecimalField(max_digits=10, decimal_places=1, blank=True, null=True)
    high = models.DecimalField(max_digits=10, decimal_places=1, blank=True, null=True)
    deviation = models.DecimalField(max_digits=10, decimal_places=1, blank=True, null=True)
    reference = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return f"{self.metabolite.name} - {self.plant_name} - {self.plant_part}"

    class Meta:
        indexes = [
            models.Index(fields=['plant_name', 'metabolite_id']),
            models.Index(fields=['metabolite_id', 'plant_name']),
            models.Index(fields=['plant_name']),
            models.Index(fields=['metabolite_id']),
        ]
        unique_together = ['metabolite', 'plant_name', 'plant_part', 'low', 'high', 'reference']
    
    
