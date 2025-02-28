from django import forms
from .models import Remede, Plant


class RemedeForm(forms.ModelForm):
    class Meta: 
        model = Remede
        fields = ['name', 'target_plant', 'description','activities', 'plants',  'notes']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['target_plant'].queryset = Plant.objects.all()
        self.fields['name'].widget.attrs['class'] = 'form-input'
        self.fields['description'].widget.attrs['class'] = 'form-input'
        self.fields['notes'].widget.attrs['class'] = 'form-input'
        self.fields['activities'].widget.attrs['class'] = 'form-input select-multiple'
