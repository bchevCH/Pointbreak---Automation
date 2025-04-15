# PrestaShop to WordPress/WooCommerce Image Migration

Ce script permet la migration automatisée des images de produits d'un site PrestaShop vers un site WordPress/WooCommerce, avec une gestion avancée des métadonnées et du stock.

## Fonctionnalités

- Extraction des données produits depuis PrestaShop (nom, stock)
- Organisation hiérarchique des images par produit
- Renommage automatique des images selon le format `nom-produit-numero.jpg`
- Génération de rapports détaillés au format JSON
- Migration contrôlée vers WooCommerce
- Gestion des erreurs et logging complet

## Processus de Migration

Le script exécute la migration en trois phases distinctes :

1. **Extraction des données PrestaShop**
   - Connexion à la base de données PrestaShop
   - Récupération des noms de produits et stocks
   - Création de dossiers par produit
   - Téléchargement et organisation des images

2. **Génération du rapport**
   - Création d'un rapport JSON détaillé
   - Statistiques globales (nombre de produits, images, stock total)
   - Détails par produit (nom, nombre d'images, stock)

3. **Migration vers WooCommerce**
   - Proposition de migration après vérification des données
   - Upload contrôlé des images
   - Association des images aux produits WooCommerce

## Prérequis

- Python 3.7 ou supérieur
- Accès FTP au site PrestaShop
- Accès à la base de données PrestaShop
- Accès API au site WordPress/WooCommerce
- MySQL/MariaDB pour la connexion à la base de données PrestaShop

## Installation

1. Clonez le dépôt :
```bash
git clone [REPO_URL]
cd prestashop-wp-image-migrator
```

2. Installez les dépendances :
```bash
pip install -r requirements.txt
```

3. Configurez les variables d'environnement :
```bash
cp .env.example .env
```

4. Modifiez le fichier `.env` avec vos informations :
```env
# Configuration FTP PrestaShop
FTP_HOST=votre_serveur_ftp
FTP_USER=votre_utilisateur_ftp
FTP_PASS=votre_mot_de_passe_ftp
FTP_IMG_PATH=/chemin/vers/images

# Configuration WordPress/WooCommerce
WP_API_URL=https://votre-site.com/wp-json/wc/v3
WP_API_USER=votre_cle_api
WP_API_PASS=votre_secret_api

# Configuration Base de données PrestaShop
DB_HOST=localhost
DB_PORT=3306
DB_NAME=nom_base_prestashop
DB_USER=utilisateur_db
DB_PASS=mot_de_passe_db
DB_PREFIX=ps_
```

## Structure du Projet

```
.
├── config.py          # Configuration globale
├── exceptions.py      # Gestion des exceptions
├── migrator.py        # Script principal
├── requirements.txt   # Dépendances
├── .env              # Variables d'environnement
├── logs/             # Dossiers de logs
└── temp_images/      # Images temporaires
```

## Utilisation

1. Exécutez le script :
```bash
python migrator.py
```

2. Le script va :
   - Se connecter à la base de données PrestaShop
   - Extraire les données des produits
   - Créer des dossiers par produit
   - Télécharger et organiser les images
   - Générer un rapport JSON
   - Proposer la migration vers WooCommerce

## Rapports

Les rapports sont générés dans le dossier `logs/` avec :
- Un fichier de log par exécution
- Un rapport JSON détaillé contenant :
  ```json
  {
    "timestamp": "2024-04-14T12:00:00",
    "products": {
      "nom-produit": {
        "id": "123",
        "images": 3,
        "stock": 10,
        "folder": "/chemin/vers/dossier"
      }
    },
    "summary": {
      "total_products": 50,
      "total_images": 150,
      "total_stock": 500
    }
  }
  ```

## Gestion des Erreurs

Le script gère plusieurs types d'erreurs :
- Connexion à la base de données
- Connexion FTP
- Téléchargement d'images
- Upload vers WooCommerce
- Système de fichiers

Chaque erreur est :
- Loggée dans le fichier de log
- Incluse dans le rapport final
- Gérée de manière appropriée pour permettre la continuation du processus

## Sécurité

- Les informations sensibles sont stockées dans `.env`
- Les connexions sont sécurisées (FTP, API, Base de données)
- Les fichiers temporaires sont automatiquement supprimés
- Les mots de passe ne sont jamais affichés dans les logs

## Contribuer

Les contributions sont les bienvenues ! Pour contribuer :
1. Fork le projet
2. Créez une branche (`git checkout -b feature/AmazingFeature`)
3. Committez vos changements (`git commit -m 'Add some AmazingFeature'`)
4. Push vers la branche (`git push origin feature/AmazingFeature`)
5. Ouvrez une Pull Request

## Licence

Ce projet est sous licence MIT. Voir le fichier `LICENSE` pour plus de détails. 