# Popote Bravo — V6.17 Communauté Premium

## Nouveautés

- Vos idées : propositions Boisson / Nourriture par tous les membres.
- Votes Oui / Non visibles avec compteurs et pourcentage.
- Photos facultatives, détection des doublons, filtres Populaires / Récentes / Validées.
- Réactions rapides 🔥 😂 🍻 👀 sans commentaires.
- Cycle Popotier : En vote → À tester → Disponible / Refusée / Archivée.
- Préremplissage du catalogue depuis une idée validée.
- Vote express Popotier (30 min, 1 h, 2 h, 4 h) avec push immédiat à tous et archivage.
- Profils publics avec profil gustatif, produit signature et statistiques communautaires.
- Badges Commun / Rare / Épique / Légendaire.
- Badges : Visionnaire, Décideur express, Explorateur, Paiement réglo, Idée du mois, Pince du mois, Consommateur du mois, Ancien de la Popote, Habitué.
- Niveau Popote basé sur participation, votes, idées, paiements validés, ancienneté, badges et réactions — pas uniquement sur la consommation.
- Réactions aux profils.
- Cadres de profil Classique / Bronze / Argent / Or / Pince du mois selon badges débloqués.
- Face ID / Touch ID / empreinte via Passkeys (WebAuthn) en plus du mot de passe.
- Nouvelle entrée Idées dans la barre mobile membre et raccourci dans Gestion Popotier, tout en gardant le style noir / or actuel.

## Fichiers à copier

- app.py
- requirements.txt
- static/style.css
- templates/base.html
- templates/login.html
- templates/ideas.html (nouveau)
- templates/profile.html (nouveau)
- templates/profiles.html (nouveau)
- templates/admin_consumptions.html
- templates/admin.html

Les nouvelles tables SQLite sont créées automatiquement au redémarrage. Aucune suppression des données existantes.
