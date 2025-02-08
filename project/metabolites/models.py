from django.db import models


class Metabolite(models.Model):
    name = models.CharField(max_length=255, unique=True)
    is_ubiquitous = models.BooleanField(default=False)

    def __str__(self):
        return self.name
    
class MetaboliteActivity(models.Model):
    metabolite = models.ForeignKey(Metabolite, related_name='activities', on_delete=models.CASCADE)
    activity_type = models.CharField(max_length=255)
    dosage = models.CharField(max_length=255, blank=True, null=True)
    reference = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return f"{self.metabolite.name} - {self.activity_type}"
    

class MetabolitePlant(models.Model):
    metabolite = models.ForeignKey(Metabolite, related_name='plants', on_delete=models.CASCADE)
    plant_part = models.CharField(max_length=255)
    low = models.DecimalField(max_digits=10, decimal_places=1, blank=True, null=True)
    high = models.DecimalField(max_digits=10, decimal_places=1, blank=True, null=True)
    deviation = models.DecimalField(max_digits=10, decimal_places=1, blank=True, null=True)
    reference = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return f"{self.metabolite.name} - {self.plant_part}"

    
    
