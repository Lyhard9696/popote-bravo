# Popote Bravo — V6.18 Cadres & Niveaux

## Niveaux Popote
Le niveau est calculé rétroactivement à partir de l'historique déjà présent en base.

Les consommations des mois précédents, y compris le mois dernier, sont donc immédiatement prises en compte après déploiement.

XP :
- consommations historiques : +2 XP, avec plafond de 10 consommations/jour pour l'XP ;
- vote à une idée : +5 XP ;
- vote express : +8 XP ;
- idée proposée : +20 XP ;
- idée validée : +60 XP supplémentaires ;
- paiement validé : +20 XP ;
- badges : +20 / +40 / +80 / +140 XP selon la rareté ;
- réaction reçue : +2 XP (100 maximum comptabilisées) ;
- ancienneté : +3 XP par semaine (plafond 3 ans).

50 niveaux sont disponibles, avec une courbe de progression qui devient progressivement plus exigeante.

## Cadres
Nouvelle page `/profil/cadres`.

- Tous les cadres sont visibles.
- Les cadres verrouillés sont grisés avec cadenas + progression.
- Un cadre débloqué peut être équipé depuis la collection.
- Les cadres déjà débloqués restent disponibles.

### Cadres Team automatiques
Pour chaque produit éligible de la Popote :
- Bronze : 30 consommations
- Argent : 60
- Or : 100
- Légendaire : 200

Les nouveaux produits ajoutés au catalogue génèrent automatiquement leurs 4 cadres Team.
Les produits clairement alcoolisés sont exclus des objectifs de volume.

### Cadres spéciaux
Niveaux, votes, idées validées, ancienneté, badges, Passkey, réactions, Pince du mois, Consommateur du mois, etc.

## Fichiers à copier dans popote_bravo_v5_render
- README.md
- app.py
- static/style.css
- templates/profile.html
- templates/profiles.html
- templates/frames.html (nouveau)
