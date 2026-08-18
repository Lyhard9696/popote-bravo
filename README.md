
# Popote Bravo — V6.10.3

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


## V6.7

- Swipe « Glisser pour payer avec PayPal ».
- Le popotier peut ajouter une dette manuelle à un membre.
- Les dettes manuelles augmentent l'ardoise mais ne comptent pas dans le classement.
- Suppression d'un produit sans confirmation supplémentaire.
- Catégories produit : Boisson / Nourriture.
- Catalogue utilisateur organisé en menus déroulants par catégorie.
- Recherche utilisateur dans le catalogue.
- Classement général affichant tous les membres du mois.


## V6.7.1 — Catalogue mobile amélioré

- Mini-panier compact, invisible lorsqu'il est vide.
- Mini-panier fixé juste au-dessus de la navigation mobile.
- Panier dépliable pour voir le détail des articles sélectionnés.
- Cartes produits beaucoup plus compactes.
- Bouton « + Ajouter » qui devient automatiquement un compteur − / +.
- Total par ligne lorsque plusieurs unités sont sélectionnées.
- Filtres rapides Tout / Boissons / Nourriture.
- Recherche catalogue conservée en haut pendant le défilement.
- Stock faible affiché en orange et stock critique en rouge.
- Produit sélectionné mis en évidence en jaune.
- Bouton de validation passe à « Enregistrement… » pendant l'envoi.


## V6.7.2 — Correctif Internal Server Error

- `init_db()` est maintenant exécuté automatiquement au démarrage sur Render/Gunicorn.
- Les migrations de la base existante sont donc appliquées avant les premières requêtes.
- Ajoute notamment les structures nécessaires pour les dettes manuelles et les catégories Boisson/Nourriture.
- Le schéma neuf contient directement la colonne `category`.
- Les migrations utilisent `CREATE TABLE IF NOT EXISTS` et `ALTER TABLE` uniquement quand une colonne manque : les données existantes sont conservées.


## V6.8 — Popotier compact

- Gestion des comptes affichée sous forme de fiches compactes.
- Une fiche membre affiche immédiatement nom, ardoise et statut.
- Bouton « Gérer » pour ouvrir uniquement les actions détaillées du membre.
- Gestion des produits affichée sous forme de fiches compactes.
- Chaque produit affiche nom, catégorie, prix et stock sur une seule ligne.
- Boutons rapides −1 / +1 pour corriger le stock.
- Bouton « Modifier » pour ouvrir prix, catégorie, seuil, stock exact et suppression.
- Toutes les fonctions existantes restent disponibles.


## V6.8.1 — Correctif templates Popotier

- Correction de `admin_accounts.html`.
- Correction de `admin_consumptions.html`.
- Les blocs Jinja sont désormais correctement fermés avec `{% endblock %}`.
- Aucun changement sur la base de données ni sur la logique métier.


## V6.8.2 — Correctif swipe PayPal

- Le curseur PayPal peut maintenant être glissé réellement au doigt sur iPhone.
- Support Pointer Events + fallback Touch Events.
- Support souris pour test sur PC.
- Déclenchement à environ 78 % de la course.
- Retour automatique à gauche si le swipe n'est pas terminé.


## V6.8.3 — Slider PayPal iPhone

- Remplacement du drag JavaScript par un `input[type=range]` natif, beaucoup plus fiable sur iPhone/Safari.
- Le slider ouvre directement PayPal lorsque le curseur atteint 96 %.
- Aucun clic supplémentaire n'est nécessaire après le swipe.
- Le lien « Ouvrir PayPal manuellement » reste uniquement comme solution de secours.
- Ajout d'espace sous les pages mobiles pour éviter que la navigation fixe masque les formulaires.


## V6.8.4 — Paiement PayPal simplifié

- Suppression complète du slider / swipe PayPal.
- Suppression du lien « Ouvrir PayPal manuellement ».
- Un seul bouton jaune « Payer avec PayPal ».
- Un clic ouvre directement PayPal avec le montant saisi/prérempli.
- Le bouton se désactive pendant l'ouverture pour éviter les doubles clics.


## V6.9 — Notifications Push téléphone

- Abonnement Web Push depuis Profil.
- Service worker pour recevoir les notifications même lorsque Popote Bravo n'est pas ouvert.
- Push aux comptes Popotier lorsqu'un membre déclare un paiement.
- Push au membre quand son paiement est validé ou refusé.
- Bouton de notification test.
- Le centre de notifications interne reste disponible en secours.

### Variables Render requises

- `VAPID_PUBLIC_KEY`
- `VAPID_PRIVATE_KEY`
- `VAPID_SUBJECT` (ex. `mailto:adresse@example.com`)

Sur iPhone, Popote Bravo doit être ajouté à l'écran d'accueil et les notifications doivent être autorisées.


## V6.9.1 — Correctif Push + PayPal

- L'activation des notifications Push est maintenant directement dans la page 🔔 Notifications.
- État visible : activées / désactivées / iPhone non installé sur l'écran d'accueil.
- Bouton de notification test après activation.
- Restauration du gros bouton jaune « Payer avec PayPal ».
- Un clic ouvre directement le PayPal de la Popote avec le montant choisi.
- Suppression définitive de l'ancien swipe cassé.


## V6.9.2 — Correctif activation Push

- Correction du template Notifications : le JavaScript n'est plus injecté dans le titre de page.
- Le script Push s'exécute maintenant après le chargement du contenu.
- Attente explicite de `navigator.serviceWorker.ready`.
- Le bouton « Activer les notifications » est désormais réellement connecté au script.
- Ajout de messages d'erreur plus clairs en cas de problème.


## V6.10 — Notifications utiles

- Push au membre lorsqu'un Popotier ajoute manuellement une dette, avec montant et motif.
- Push aux Popotiers uniquement lorsqu'un produit passe réellement d'un stock positif à 0.
- Suppression des alertes Push de stock faible : seule la rupture déclenche une notification.
- Bilan Push du classement du mois précédent avec position et total de consommations.
- 🥇 🥈 🥉 pour le podium, 🏆 pour les autres positions.
- Le bilan mensuel est idempotent : un membre ne le reçoit qu'une fois par mois.


## V6.10.1 — Classement et dettes Popotier

- Le classement mensuel additionne désormais :
  - les consommations du mois ;
  - les dettes manuelles ajoutées par le Popotier pendant le mois.
- Les paiements ne diminuent toujours pas le classement.
- La notification Push de classement de fin de mois utilise exactement le même calcul.


## V6.10.2 — Classement redesign

- Podium Top 3 en trois cartes distinctes.
- Le 1er est plus grand et placé au centre.
- La ligne de l'utilisateur connecté reste mise en évidence en jaune.
- Rappel « Ma position » juste sous le podium.
- Le dernier reçoit le badge « 🦀 Pince du mois 🦀 ».
- Les montants sont alignés à droite pour une lecture immédiate.


## V6.10.3 — Classement mobile optimisé

- Le 1er du podium occupe toute la largeur sur mobile.
- Les 2e et 3e sont affichés côte à côte dessous.
- Les noms restent horizontaux et lisibles.
- Les montants restent alignés à droite.
- La ligne de l'utilisateur reste mise en évidence en jaune.
- Le badge « 🦀 Pince du mois » est conservé.
- Sur les très petits écrans, les trois cartes passent en une colonne.
