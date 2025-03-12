from django.db import models
from django.db import connection
from django.utils.functional import cached_property
from django.core.cache import cache
import logging
from .utils import log_execution_time

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

    def get_common_plants(self, activity_filter=None, page=1, per_page=50, sort_params=None, exclude_ubiquitous=False):
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
                    order_by.append(f"""
                        CASE 
                            WHEN reference_count >= metabolites_total 
                            THEN (common_metabolites_count * 100.0 / NULLIF(reference_count, 0))
                            ELSE (common_metabolites_count * 100.0 / NULLIF(metabolites_total, 0))
                        END {direction}
                    """.replace('\n', ' ').strip())
                elif field == 'common_activity_metabolites' and activity_filter:
                    order_by.append(f"common_activity_metabolites_count {direction}")
                elif field == 'total_activity_metabolites' and activity_filter:
                    order_by.append(f"total_activity_metabolites_count {direction}")
        
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

            if activity_filter:
                # Créer les tables temporaires
                query_temp_ref = """
                    CREATE TEMPORARY TABLE IF NOT EXISTS temp_reference_metabolites AS
                    SELECT DISTINCT mp.metabolite_id
                    FROM metabolites_metaboliteplant mp
                    JOIN metabolites_metabolite m ON m.id = mp.metabolite_id
                    WHERE mp.plant_name = %s
                """
                
                if exclude_ubiquitous:
                    query_temp_ref += " AND m.is_ubiquitous = FALSE"
                
                cursor.execute(query_temp_ref, [self.name])

                query_temp_activity = """
                    CREATE TEMPORARY TABLE IF NOT EXISTS temp_activity_metabolites AS
                    SELECT DISTINCT mp.metabolite_id, mp.plant_name
                    FROM metabolites_metaboliteplant mp
                    JOIN metabolites_metaboliteactivity ma ON ma.metabolite_id = mp.metabolite_id
                    JOIN metabolites_activity a ON a.id = ma.activity_id
                    JOIN metabolites_metabolite m ON m.id = mp.metabolite_id
                    WHERE a.name = %s
                """
                
                if exclude_ubiquitous:
                    query_temp_activity += " AND m.is_ubiquitous = FALSE"
                
                cursor.execute(query_temp_activity, [activity_filter])

                # Requête principale avec tri dynamique
                query_main = f"""
                    WITH plant_counts AS (
                        SELECT plant_name, COUNT(DISTINCT mp.metabolite_id) as metabolites_total
                        FROM metabolites_metaboliteplant mp
                        JOIN metabolites_metabolite m ON m.id = mp.metabolite_id
                        WHERE 1=1
                """
                
                if exclude_ubiquitous:
                    query_main += " AND m.is_ubiquitous = FALSE"
                
                query_main += f"""
                        GROUP BY plant_name
                    )
                    SELECT 
                        p.id,
                        p.name,
                        COUNT(DISTINCT mp2.metabolite_id) as common_metabolites_count,
                        COUNT(DISTINCT CASE 
                            WHEN am.metabolite_id IS NOT NULL 
                            THEN mp2.metabolite_id 
                        END) as common_activity_metabolites_count,
                        pc.metabolites_total,
                        t2.activity_count as total_activity_metabolites_count,
                        COUNT(*) OVER() as pagination_total,
                        """ + str(reference_count) + """ as reference_count
                    FROM metabolites_plant p
                    JOIN metabolites_metaboliteplant mp2 ON mp2.plant_name = p.name
                    JOIN temp_reference_metabolites rm ON rm.metabolite_id = mp2.metabolite_id
                    JOIN plant_counts pc ON pc.plant_name = p.name
                    LEFT JOIN temp_activity_metabolites am ON am.metabolite_id = mp2.metabolite_id 
                        AND am.plant_name = p.name
                    LEFT JOIN (
                        SELECT mp.plant_name, COUNT(DISTINCT ma.metabolite_id) as activity_count
                        FROM metabolites_metaboliteplant mp
                        JOIN metabolites_metaboliteactivity ma ON ma.metabolite_id = mp.metabolite_id
                        JOIN metabolites_activity a ON a.id = ma.activity_id
                """
                
                if exclude_ubiquitous:
                    query_main += """
                        JOIN metabolites_metabolite m ON m.id = mp.metabolite_id
                        WHERE a.name = %s AND m.is_ubiquitous = FALSE
                    """
                else:
                    query_main += """
                        WHERE a.name = %s
                    """
                
                query_main += """
                        GROUP BY mp.plant_name
                    ) t2 ON t2.plant_name = p.name
                    WHERE p.name != %s AND pc.metabolites_total > 1
                    GROUP BY p.id, p.name, pc.metabolites_total, t2.activity_count
                    HAVING COUNT(DISTINCT mp2.metabolite_id) > 0
                """
                
                query_main += f" {order_by_clause}"
                query_main += " LIMIT %s OFFSET %s"
                
                cursor.execute(query_main, [activity_filter, self.name, per_page, offset])

                columns = [col[0] for col in cursor.description]
                results = [dict(zip(columns, row)) for row in cursor.fetchall()]
                logger.info(f"Nombre de résultats obtenus: {len(results)}")

                # Nettoyer les tables temporaires
                cursor.execute("DROP TEMPORARY TABLE IF EXISTS temp_reference_metabolites")
                cursor.execute("DROP TEMPORARY TABLE IF EXISTS temp_activity_metabolites")

            else:
                # Version sans activité avec tri dynamique
                query_temp_ref = """
                    CREATE TEMPORARY TABLE IF NOT EXISTS temp_reference_metabolites AS
                    SELECT DISTINCT mp.metabolite_id
                    FROM metabolites_metaboliteplant mp
                    JOIN metabolites_metabolite m ON m.id = mp.metabolite_id
                    WHERE mp.plant_name = %s
                """
                
                if exclude_ubiquitous:
                    query_temp_ref += " AND m.is_ubiquitous = FALSE"
                
                cursor.execute(query_temp_ref, [self.name])

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
                        COUNT(DISTINCT mp2.metabolite_id) as common_metabolites_count,
                        pc.metabolites_total,
                        COUNT(*) OVER() as pagination_total,
                        """ + str(reference_count) + """ as reference_count
                    FROM metabolites_plant p
                    JOIN metabolites_metaboliteplant mp2 ON mp2.plant_name = p.name
                    JOIN temp_reference_metabolites rm ON rm.metabolite_id = mp2.metabolite_id
                    JOIN plant_counts pc ON pc.plant_name = p.name
                    WHERE p.name != %s AND pc.metabolites_total > 1
                    GROUP BY p.id, p.name, pc.metabolites_total
                    HAVING COUNT(DISTINCT mp2.metabolite_id) > 0
                """
                
                query += f" {order_by_clause}"
                query += " LIMIT %s OFFSET %s"
                logger.info(f"Exécution de la requête SQL: {query}")
                cursor.execute(query, [self.name, per_page, offset])

                columns = [col[0] for col in cursor.description]
                results = [dict(zip(columns, row)) for row in cursor.fetchall()]
                logger.info(f"Nombre de résultats obtenus: {len(results)}")

                cursor.execute("DROP TEMPORARY TABLE IF EXISTS temp_reference_metabolites")
            
            # Calculer les pourcentages avec la nouvelle méthode
            for result in results:
                common_count = result['common_metabolites_count']
                plant_total = result['metabolites_total']  # Utilisation du nouveau champ
                
                # Déterminer quel calcul utiliser
                # Calculer le pourcentage par rapport à la plante cible (recherchée)
                # au lieu de la plante affichée dans le tableau
                if reference_count >= plant_total:
                    # Cas bleu : la plante cible a plus de métabolites
                    percentage = (common_count * 100.0) / reference_count if reference_count > 0 else 0
                    result['percentage_type'] = 'blue'
                    logger.info(f"- Cas BLEU: {common_count} * 100 / {reference_count} = {percentage}%")
                else:
                    # Cas vert : la plante affichée a plus de métabolites
                    percentage = (common_count * 100.0) / plant_total if plant_total > 0 else 0
                    result['percentage_type'] = 'green'
                    logger.info(f"- Cas VERT: {common_count} * 100 / {plant_total} = {percentage}%")
                
                result['common_metabolites_percentage'] = round(percentage, 1)
                logger.info(f"- Pourcentage final: {result['common_metabolites_percentage']}%")
            
            # Filtrer les résultats pour exclure les plantes avec un seul métabolite
            # et les plantes avec 100% de métabolites communs (qui sont probablement des plantes avec peu de métabolites)
            results = [result for result in results if result['metabolites_total'] > 1 and result['common_metabolites_percentage'] < 100.0]
            
            # Récupérer le total_count pour la pagination
            total_count = results[0]['pagination_total'] if results else 0
            
            return {
                'results': results,
                'total_count': total_count,
                'page': page,
                'per_page': per_page,
                'total_pages': (total_count + per_page - 1) // per_page
            }
    
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
            models.Index(fields=['metabolite_id', 'plant_name']),
            models.Index(fields=['plant_name', 'metabolite', 'plant_part'], name='idx_plant_metab_part'),
            models.Index(fields=['metabolite', 'plant_name'], name='idx_metab_plant'),
            models.Index(fields=['metabolite'], name='idx_metabolite'),
            models.Index(fields=['plant_name', 'plant_part'], name='idx_plant_part'),
            models.Index(fields=['plant_name', 'metabolite_id'], name='idx_plant_metab_id'),
            models.Index(fields=['metabolite_id', 'plant_name'], name='idx_metab_id_plant'),
        ]
        unique_together = ['metabolite', 'plant_name', 'plant_part', 'low', 'high', 'reference']
    
    
