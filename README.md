# Popote Bravo — V6.16

## Notification générale Popotier

Ajout dans la page Gestion d'un bloc « Notification générale ».

Fonctionnement :
- le Popotier écrit un titre et un message ;
- bouton « Envoyer à tout le monde » ;
- tous les comptes actifs reçoivent la notification dans Popote Bravo ;
- les comptes ayant activé le push la reçoivent aussi sur leur téléphone ;
- `{prenom}` peut être utilisé dans le titre ou le message pour insérer le nom du membre ;
- un message de confirmation indique le nombre de comptes notifiés et le nombre d'appareils push atteints.

Fichiers à copier dans `popote_bravo_v5_render` :
- `app.py`
- `static/style.css`
- `templates/admin.html`
