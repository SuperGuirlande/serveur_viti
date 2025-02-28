from django import template

register = template.Library()

@register.filter
def get_item(dictionary, key):
    return dictionary.get(key)

@register.filter
def get_concentration(plant, activity):
    return activity.get_plant_total_concentration(plant) 