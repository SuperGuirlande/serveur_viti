from django.db import models
from django.db import connection


class Metabolite(models.Model):
    name = models.CharField(max_length=255, unique=True)
    is_ubiquitous = models.BooleanField(default=False)


    def get_unique_activities(self):
        return MetaboliteActivity.objects.filter(metabolite=self).distinct()
    
    def get_unique_activities_count(self):
        return MetaboliteActivity.objects.filter(metabolite=self).distinct().count()
    
    def get_unique_plants_count(self):
        return MetabolitePlant.objects.filter(metabolite=self).values('plant_name').distinct().count()
    
    def get_plants_with_parts(self):
        return MetabolitePlant.objects.filter(
            metabolite=self
        ).values(
            'plant_name',
            'plant_part',
            'low',
            'high',
            'deviation',
            'reference'
        ).annotate(
            plant_id=models.Subquery(
                Plant.objects.filter(
                    name=models.OuterRef('plant_name')
                ).values('id')[:1]
            )
        ).distinct()
    
    def get_activities_with_details(self):
        return MetaboliteActivity.objects.filter(
            metabolite=self
        ).values(
            'activity__name',
            'dosage',
            'reference'
        ).distinct()

    def __str__(self):
        return self.name
    
    def get_activities_by_plant(self):
        """Retourne un dictionnaire des activités groupées par plante"""
        return (
            self.plants.values('plant_name')
            .annotate(
                activities=models.Subquery(
                    MetaboliteActivity.objects.filter(
                        metabolite=self
                    ).values('activity__name')
                    .distinct()
                )
            )
        )
    
    def get_plants_by_activity(self):
        """Retourne un dictionnaire des plantes groupées par activité"""
        return (
            self.activities.values('activity__name')
            .annotate(
                plants=models.Subquery(
                    MetabolitePlant.objects.filter(
                        metabolite=self
                    ).values('plant_name')
                    .distinct()
                )
            )
        )

    @classmethod
    def get_global_matrix(cls):
        """Retourne une matrice de relations entre métabolites, plantes et activités"""
        return (
            cls.objects
            .annotate(
                plant_count=models.Count('plants__plant_name', distinct=True),
                activity_count=models.Count('activities__activity', distinct=True)
            )
            .values('name', 'is_ubiquitous', 'plant_count', 'activity_count')
        )

class Activity(models.Model):
    name = models.CharField(max_length=255, unique=True, db_index=True)

    def __str__(self):
        return self.name
    
class Plant(models.Model):
    name = models.CharField(max_length=200, db_index=True)

    def __str__(self):
        return self.name
    
    @property
    def all_metabolites_count(self):
        """Retourne le nombre total de métabolites (incluant les doublons sur différentes parties)"""
        return MetabolitePlant.objects.filter(plant_name=self.name).count()
    
    def get_unique_metabolites_count(self):
        """Retourne le nombre de métabolites uniques"""
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT COUNT(DISTINCT metabolite_id) 
                FROM metabolites_metaboliteplant 
                WHERE plant_name = %s
            """, [self.name])
            return cursor.fetchone()[0]
    
    def get_metabolites_with_parts(self):
        return MetabolitePlant.objects.filter(
            plant_name=self.name
        ).values(
            'metabolite_id',
            'metabolite__name',
            'plant_part',
            'low',
            'high',
            'deviation',
            'reference',
            'metabolite__is_ubiquitous'
        ).order_by(
            'metabolite__name',
            'plant_part'
        ).distinct()

    def get_common_plants(self, activity_filter=None, page=1, per_page=50):
        offset = (page - 1) * per_page
        with connection.cursor() as cursor:
            if activity_filter:
                query = """
                    WITH reference_metabolites AS (
                        SELECT DISTINCT metabolite_id
                        FROM metabolites_metaboliteplant
                        WHERE plant_name = %s
                    ),
                    activity_metabolites AS (
                        SELECT DISTINCT mp.metabolite_id, mp.plant_name
                        FROM metabolites_metaboliteplant mp
                        JOIN metabolites_metaboliteactivity ma ON ma.metabolite_id = mp.metabolite_id
                        JOIN metabolites_activity a ON a.id = ma.activity_id
                        WHERE a.name = %s
                    ),
                    common_plants AS (
                        SELECT 
                            p.id,
                            p.name,
                            COUNT(DISTINCT mp2.metabolite_id) as common_metabolites_count,
                            COUNT(DISTINCT CASE 
                                WHEN am.metabolite_id IS NOT NULL 
                                THEN mp2.metabolite_id 
                                ELSE NULL 
                            END) as common_activity_metabolites_count,
                            (SELECT COUNT(DISTINCT metabolite_id) 
                             FROM metabolites_metaboliteplant 
                             WHERE plant_name = p.name) as total_metabolites_count,
                            (SELECT COUNT(DISTINCT ma.metabolite_id)
                             FROM metabolites_metaboliteactivity ma
                             JOIN metabolites_activity a ON a.id = ma.activity_id
                             JOIN metabolites_metaboliteplant mp ON mp.metabolite_id = ma.metabolite_id
                             WHERE mp.plant_name = p.name
                             AND a.name = %s) as total_activity_metabolites_count
                        FROM metabolites_plant p
                        JOIN metabolites_metaboliteplant mp2 ON mp2.plant_name = p.name
                        JOIN reference_metabolites rm ON rm.metabolite_id = mp2.metabolite_id
                        LEFT JOIN activity_metabolites am ON am.metabolite_id = mp2.metabolite_id 
                            AND am.plant_name = p.name
                        WHERE p.name != %s
                        GROUP BY p.id, p.name
                        HAVING COUNT(DISTINCT mp2.metabolite_id) > 0
                    )
                    SELECT *, 
                           COUNT(*) OVER() as total_count
                    FROM common_plants
                    ORDER BY common_activity_metabolites_count DESC, 
                             common_metabolites_count DESC
                    LIMIT %s OFFSET %s
                """
                params = [self.name, activity_filter, activity_filter, self.name, per_page, offset]
            else:
                query = """
                    WITH reference_metabolites AS (
                        SELECT DISTINCT metabolite_id
                        FROM metabolites_metaboliteplant
                        WHERE plant_name = %s
                    ),
                    common_plants AS (
                        SELECT 
                            p.id,
                            p.name,
                            COUNT(DISTINCT mp2.metabolite_id) as common_metabolites_count,
                            (SELECT COUNT(DISTINCT metabolite_id) 
                             FROM metabolites_metaboliteplant 
                             WHERE plant_name = p.name) as total_metabolites_count
                        FROM metabolites_plant p
                        JOIN metabolites_metaboliteplant mp2 ON mp2.plant_name = p.name
                        JOIN reference_metabolites rm ON rm.metabolite_id = mp2.metabolite_id
                        WHERE p.name != %s
                        GROUP BY p.id, p.name
                        HAVING COUNT(DISTINCT mp2.metabolite_id) > 0
                    )
                    SELECT *, 
                           COUNT(*) OVER() as total_count
                    FROM common_plants
                    ORDER BY common_metabolites_count DESC
                    LIMIT %s OFFSET %s
                """
                params = [self.name, self.name, per_page, offset]

            cursor.execute(query, params)
            columns = [col[0] for col in cursor.description]
            results = [dict(zip(columns, row)) for row in cursor.fetchall()]
            
            total_count = results[0]['total_count'] if results else 0
            
            return {
                'results': results,
                'total_count': total_count,
                'page': page,
                'per_page': per_page,
                'total_pages': (total_count + per_page - 1) // per_page
            }
    
    def get_metabolites_by_activity(self, activity_name):
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT COUNT(DISTINCT mp.metabolite_id) 
                FROM metabolites_metaboliteplant mp
                JOIN metabolites_metaboliteactivity ma ON ma.metabolite_id = mp.metabolite_id
                JOIN metabolites_activity a ON a.id = ma.activity_id
                WHERE mp.plant_name = %s
                AND a.name = %s
            """, [self.name, activity_name])
            return cursor.fetchone()[0]
            

        



class MetaboliteActivity(models.Model):
    metabolite = models.ForeignKey(Metabolite, related_name='activities', on_delete=models.CASCADE)
    activity = models.ForeignKey(Activity, on_delete=models.CASCADE)
    dosage = models.CharField(max_length=255, null=True, blank=True)
    reference = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        unique_together = ['metabolite', 'activity', 'dosage', 'reference']
        indexes = [
            models.Index(fields=['metabolite', 'activity']),
            models.Index(fields=['activity']),
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
            models.Index(fields=['plant_name', 'metabolite']),
            models.Index(fields=['metabolite']),
            models.Index(fields=['plant_name', 'plant_part']),
        ]
        unique_together = ['metabolite', 'plant_name', 'plant_part', 'low', 'high', 'reference']
    
    
