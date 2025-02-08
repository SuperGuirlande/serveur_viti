from django.shortcuts import render
from metabolites.models import Metabolite

def index(request):
    metabolites = Metabolite.objects.all()
    user = request.user
    context = {
        'user': user,
        'metabolites': metabolites,
    }
    return render(request, 'main/index.html', context)
