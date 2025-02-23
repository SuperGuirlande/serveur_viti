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
    
class Activity(models.Model):
    name = models.CharField(max_length=255, unique=True)

    def __str__(self):
        return self.name
    
class Plant(models.Model):
    name = models.CharField(max_length=200, db_index=True)

    def __str__(self):
        return self.name
    
    def get_unique_metabolites_count(self):
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
            'reference'
        ).distinct()  

    def get_common_plants(self, activity_filter=None):
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
                    )
                    SELECT 
                        p.*,
                        COUNT(DISTINCT mp2.metabolite_id) as common_metabolites_count,
                        COUNT(DISTINCT CASE 
                            WHEN am.metabolite_id IS NOT NULL 
                            AND rm.metabolite_id IS NOT NULL
                            THEN mp2.metabolite_id 
                            ELSE NULL 
                        END) as common_activity_metabolites_count,
                        COUNT(DISTINCT am_total.metabolite_id) as total_activity_metabolites_count
                    FROM metabolites_plant p
                    JOIN metabolites_metaboliteplant mp2 ON mp2.plant_name = p.name
                    JOIN reference_metabolites rm ON rm.metabolite_id = mp2.metabolite_id
                    LEFT JOIN activity_metabolites am ON am.metabolite_id = mp2.metabolite_id 
                        AND am.plant_name = p.name
                    LEFT JOIN activity_metabolites am_total ON am_total.plant_name = p.name
                    WHERE p.name != %s
                    GROUP BY p.id, p.name
                    HAVING COUNT(DISTINCT mp2.metabolite_id) > 0
                    ORDER BY total_activity_metabolites_count DESC, 
                             common_metabolites_count DESC
                """
                params = [self.name, activity_filter, self.name]
            else:
                query = """
                    WITH reference_metabolites AS (
                        SELECT DISTINCT metabolite_id
                        FROM metabolites_metaboliteplant
                        WHERE plant_name = %s
                    )
                    SELECT p.*, 
                           COUNT(DISTINCT mp2.metabolite_id) as common_metabolites_count
                    FROM metabolites_plant p
                    JOIN metabolites_metaboliteplant mp2 ON mp2.plant_name = p.name
                    JOIN reference_metabolites rm ON rm.metabolite_id = mp2.metabolite_id
                    WHERE p.name != %s
                    GROUP BY p.id, p.name
                    HAVING COUNT(DISTINCT mp2.metabolite_id) > 0
                    ORDER BY common_metabolites_count DESC
                """
                params = [self.name, self.name]

            cursor.execute(query, params)
            columns = [col[0] for col in cursor.description]
            return [
                dict(zip(columns, row))
                for row in cursor.fetchall()
            ]
    
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
        ]
        unique_together = ['metabolite', 'plant_name', 'plant_part', 'low', 'high', 'reference']
    
    
