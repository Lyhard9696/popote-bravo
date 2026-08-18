# Popote Bravo — V6.16.1

## Correctif validation des paiements déclarés

Correction d'un bug lors de la validation d'un paiement par le Popotier.

Avant :
- la validation comparait le paiement uniquement aux consommations moins les paiements déjà validés ;
- les dettes manuelles ajoutées par le Popotier étaient oubliées ;
- un membre pouvait donc voir 15 € d'ardoise, déclarer 15 €, puis obtenir à tort le message « le montant dépasse la dette officielle restante ».

Maintenant :
- la validation utilise exactement le même calcul d'ardoise que le reste de l'application :
  consommations + dettes manuelles - paiements validés.

Fichier à copier dans `popote_bravo_v5_render` :
- `app.py`
