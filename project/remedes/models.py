from django.db import models
from metabolites.models import Plant, Activity
from django_ckeditor_5.fields import CKEditor5Field
from accounts.models import CustomUser
from django.utils import timezone

def get_default_user():
    return CustomUser.objects.first().id

class Remede(models.Model):
    name = models.CharField(max_length=255)
    target_plant = models.ForeignKey(Plant, on_delete=models.CASCADE, related_name='remedes')
    description = models.TextField(null=True, blank=True)
    notes = CKEditor5Field(null=True, blank=True, config_name='notes')

    activities = models.ManyToManyField(Activity, related_name='remedes_used_in')
    plants = models.ManyToManyField(Plant, related_name='remedes_used_in', blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, related_name='remedes_created', default=get_default_user, null=True, blank=True)

    def __str__(self):
        return self.name


