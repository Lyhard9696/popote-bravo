# Popote Bravo — V6.20.9

Correctif à appliquer par-dessus la V6.20.8.

## Déconnexion compte invité
- ajout de « Quitter » dans la barre mobile du compte invité ;
- ajout de « Déconnexion » sur la navigation desktop ;
- confirmation avant déconnexion ;
- la session invité est supprimée ;
- le cookie de reconnexion automatique est supprimé ;
- le token appareil stocké pour cet invité est réinitialisé ;
- le compte et son historique restent conservés ;
- l'invité peut reprendre son compte plus tard en retapant exactement le même nom.

## Fichiers à remplacer
- app.py
- static/style.css
- templates/base.html
