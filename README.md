
# Popote Bravo — V4

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
