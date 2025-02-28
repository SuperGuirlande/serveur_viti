from django.db import models
from metabolites.models import Plant, Activity
from django_ckeditor_5.fields import CKEditor5Field

class Remede(models.Model):
    name = models.CharField(max_length=255)
    target_plant = models.ForeignKey(Plant, on_delete=models.CASCADE, related_name='remedes')
    description = models.TextField(null=True, blank=True)
    notes = CKEditor5Field(null=True, blank=True, config_name='notes')

    activities = models.ManyToManyField(Activity, related_name='remedes_used_in')
    plants = models.ManyToManyField(Plant, related_name='remedes_used_in', blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


