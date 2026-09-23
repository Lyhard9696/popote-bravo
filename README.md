# Popote Bravo — V6.20 Comptes invités

## Fonctionnement invité
- Bouton « Compte invité » sur la page de connexion.
- L'invité saisit uniquement son nom et prénom.
- Aucun mot de passe.
- Un identifiant d'appareil persistant est enregistré dans un cookie sécurisé.
- La session invité reste persistante pendant plusieurs années.
- Si le cookie/session disparaît, retaper le même nom reconnecte au même compte invité.
- Aucun bouton de déconnexion dans l'interface invité.

## Accès limité
Un invité a uniquement accès à :
- son ardoise actuelle ;
- le catalogue Boissons / Nourriture et l'ajout de consommations ;
- son historique récent ;
- le classement.

Il n'a pas accès aux idées, votes, profils, cadres, XP, notifications, QR, Passkeys ni à l'administration.

## Classement
- Les invités participent au classement mensuel.
- Ils sont identifiés par un badge « Invité ».
- Les invités ne possèdent pas de profil public : leur ligne n'est donc pas cliquable.
- Les vrais membres conservent leurs profils publics depuis le classement.

## Gestion Popotier
Nouvel écran `/admin/invites` :
- nom de chaque invité ;
- montant actuellement dû ;
- nombre de consommations ;
- dernière consommation ;
- bouton « Marquer payé ».

Quand le Popotier clique sur « Marquer payé », Popote Bravo enregistre exactement le solde courant comme paiement.
Les consommations restent dans l'historique mais l'ardoise repasse à 0 €.

## Important
Le mode invité est volontairement simple : le nom sert de solution de récupération si le téléphone n'est plus reconnu.
Il ne faut donc pas l'utiliser pour stocker des informations privées ou sensibles.

## Correctif iPhone
La V6.20 inclut aussi le correctif V6.19.3 de la barre de navigation basse iPhone/PWA.

## Fichiers à copier
- README.md
- app.py
- static/style.css
- templates/base.html
- templates/login.html
- templates/dashboard.html
- templates/classement.html
- templates/admin.html
- templates/guest_access.html (nouveau)
- templates/admin_guests.html (nouveau)


## V6.20.1 — Profil épuré
La page Profil est raccourcie :
- suppression de l'affichage complet des Badges ;
- suppression du gros bloc « Cadres de profil » ;
- suppression des « Réactions au profil » ;
- ajout d'un lien compact « Changer mon cadre » dans l'en-tête du profil.

Les badges continuent d'exister en arrière-plan et restent utilisés pour les XP / déblocages.
Les cadres continuent d'exister et leur collection reste accessible depuis le lien compact du profil.
