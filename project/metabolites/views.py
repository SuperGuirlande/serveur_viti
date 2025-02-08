from django.shortcuts import render, get_object_or_404
from metabolites.models import Metabolite, MetaboliteActivity, MetabolitePlant


# Create your views here.
def metabolite_detail(request, id):
    metabolite = get_object_or_404(Metabolite, id=id)

    context = {
        'metabolite': metabolite
    }

    return render(request, 'metabolites/metabolite_detail.html', context)


