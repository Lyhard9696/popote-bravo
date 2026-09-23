# Popote Bravo — V6.20.8

Cette version remplace directement la V6.20.7.

## Face ID / Passkey
- suppression complète de Face ID / Passkey dans l'interface ;
- suppression du code WebAuthn côté Flask ;
- suppression de la dépendance `webauthn` ;
- connexion classique et sessions persistantes inchangées.

## Suppression des comptes invités
Dans Gestion > Comptes invités :
- un compte invité vide peut être supprimé par le Popotier ;
- confirmation obligatoire avant suppression ;
- le téléphone de l'ancien compte n'est plus reconnu automatiquement ;
- le même nom/prénom peut être recréé immédiatement.

Par sécurité, un compte ayant déjà des consommations, dettes, paiements ou demandes de paiement ne peut pas être supprimé depuis ce bouton. Son historique comptable est conservé.

Techniquement, un compte supprimé est archivé et désactivé plutôt que détruit brutalement, afin d'éviter toute corruption future de l'historique.

## Fichiers à copier
- app.py
- requirements.txt
- static/style.css
- templates/login.html
- templates/profile.html
- templates/admin_guests.html
