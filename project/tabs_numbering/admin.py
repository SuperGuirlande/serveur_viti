from django.contrib import admin
from .models import PlantNumbering

@admin.register(PlantNumbering)
class PlantNumberingAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'plant_id', 'created_at')
    list_filter = ('user', 'created_at')
    search_fields = ('name', 'user__username')
    readonly_fields = ('created_at',)
    ordering = ('-created_at',)
