from django.contrib import admin
from .models import Remede


class RemedeAdmin(admin.ModelAdmin):
    list_display = ('name', 'target_plant', 'created_at', 'updated_at')
    list_filter = ('target_plant',)
    search_fields = ('name', 'target_plant__name')
    list_per_page = 20

admin.site.register(Remede, RemedeAdmin)

