
# Popote Bravo — V6.6.1

Petite web-app mobile pour gérer les consommations d'une popote.

## Fonctionnalités incluses

- Création de compte membre
- Connexion par mot de passe
- Mots de passe hashés
- Compte gestionnaire / popotier
- Ajout de boissons
- Modification des noms et prix
- Activation/désactivation d'une boisson
- Enregistrement des consommations uniquement sur son propre compte
- Conservation du prix historique au moment de la consommation
- Ardoise individuelle
- Vue globale du popotier
- Enregistrement des paiements
- Historique consommations + paiements

## Lancer le projet

1. Installe Python 3.11+.
2. Ouvre un terminal dans ce dossier.
3. Crée un environnement virtuel :

Windows :
    py -m venv .venv
    .venv\Scripts\activate

macOS/Linux :
    python3 -m venv .venv
    source .venv/bin/activate

4. Installe les dépendances :
    pip install -r requirements.txt

5. Lance :
    python app.py

6. Ouvre :
    http://127.0.0.1:5000

## Tester depuis un téléphone sur le même Wi-Fi

Le serveur écoute sur 0.0.0.0:5000.

Sur le PC, trouve son adresse IP locale, par exemple 192.168.1.25.
Sur le téléphone, ouvre :

    http://192.168.1.25:5000

Cette adresse pourra ensuite être transformée en QR code pour les tests.

## Compte gestionnaire initial

Nom :
    popotier

Mot de passe :
    ChangeMoi123!

IMPORTANT : change le mot de passe et la SECRET_KEY avant toute mise en ligne réelle.

## À ajouter ensuite

- changement de mot de passe dans l'interface
- validation des nouveaux comptes par le popotier
- QR code intégré
- export CSV / Excel
- suivi du stock
- suppression/annulation d'une consommation récente
- mise en ligne avec HTTPS et base de données hébergée


## Paiement PayPal

Cette V2 permet au membre de payer tout ou partie de son ardoise via PayPal.
La dette n'est déduite qu'après confirmation d'un paiement capturé.

Variables d'environnement à configurer :

    SECRET_KEY=une-cle-longue-et-aleatoire
    PAYPAL_MODE=sandbox
    PAYPAL_CLIENT_ID=...
    PAYPAL_CLIENT_SECRET=...
    PAYPAL_WEBHOOK_ID=...

Commencer avec `PAYPAL_MODE=sandbox` et les identifiants d'une application PayPal Sandbox.
Pour la production, passer à `PAYPAL_MODE=live` uniquement après tests.

Le webhook `/api/paypal/webhook` doit être exposé en HTTPS et configuré côté PayPal.
Abonner au minimum l'événement `PAYMENT.CAPTURE.COMPLETED`.

IMPORTANT : ne jamais mettre le `PAYPAL_CLIENT_SECRET` dans du JavaScript ou dans une page publique.
Il reste uniquement côté serveur.


## Nouveauté V3

Le popotier peut enregistrer un paiement directement depuis le tableau de bord :
- choix du membre ;
- montant payé ;
- moyen de paiement (espèces, virement, PayPal manuel, autre) ;
- note optionnelle ;
- déduction immédiate de l'ardoise.


## Nouveauté V4 — Gestion de stock

- stock initial configurable pour chaque boisson ;
- décrément automatique de 1 à chaque consommation ;
- affichage du stock restant côté membre ;
- passage automatique en indisponible quand le stock atteint 0 ;
- alerte de stock faible à 5 unités ou moins ;
- réapprovisionnement rapide avec un bouton dédié ;
- possibilité de corriger manuellement le stock depuis l'administration.


## V5 — Mise en ligne sur Render

Lancement production :

    gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 60

Variables :

    APP_ENV=production
    SECRET_KEY=<générée côté Render>
    DATA_DIR=/var/data

Pour conserver SQLite sur Render, attacher un disque persistant au service et le monter sur `/var/data`.

Route de contrôle : `/health`


## V5.1 — Changement de mot de passe

Chaque utilisateur connecté peut modifier son mot de passe depuis le menu « Mot de passe ».

Le formulaire :
- vérifie le mot de passe actuel ;
- exige au moins 8 caractères ;
- demande une confirmation ;
- refuse de réutiliser exactement le mot de passe actuel ;
- stocke uniquement le hash du nouveau mot de passe.


## V5.2
Paiements PayPal déclarés par le membre, puis validés ou refusés par le popotier.


## V5.3 — PayPal.Me

Lien de paiement par défaut :

    https://paypal.me/PopoteBellac

Le membre :
- choisit le montant à régler ;
- ouvre PayPal.Me avec le montant prérempli ;
- revient dans Popote Bravo ;
- déclare le même montant ;
- voit son reste estimé diminuer immédiatement ;
- attend la validation du popotier.

Variable optionnelle :

    PAYPAL_ME_URL=https://paypal.me/PopoteBellac


## V5.4 — Icône iPhone

L'insigne P3 est utilisé comme icône d'écran d'accueil iPhone et comme favicon navigateur.


## V6

- Annulation d'une consommation pendant 30 secondes côté membre.
- Suppression/correction d'une consommation par le popotier avec restauration du stock.
- Seuil de stock faible personnalisable pour chaque produit.
- Gestion des membres : renommer, activer/désactiver, réinitialiser le mot de passe.
- Tableau de bord popotier : ardoises totales, consommations sur 24 h, paiements à vérifier, stocks faibles.
- Page QR Code accessible depuis le menu et scannable directement depuis l'écran d'un téléphone.


## V6.1

- Page Classement visible par les membres connectés.
- Top 3 du mois selon la somme des consommations en euros.
- Les paiements n'ont aucun effet sur le classement.
- QR Code amélioré avec partage natif du téléphone.
- Bouton de copie du lien en solution de secours.


## V6.2 — Expérience mobile

- Barre de navigation fixe en bas sur téléphone.
- Zones tactiles plus grandes pour usage à une main.
- Gestion des safe areas iPhone / écran d'accueil.
- En-tête compact et écran membre plus visuel.
- Animations discrètes sur boutons, cartes et messages de confirmation.
- Aucun changement dans la logique des ardoises, paiements ou stocks.


## V6.2.1

Correctif mobile :
- ajout d'un bouton « Se déconnecter » visible sur la page Profil / Mot de passe.


## V6.3 — Gestion popotier

- Suppression définitive d'un compte membre.
- Ajout de boisson toujours disponible.
- Suppression d'une boisson du catalogue, en conservant l'historique des anciennes consommations.
- Mise à jour directe du stock : si le stock affiche 20, saisir 6 puis valider met immédiatement le stock à 6.
- Un stock mis à 0 rend automatiquement la boisson indisponible.


## V6.3.1 — Onglet Stock

- Nouvel onglet Stock réservé au popotier.
- Affichage volontairement simple : nom du produit + quantité restante.
- Les ruptures apparaissent en rouge.
- Les stocks sous leur seuil apparaissent en jaune.
- Tri automatique : ruptures et stocks faibles en premier, pratique pour faire les courses.


## V6.4 — Gestion Popotier réorganisée

- Gestion devient un menu central.
- Gestion des comptes : membres, activation, nom, mot de passe, fiche et suppression.
- Gestion des consommations : produits, prix, stock, seuils, ajout et suppression.
- Stock / Courses reste une page séparée.
- Le tableau principal conserve les paiements à vérifier et l'enregistrement manuel des paiements.
- Correction de la modification du seuil de stock faible dans les fiches produits.

## V6.5 — Expérience utilisateur

- Accueil membre plus rapide : ardoise actuelle, dépensé ce mois, paiements en attente.
- Quantité multiple : ajouter plusieurs exemplaires d'un produit en une seule validation.
- Confirmation automatique pour les quantités supérieures à 1.
- Le stock ne peut jamais descendre sous zéro.
- Suivi visuel des paiements déclarés : en attente, validé ou refusé.
- Classement enrichi : Top 3 public + position personnelle et montant consommé dans le mois.


## V6.6 — Panier & Notifications

- Panier multi-produits : plusieurs boissons/barres en une seule validation.
- Compteur fixe du panier avec nombre d'articles et total en euros.
- État « Enregistrement… » pendant l'envoi pour éviter les doubles validations.
- Ticket après commande, regroupé par produit, annulable pendant 30 secondes.
- Historique regroupé par commande : ex. 8 × Coca — total de la commande.
- Produits en rupture conservés visibles et grisés.
- Retour visuel renforcé après une commande réussie.
- Badge de paiements en attente sur l'accueil.
- Centre de notifications interne.
- Notifications membre lors d'un paiement validé ou refusé.
- Notifications Popotier lors d'un stock faible ou d'une rupture.
- Recherche instantanée dans les comptes et les produits.
- Confirmation renforcée par saisie de SUPPRIMER pour les suppressions définitives.
- Confirmation renforcée pour un ajustement de stock de 10 unités ou plus.


## V6.6.1 — Bouton PayPal

- Restauration du bouton jaune PayPal sur l'accueil membre.
- Ajout d'un pictogramme PayPal stylisé.
- Le badge du nombre de paiements en attente reste visible.
- Aucun changement fonctionnel sur les paiements.
