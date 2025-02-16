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
            'plant_part'
        ).distinct()  

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
    
    
