"""
Script principal de migration d'images de PrestaShop vers WordPress/WooCommerce.
"""

import os
import json
import logging
import ftplib
import requests
import re
import shutil
import mysql.connector
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
from woocommerce import API

from config import (
    LOGS_DIR, TEMP_DIR, IMAGE_PATTERNS,
    FTP_CONFIG, API_CONFIG, LOG_CONFIG, DB_CONFIG
)
from exceptions import (
    ProductNotFoundError, FTPConnectionError,
    ImageUploadError, APIError, FileSystemError, DatabaseError
)

# Configuration du logger
logger = logging.getLogger(__name__)
logger.setLevel(LOG_CONFIG["level"])

# Configuration du handler de fichier
log_file = LOGS_DIR / f"migration_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
file_handler = logging.FileHandler(log_file)
file_handler.setFormatter(logging.Formatter(LOG_CONFIG["format"]))
logger.addHandler(file_handler)

# Configuration du handler console
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter(LOG_CONFIG["format"]))
logger.addHandler(console_handler)

class FTPHandler:
    """Gestionnaire de connexion et d'opérations FTP."""
    
    def __init__(self, host, user, password, base_path):
        """
        Initialise le gestionnaire FTP.

        Args:
            host (str): Adresse du serveur FTP
            user (str): Nom d'utilisateur FTP
            password (str): Mot de passe FTP
            base_path (str): Chemin de base des images
        """
        self.host = host
        self.user = user
        self.password = password
        self.base_path = base_path
        self.connection = None

    def __enter__(self):
        """Contexte d'entrée pour la connexion FTP."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Contexte de sortie pour la connexion FTP."""
        self.disconnect()

    def connect(self):
        """
        Établit la connexion FTP.

        Returns:
            bool: True si la connexion est réussie, False sinon

        Raises:
            FTPConnectionError: Si la connexion échoue
        """
        try:
            self.connection = ftplib.FTP(self.host, timeout=FTP_CONFIG["timeout"])
            self.connection.login(self.user, self.password)
            logger.info(f"Connexion FTP établie avec succès sur {self.host}")
            return True
        except Exception as error:
            raise FTPConnectionError(self.host, str(error))

    def disconnect(self):
        """Ferme la connexion FTP."""
        if self.connection:
            try:
                self.connection.quit()
                logger.info("Connexion FTP fermée")
            except Exception as error:
                logger.error(f"Erreur lors de la fermeture FTP: {error}")

    def get_product_images(self, product_id):
        """
        Récupère les images d'un produit depuis PrestaShop.

        Args:
            product_id (int): ID du produit

        Returns:
            tuple: (image_principale, images_secondaires)

        Raises:
            FileSystemError: Si la récupération des images échoue
        """
        try:
            # Construction du chemin du dossier
            product_id_str = str(product_id)
            folder_path = '/'.join(list(product_id_str))
            full_path = f"{self.base_path}{folder_path}/"
            
            # Liste des fichiers dans le dossier
            self.connection.cwd(full_path)
            files = self.connection.nlst()
            
            # Tri des images
            main_image = None
            additional_images = []
            
            for file in files:
                if file.endswith('.jpg'):
                    if re.match(IMAGE_PATTERNS["main"].format(product_id=product_id), file):
                        main_image = file
                    elif re.match(IMAGE_PATTERNS["additional"].format(product_id=product_id), file):
                        additional_images.append(file)
            
            # Tri des images secondaires par numéro
            additional_images.sort(key=lambda x: int(x.split('-')[1].split('.')[0]))
            
            return main_image, additional_images
        except Exception as error:
            raise FileSystemError("récupération des images", full_path, str(error))

    def download_image(self, image_path, local_path):
        """
        Télécharge une image depuis le serveur FTP.

        Args:
            image_path (str): Chemin de l'image sur le FTP
            local_path (str): Chemin local de destination

        Returns:
            bool: True si le téléchargement réussit, False sinon

        Raises:
            FileSystemError: Si le téléchargement échoue
        """
        try:
            with open(local_path, 'wb') as file:
                self.connection.retrbinary(f'RETR {image_path}', file.write)
            logger.info(f"Image téléchargée: {image_path}")
            return True
        except Exception as error:
            raise FileSystemError("téléchargement", image_path, str(error))

class WordPressHandler:
    """Gestionnaire de connexion et d'opérations WordPress/WooCommerce."""
    
    def __init__(self, api_url, consumer_key, consumer_secret):
        """
        Initialise le gestionnaire WordPress.

        Args:
            api_url (str): URL de l'API WordPress
            consumer_key (str): Clé API WooCommerce
            consumer_secret (str): Secret API WooCommerce
        """
        if not api_url or not consumer_key or not consumer_secret:
            logger.error("Configuration API WordPress/WooCommerce incomplète")
            raise ValueError("Les paramètres d'API WooCommerce sont requis (URL, clé, secret)")
            
        self.api_url = api_url
        self.wcapi = API(
            url=api_url,
            consumer_key=consumer_key,
            consumer_secret=consumer_secret,
            version="wc/v3",
            timeout=API_CONFIG["timeout"]
        )
        
        # Configuration des retries pour les requêtes
        self.session = requests.Session()
        retry_strategy = Retry(
            total=API_CONFIG["retry_attempts"],
            backoff_factor=API_CONFIG["retry_backoff_factor"],
            status_forcelist=API_CONFIG["retry_status_forcelist"],
            allowed_methods=["GET", "POST", "PUT", "DELETE"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def get_product_by_name(self, product_name):
        """
        Récupère un produit WordPress par son nom.

        Args:
            product_name (str): Nom du produit

        Returns:
            dict: Données du produit ou None si non trouvé

        Raises:
            APIError: Si la requête API échoue
        """
        if not product_name:
            logger.warning("Nom de produit vide fourni")
            return None
            
        try:
            response = self.wcapi.get(
                "products",
                params={"search": product_name, "per_page": 20},
                timeout=API_CONFIG["timeout"]
            )
            
            if response.status_code == 200:
                products = response.json()
                for product in products:
                    if product['name'].lower() == product_name.lower():
                        return product
                        
                logger.warning(f"Produit '{product_name}' non trouvé dans WooCommerce")
                return None
            else:
                raise APIError("products", response.status_code, response.text)
        except requests.exceptions.Timeout:
            logger.error(f"Timeout lors de la recherche du produit '{product_name}'")
            raise APIError("products", 0, "Timeout de la requête")
        except requests.exceptions.RequestException as error:
            logger.error(f"Erreur lors de la recherche du produit '{product_name}': {error}")
            raise APIError("products", 0, str(error))

    def check_image_exists(self, image_name):
        """
        Vérifie si une image existe déjà dans la médiathèque.

        Args:
            image_name (str): Nom de l'image

        Returns:
            bool: True si l'image existe, False sinon

        Raises:
            APIError: Si la requête API échoue
        """
        if not image_name:
            logger.warning("Nom d'image vide fourni")
            return False
            
        try:
            response = self.wcapi.get(
                "media",
                params={
                    "search": image_name,
                    "per_page": 5
                },
                timeout=API_CONFIG["timeout"]
            )
            
            if response.status_code == 200:
                media = response.json()
                if media:
                    for item in media:
                        if item['title']['rendered'].lower() == image_name.lower():
                            logger.info(f"Image trouvée dans la médiathèque: {image_name}")
                            return True
                return False
            else:
                raise APIError("media", response.status_code, response.text)
        except requests.exceptions.Timeout:
            logger.error(f"Timeout lors de la vérification d'image '{image_name}'")
            raise APIError("media", 0, "Timeout de la requête")
        except requests.exceptions.RequestException as error:
            logger.error(f"Erreur lors de la vérification d'image '{image_name}': {error}")
            raise APIError("media", 0, str(error))

    def upload_image(self, image_path, product_id, is_main_image=False):
        """
        Upload une image vers WordPress et l'associe à un produit.

        Args:
            image_path (str): Chemin local de l'image
            product_id (int): ID du produit
            is_main_image (bool): True si image principale

        Returns:
            bool: True si l'upload réussit

        Raises:
            ImageUploadError: Si l'upload échoue
            APIError: Si la requête API échoue
            FileNotFoundError: Si le fichier image n'existe pas
        """
        if not os.path.exists(image_path):
            logger.error(f"Fichier non trouvé: {image_path}")
            raise FileNotFoundError(f"Le fichier image n'existe pas: {image_path}")
            
        try:
            # Vérification de l'existence de l'image
            image_name = os.path.basename(image_path)
            if self.check_image_exists(image_name):
                logger.info(f"Image déjà existante: {image_name}")
                return True

            # Upload de l'image avec métadonnées
            with open(image_path, 'rb') as file:
                files = {'file': file}
                data = {
                    'title': image_name,
                    'alt_text': image_name.split('.')[0],
                    'post': product_id
                }
                
                logger.info(f"Début de l'upload de {image_name} pour le produit {product_id}")
                response = self.session.post(
                    f"{self.api_url}/media",
                    auth=(self.wcapi.consumer_key, self.wcapi.consumer_secret),
                    files=files,
                    data=data,
                    timeout=API_CONFIG["timeout"] * 2  # Timeout plus long pour les uploads
                )
            
            if response.status_code == 201:
                image_id = response.json()['id']
                logger.info(f"Image uploadée avec succès: {image_name} (ID: {image_id})")
                
                # Récupération des images actuelles du produit
                product_response = self.wcapi.get(
                    f"products/{product_id}",
                    timeout=API_CONFIG["timeout"]
                )
                
                if product_response.status_code != 200:
                    raise APIError(f"products/{product_id}", product_response.status_code, product_response.text)
                    
                product = product_response.json()
                current_images = product.get('images', [])
                
                # Préparation des nouvelles images
                if is_main_image:
                    new_images = [{"id": image_id}] + current_images
                else:
                    new_images = current_images + [{"id": image_id}]
                
                # Mise à jour du produit
                update_data = {"images": new_images}
                update_response = self.wcapi.put(
                    f"products/{product_id}",
                    update_data,
                    timeout=API_CONFIG["timeout"]
                )
                
                if update_response.status_code not in [200, 201]:
                    raise APIError(f"products/{product_id}", update_response.status_code, update_response.text)
                    
                logger.info(f"Image associée au produit {product_id} (principale: {is_main_image})")
                return True
            else:
                raise APIError("media", response.status_code, response.text)
        except requests.exceptions.Timeout:
            logger.error(f"Timeout lors de l'upload de l'image '{image_path}'")
            raise ImageUploadError(image_path, "Timeout de la requête")
        except requests.exceptions.RequestException as error:
            logger.error(f"Erreur réseau lors de l'upload de l'image '{image_path}': {error}")
            raise ImageUploadError(image_path, str(error))
        except Exception as error:
            logger.error(f"Erreur inattendue lors de l'upload de l'image '{image_path}': {error}")
            raise ImageUploadError(image_path, str(error))

    def get_product_stock(self, product_id):
        """
        Récupère la quantité en stock d'un produit.

        Args:
            product_id (int): ID du produit

        Returns:
            int: Quantité en stock

        Raises:
            APIError: Si la requête API échoue
        """
        try:
            response = self.wcapi.get(
                f"products/{product_id}",
                timeout=API_CONFIG["timeout"]
            )
            
            if response.status_code != 200:
                raise APIError(f"products/{product_id}", response.status_code, response.text)
                
            product = response.json()
            return product.get('stock_quantity', 0)
        except requests.exceptions.Timeout:
            logger.error(f"Timeout lors de la récupération du stock du produit {product_id}")
            raise APIError(f"products/{product_id}", 0, "Timeout de la requête")
        except requests.exceptions.RequestException as error:
            logger.error(f"Erreur lors de la récupération du stock du produit {product_id}: {error}")
            raise APIError(f"products/{product_id}", 0, str(error))

class ImageMigrator:
    """Gestionnaire principal de la migration d'images."""
    
    def __init__(self):
        """Initialise le migrator avec les configurations nécessaires."""
        load_dotenv()
        self.ftp_handler = FTPHandler(
            FTP_CONFIG["host"],
            FTP_CONFIG["user"],
            FTP_CONFIG["password"],
            FTP_CONFIG["base_path"]
        )
        self.wp_handler = WordPressHandler(
            API_CONFIG["url"],
            API_CONFIG["consumer_key"],
            API_CONFIG["consumer_secret"]
        )
        self.migration_report = {
            'timestamp': datetime.now().isoformat(),
            'products': {},
            'summary': {
                'total_products': 0,
                'total_images': 0,
                'successful_migrations': 0,
                'failed_migrations': 0
            }
        }
        self.products_data = {}
        self.db_connection = None

    @contextmanager
    def db_cursor(self):
        """
        Gestionnaire de contexte pour les curseurs de base de données.
        
        Yields:
            mysql.connector.cursor: Un curseur de base de données
            
        Raises:
            DatabaseError: Si une erreur de base de données se produit
        """
        if not self.db_connection or not self.db_connection.is_connected():
            self._connect_db()

        cursor = None
        try:
            cursor = self.db_connection.cursor(dictionary=True)
            yield cursor
        except mysql.connector.Error as e:
            logger.error(f"Erreur de base de données: {e}")
            raise DatabaseError(str(e))
        finally:
            if cursor:
                cursor.close()

    def _connect_db(self):
        """
        Établit la connexion à la base de données PrestaShop.
        
        Raises:
            DatabaseError: Si la connexion à la base de données échoue
        """
        try:
            if self.db_connection and self.db_connection.is_connected():
                return

            self.db_connection = mysql.connector.connect(
                host=DB_CONFIG['host'],
                port=DB_CONFIG['port'],
                database=DB_CONFIG['database'],
                user=DB_CONFIG['user'],
                password=DB_CONFIG['password'],
                connection_timeout=10,
                autocommit=False,  # Désactiver l'autocommit pour utiliser les transactions
                use_pure=True,     # Utiliser l'implémentation pure Python pour plus de stabilité
                charset='utf8mb4'  # Support des caractères spéciaux
            )
            logger.info("Connexion à la base de données PrestaShop établie")
        except mysql.connector.Error as e:
            logger.error(f"Erreur de connexion à la base de données: {e}")
            raise DatabaseError(f"Erreur de connexion à la base de données: {e}")

    def _get_product_name(self, product_id):
        """
        Récupère le nom du produit depuis la base de données PrestaShop.
        
        Args:
            product_id (str): ID du produit
            
        Returns:
            str: Nom du produit ou None si non trouvé
            
        Raises:
            DatabaseError: Si une erreur de base de données se produit
        """
        try:
            with self.db_cursor() as cursor:
                # Requête pour récupérer le nom du produit
                query = f"""
                    SELECT pl.name 
                    FROM {DB_CONFIG['prefix']}product_lang pl
                    WHERE pl.id_product = %s
                    AND pl.id_lang = 1
                    LIMIT 1
                """
                
                cursor.execute(query, (product_id,))
                result = cursor.fetchone()
                
                if result:
                    # Nettoyage du nom de produit pour éviter les problèmes de fichiers
                    clean_name = re.sub(r'[\\/*?:"<>|]', '', result['name'])
                    return clean_name
                else:
                    logger.warning(f"Produit {product_id} non trouvé dans la base de données")
                    return None
                    
        except Exception as e:
            logger.error(f"Erreur lors de la récupération du nom du produit {product_id}: {e}")
            return None

    def _get_product_stock(self, product_id):
        """
        Récupère le stock du produit depuis la base de données PrestaShop.
        
        Args:
            product_id (str): ID du produit
            
        Returns:
            int: Quantité en stock ou 0 si non trouvé
            
        Raises:
            DatabaseError: Si une erreur de base de données se produit
        """
        try:
            with self.db_cursor() as cursor:
                # Requête pour récupérer le stock du produit
                query = f"""
                    SELECT sa.quantity 
                    FROM {DB_CONFIG['prefix']}stock_available sa
                    WHERE sa.id_product = %s
                    AND sa.id_product_attribute = 0
                    LIMIT 1
                """
                
                cursor.execute(query, (product_id,))
                result = cursor.fetchone()
                
                if result:
                    return int(result['quantity'])
                else:
                    logger.warning(f"Stock non trouvé pour le produit {product_id}")
                    return 0
                    
        except Exception as e:
            logger.error(f"Erreur lors de la récupération du stock du produit {product_id}: {e}")
            return 0

    def close_connections(self):
        """Ferme toutes les connexions ouvertes."""
        if self.db_connection:
            try:
                self.db_connection.close()
                logger.info("Connexion à la base de données fermée")
            except Exception as e:
                logger.error(f"Erreur lors de la fermeture de la connexion à la base de données: {e}")

    def __del__(self):
        """Ferme la connexion à la base de données lors de la destruction de l'objet."""
        self.close_connections()

    def extract_prestashop_data(self):
        """
        Extrait les données des produits depuis PrestaShop.
        
        Returns:
            bool: True si l'extraction a réussi, False sinon
        """
        if not FTP_CONFIG.get("host") or not FTP_CONFIG.get("user") or not FTP_CONFIG.get("password"):
            logger.error("Configuration FTP incomplète")
            return False
        
        try:
            with self.ftp_handler as ftp:
                # Liste des dossiers de produits
                product_dirs = ftp.connection.nlst()
                products_processed = 0
                
                for product_dir in product_dirs:
                    if re.match(r'^\d+$', product_dir):  # Vérifie si c'est un dossier de produit
                        try:
                            # Récupération du nom du produit
                            product_name = self._get_product_name(product_dir)
                            if not product_name:
                                logger.warning(f"Nom de produit non trouvé pour l'ID {product_dir}, ignoré")
                                continue

                            # Création du dossier pour le produit
                            product_folder = TEMP_DIR / product_name
                            product_folder.mkdir(parents=True, exist_ok=True)

                            # Récupération des images
                            main_image, additional_images = ftp.get_product_images(product_dir)
                            all_images = [main_image] if main_image else []
                            all_images.extend(additional_images if additional_images else [])
                            
                            if not all_images:
                                logger.warning(f"Aucune image trouvée pour le produit {product_name}")
                                continue
                                
                            stock = self._get_product_stock(product_dir)

                            # Organisation des images
                            downloaded_images = 0
                            for idx, image in enumerate(all_images, 1):
                                if image:
                                    local_path = product_folder / f"{product_name}-{idx}.jpg"
                                    if ftp.download_image(image, str(local_path)):
                                        downloaded_images += 1

                            # Stockage des données du produit
                            self.products_data[product_name] = {
                                'id': product_dir,
                                'images': downloaded_images,
                                'stock': stock,
                                'folder': str(product_folder)
                            }

                            logger.info(f"Données extraites pour le produit: {product_name} ({downloaded_images} images)")
                            products_processed += 1

                        except Exception as e:
                            logger.error(f"Erreur lors de l'extraction du produit {product_dir}: {e}")
                            
                logger.info(f"Extraction terminée: {products_processed} produits traités")
                return products_processed > 0

        except FTPConnectionError as e:
            logger.error(f"Erreur de connexion FTP: {e}")
            return False
        except Exception as e:
            logger.error(f"Erreur lors de l'extraction des données: {e}")
            return False

    def generate_report(self):
        """Génère un rapport JSON des données extraites."""
        report_path = LOGS_DIR / f"extraction_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        report_data = {
            'timestamp': datetime.now().isoformat(),
            'products': self.products_data,
            'summary': {
                'total_products': len(self.products_data),
                'total_images': sum(p['images'] for p in self.products_data.values()),
                'total_stock': sum(p['stock'] for p in self.products_data.values())
            }
        }

        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(report_data, f, ensure_ascii=False, indent=4)

        logger.info(f"Rapport généré: {report_path}")
        return report_path

    def propose_woocommerce_upload(self):
        """Propose l'upload des images vers WooCommerce."""
        if not self.products_data:
            logger.warning("Aucune donnée à migrer vers WooCommerce")
            return

        print("\n=== Proposition de migration vers WooCommerce ===")
        print(f"Nombre de produits à migrer: {len(self.products_data)}")
        print("\nVoulez-vous procéder à la migration vers WooCommerce? (y/n)")
        
        response = input().lower()
        if response == 'y':
            self.migrate_to_woocommerce()
        else:
            logger.info("Migration vers WooCommerce annulée")

    def migrate_to_woocommerce(self):
        """
        Effectue la migration des images vers WooCommerce.
        
        Returns:
            bool: True si la migration a réussi, False sinon
        """
        if not self.products_data:
            logger.warning("Aucune donnée à migrer vers WooCommerce")
            return False
        
        total_products = len(self.products_data)
        success_count = 0
        failed_count = 0
        
        logger.info(f"Début de la migration vers WooCommerce: {total_products} produits")
        
        for product_name, data in self.products_data.items():
            try:
                product_folder = Path(data['folder'])
                images = sorted(product_folder.glob(f"{product_name}-*.jpg"))
                
                if not images:
                    logger.warning(f"Aucune image trouvée pour le produit {product_name}")
                    continue
                    
                images_success = 0
                for idx, image_path in enumerate(images, 1):
                    is_main = idx == 1
                    try:
                        if self.wp_handler.upload_image(str(image_path), data['id'], is_main_image=is_main):
                            images_success += 1
                            logger.info(f"Image {idx}/{len(images)} du produit {product_name} migrée avec succès")
                    except Exception as e:
                        logger.error(f"Échec de l'upload de l'image {idx} pour {product_name}: {e}")
                
                if images_success == len(images):
                    logger.info(f"Produit {product_name}: {images_success}/{len(images)} images migrées avec succès")
                    success_count += 1
                elif images_success > 0:
                    logger.warning(f"Produit {product_name}: {images_success}/{len(images)} images migrées partiellement")
                    success_count += 1
                else:
                    logger.error(f"Produit {product_name}: échec total de la migration des images")
                    failed_count += 1
                    
            except Exception as e:
                logger.error(f"Erreur lors de la migration du produit {product_name}: {e}")
                failed_count += 1
        
        self.migration_report['summary']['successful_migrations'] = success_count
        self.migration_report['summary']['failed_migrations'] = failed_count
        
        logger.info(f"Migration terminée: {success_count} produits réussis, {failed_count} produits échoués")
        return success_count > 0

def main():
    """Fonction principale d'exécution."""
    start_time = datetime.now()
    logger.info(f"Début du processus de migration: {start_time}")
    
    # Création des dossiers temporaires s'ils n'existent pas
    for directory in [LOGS_DIR, TEMP_DIR]:
        try:
            directory.mkdir(exist_ok=True, parents=True)
        except Exception as e:
            logger.error(f"Erreur lors de la création du dossier {directory}: {e}")
            print(f"Erreur critique: Impossible de créer le dossier {directory}")
            return
    
    migrator = None
    success = False
    
    try:
        migrator = ImageMigrator()
        
        # Phase 1: Extraction des données PrestaShop
        logger.info("Début de l'extraction des données PrestaShop")
        extraction_success = migrator.extract_prestashop_data()
        
        if not extraction_success:
            logger.error("L'extraction des données a échoué ou n'a trouvé aucun produit")
            print("\nAucun produit n'a pu être extrait. Vérifiez les logs pour plus de détails.")
            return
        
        # Phase 2: Génération du rapport
        logger.info("Génération du rapport d'extraction")
        report_path = migrator.generate_report()
        print(f"\nRapport d'extraction généré: {report_path}")
        print(f"\nNombre de produits extraits: {len(migrator.products_data)}")
        print(f"Nombre total d'images: {sum(p['images'] for p in migrator.products_data.values())}")
        
        # Phase 3: Proposition de migration WooCommerce
        print("\n=== Proposition de migration vers WooCommerce ===")
        print("Voulez-vous procéder à la migration vers WooCommerce? (y/n)")
        
        response = input().lower()
        if response == 'y':
            logger.info("Début de la migration vers WooCommerce")
            migration_success = migrator.migrate_to_woocommerce()
            
            if migration_success:
                print("\nMigration terminée avec succès!")
                print(f"Produits migrés: {migrator.migration_report['summary']['successful_migrations']}")
                print(f"Produits échoués: {migrator.migration_report['summary']['failed_migrations']}")
                success = True
            else:
                print("\nLa migration a échoué. Consultez les logs pour plus de détails.")
        else:
            logger.info("Migration vers WooCommerce annulée par l'utilisateur")
            print("\nMigration annulée.")
            success = True  # L'annulation est considérée comme un succès du programme
        
    except KeyboardInterrupt:
        logger.warning("Interruption utilisateur détectée")
        print("\nOpération interrompue par l'utilisateur.")
    except Exception as e:
        logger.error(f"Erreur critique lors de l'exécution: {e}", exc_info=True)
        print(f"\nUne erreur critique est survenue: {e}")
    finally:
        # Nettoyage et fermeture des ressources
        if migrator:
            try:
                migrator.close_connections()
            except Exception as e:
                logger.error(f"Erreur lors de la fermeture des connexions: {e}")
                
        # Nettoyage des fichiers temporaires
        if TEMP_DIR.exists():
            try:
                shutil.rmtree(TEMP_DIR)
                logger.info("Nettoyage des fichiers temporaires effectué")
            except Exception as e:
                logger.error(f"Erreur lors du nettoyage des fichiers temporaires: {e}")
        
        end_time = datetime.now()
        duration = end_time - start_time
        logger.info(f"Fin du processus de migration: {end_time} (durée: {duration})")
        
        if success:
            print(f"\nOpération terminée en {duration}")
        else:
            print("\nOpération terminée avec des erreurs. Consultez les logs pour plus de détails.")

if __name__ == "__main__":
    main() 