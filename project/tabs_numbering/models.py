from django.db import models
from accounts.models import CustomUser
from metabolites.models import Plant

class PlantNumbering(models.Model):
    """
    Modèle pour stocker les numérotations de plantes créées par les utilisateurs.
    Les numérotations permettent aux utilisateurs d'assigner des numéros uniques aux plantes 
    et de conserver cette numérotation entre les différentes vues triées.
    """
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='plant_numberings')
    name = models.CharField(max_length=255, verbose_name="Nom de la numérotation")
    plant_id = models.IntegerField(verbose_name="ID de la plante de référence")
    query_params = models.TextField(verbose_name="Paramètres de requête")  # Stockés en JSON
    numbering_data = models.JSONField(verbose_name="Données de numérotation")  # {plant_id: numéro}
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Date de création")

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Numérotation de plantes"
        verbose_name_plural = "Numérotations de plantes"
        
    def __str__(self):
        return f"{self.name} ({self.created_at.strftime('%d/%m/%Y')})"
