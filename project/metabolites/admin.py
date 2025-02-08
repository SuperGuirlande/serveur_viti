from django.contrib import admin
from .models import Metabolite, MetaboliteActivity, MetabolitePlant


class MetaboliteActivityInline(admin.TabularInline):
    model = MetaboliteActivity
    extra = 1
    fields = ('activity_type', 'dosage', 'reference')

class MetabolitePlantInline(admin.TabularInline):
    model = MetabolitePlant
    extra = 1
    fields = ('plant_part', 'low', 'high', 'deviation', 'reference')

class MetaboliteAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_ubiquitous', 'get_activities_count', 'get_plants_count')
    list_filter = ('is_ubiquitous', 'activities__activity_type')
    search_fields = ('name', 'activities__activity_type', 'activities__reference')
    ordering = ('name',)
    inlines = [MetaboliteActivityInline, MetabolitePlantInline]
    
    fieldsets = (
        ('Informations principales', {
            'fields': ('name', 'is_ubiquitous')
        }),
    )
    
    def get_activities_count(self, obj):
        return obj.activities.count()
    get_activities_count.short_description = 'Nombre d\'activités'

    def get_plants_count(self, obj):
        return obj.plants.count()
    get_plants_count.short_description = 'Nombre de plantes'

    class Media:
        css = {
            'all': ('admin/css/forms.css',)
        }
        js = ('admin/js/vendor/jquery/jquery.js',)


class MetaboliteActivityAdmin(admin.ModelAdmin):
    list_display = ('activity_type', 'dosage', 'reference', 'metabolite')
    list_filter = ('activity_type',)
    search_fields = ('activity_type', 'reference', 'metabolite__name')
    ordering = ('activity_type',)


class MetabolitePlantAdmin(admin.ModelAdmin):
    list_display = ('metabolite', 'plant_part', 'low', 'high', 'deviation', 'reference')
    list_filter = ('plant_part',)
    search_fields = ('metabolite__name', 'plant_part', 'reference')
    ordering = ('metabolite', 'plant_part')


admin.site.register(Metabolite, MetaboliteAdmin)
admin.site.register(MetaboliteActivity, MetaboliteActivityAdmin)
admin.site.register(MetabolitePlant, MetabolitePlantAdmin)