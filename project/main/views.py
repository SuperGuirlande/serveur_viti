from django.shortcuts import render
from metabolites.models import Metabolite, Activity, Plant
from django.contrib.auth.decorators import login_required

@login_required
def index(request):
    metabolites = Metabolite.objects.all()
    plants = Plant.objects.all()
    activities = Activity.objects.all()
    user = request.user
    context = {
        'user': user,
        'metabolites': metabolites,
        'plants': plants,
        'activities': activities,
    }
    return render(request, 'main/index.html', context)
