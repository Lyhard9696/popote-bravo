# Popote Bravo — V6.19 Cadres Signature & XP final

## XP Popote
Le niveau est recalculé automatiquement à partir des données déjà présentes en base.

Barème :
- Boisson non alcoolisée : 5 XP par consommation.
- Nourriture : 6 XP par consommation.
- Vote à une idée : 2 XP.
- Vote express : 2 XP.
- Idée proposée : 5 XP.
- Idée validée : +15 XP.
- Paiement validé : 4 XP.
- Badge Commun / Rare / Épique / Légendaire : +5 / +10 / +20 / +35 XP.
- Réactions reçues : +1 XP, plafonné à 100 réactions.
- Ancienneté : +4 XP par mois, plafonné à 36 mois.

Tout l'historique de consommations est rétroactif : le mois dernier et les mois antérieurs sont pris en compte dès le déploiement.

Les produits clairement alcoolisés sont exclus des objectifs de volume et de l'XP de consommation.

## 50 niveaux Popote
La progression est rapide au début puis devient plus prestigieuse.
Titres : Recrue, Connu au comptoir, Habitué, Régulier, Pilier, Figure, Patron, Légende, Institution, Mythe.

## 25 badges
Ajout de nombreux badges : premier vote, premier express, première idée, Visionnaire, Démocrate, Grand explorateur, premier paiement, Toujours réglo, Centurion, Archive vivante, Pilier historique, Top 3 du mois, etc.

## 40 cadres spéciaux
Quarante cadres spéciaux visibles dans la collection, chacun avec :
- palette propre ;
- ornement propre ;
- rareté ;
- condition de déblocage ;
- barre de progression ;
- état verrouillé grisé.

## Cadres Team produits
Chaque produit éligible génère automatiquement 4 cadres :
- Bronze : 30 consommations ;
- Argent : 60 ;
- Or : 100 ;
- Légendaire : 200.

Le visuel/photo du produit apparaît à quatre endroits autour du cadre.
Les grandes marques reconnues (Coca, Red Bull, Ice Tea, Oasis, Monster, Bueno, Fanta, Orangina, etc.) reçoivent automatiquement une palette dédiée.

Une fois équipé, le cadre est réellement appliqué autour du bloc Profil Popote, avec quatre ornements/visuels aux coins.

## Fichiers à copier dans popote_bravo_v5_render
- README.md
- app.py
- static/style.css
- templates/profile.html
- templates/profiles.html
- templates/frames.html


## V6.19.1 — Historique cadres & profils depuis le classement

- Les cadres Team utilisent tout l'historique de consommations déjà enregistré, mois dernier inclus.
- Le rapprochement historique fonctionne aussi par nom de produit : si un produit a été recréé avec un nouvel ID, ses anciennes consommations continuent de compter.
- La page Cadres affiche tous les cadres débloqués dans une section d'accès rapide tout en haut.
- Le cadre actuellement équipé est affiché en premier.
- Les cadres Team affichent le total historique et le nombre de consommations du mois dernier.
- Chaque membre du classement, podium compris, est cliquable et ouvre directement son profil Popote.
- Les profils sont visibles par tous les membres connectés de la Popote.


## V6.19.2 — Cadres Team évolutifs et page compacte

- Une seule carte par Team produit : aucune duplication Normal/Bronze/Argent/Or.
- Évolution automatique : 20 Normal, 40 Bronze, 50 Argent, 60 Or, 100 Légendaire.
- Le cadre équipé évolue tout seul quand le compteur franchit un palier.
- Historique complet conservé, mois dernier inclus.
- Regroupement robuste des variantes de marques : Red Bull, Redbull, Red Bull Zero, etc. alimentent une seule Team Red Bull.
- Les produits historiques supprimés du catalogue restent comptabilisés dans la collection.
- Menus déroulants : Mes cadres débloqués, Teams boissons, Teams nourriture, Collection spéciale.
- Les cadres débloqués restent en accès rapide tout en haut, avec le cadre équipé en premier.
- Le clic depuis le classement vers les profils publics de V6.19.1 est conservé.
