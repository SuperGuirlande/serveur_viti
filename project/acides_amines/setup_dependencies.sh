#!/bin/bash
# Script pour installer les dépendances nécessaires pour l'application acides_amines

echo "Installation des dépendances pour l'analyse des profils d'acides aminés..."
echo "Note: En cas d'erreur avec pip, utilisez directement les commandes ci-dessous:"
echo "  python -m pip install numpy"
echo "  python -m pip install scipy"
echo ""

# Essayer d'installer avec python -m pip qui est plus fiable
python -m pip install numpy scipy

echo "Installation terminée !"
echo ""
echo "Si vous rencontrez toujours des erreurs, installez manuellement les packages avec:"
echo "  pip install numpy"
echo "  pip install scipy"
echo "ou"
echo "  conda install numpy scipy (si vous utilisez Anaconda)" 