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
    ImageUploadError, APIError, FileSystemError
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
        self.api_url = api_url
        self.wcapi = API(
            url=api_url,
            consumer_key=consumer_key,
            consumer_secret=consumer_secret,
            version="wc/v3"
        )
        
        # Configuration des retries pour les requêtes
        self.session = requests.Session()
        retry_strategy = Retry(
            total=API_CONFIG["retry_attempts"],
            backoff_factor=API_CONFIG["retry_backoff_factor"],
            status_forcelist=API_CONFIG["retry_status_forcelist"]
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
        try:
            response = self.wcapi.get(
                "products",
                params={"search": product_name},
                timeout=API_CONFIG["timeout"]
            )
            
            if response.status_code == 200:
                products = response.json()
                for product in products:
                    if product['name'].lower() == product_name.lower():
                        return product
            else:
                raise APIError("products", response.status_code, response.text)
                
            return None
        except Exception as error:
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
        try:
            response = self.wcapi.get(
                "media",
                params={
                    "search": image_name,
                    "per_page": 1
                },
                timeout=API_CONFIG["timeout"]
            )
            
            if response.status_code == 200:
                media = response.json()
                if media:
                    for item in media:
                        if item['title']['rendered'].lower() == image_name.lower():
                            return True
            else:
                raise APIError("media", response.status_code, response.text)
                
            return False
        except Exception as error:
            raise APIError("media", 0, str(error))

    def upload_image(self, image_path, product_id, is_main_image=False):
        """
        Upload une image vers WordPress et l'associe à un produit.

        Args:
            image_path (str): Chemin local de l'image
            product_id (int): ID du produit
            is_main_image (bool): True si image principale

        Returns:
            bool: True si l'upload réussit, False sinon

        Raises:
            ImageUploadError: Si l'upload échoue
            APIError: Si la requête API échoue
        """
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
                    'post': product_id
                }
                response = self.session.post(
                    f"{self.api_url}/media",
                    auth=(self.wcapi.consumer_key, self.wcapi.consumer_secret),
                    files=files,
                    data=data,
                    timeout=API_CONFIG["timeout"]
                )
            
            if response.status_code == 201:
                image_id = response.json()['id']
                
                # Récupération des images actuelles du produit
                product = self.wcapi.get(
                    f"products/{product_id}",
                    timeout=API_CONFIG["timeout"]
                ).json()
                current_images = product.get('images', [])
                
                # Préparation des nouvelles images
                if is_main_image:
                    new_images = [{"id": image_id}] + current_images
                else:
                    new_images = current_images + [{"id": image_id}]
                
                # Mise à jour du produit
                update_data = {"images": new_images}
                self.wcapi.put(
                    f"products/{product_id}",
                    update_data,
                    timeout=API_CONFIG["timeout"]
                )
                logger.info(f"Image associée au produit {product_id} (principale: {is_main_image})")
                return True
            else:
                raise APIError("media", response.status_code, response.text)
        except Exception as error:
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
            product = self.wcapi.get(
                f"products/{product_id}",
                timeout=API_CONFIG["timeout"]
            ).json()
            return product.get('stock_quantity', 0)
        except Exception as error:
            raise APIError(f"products/{product_id}", 0, str(error))

class ImageMigrator:
    """Gestionnaire principal de la migration d'images."""
    
    def __init__(self):
        """Initialise le migrator avec les configurations nécessaires."""
        load_dotenv()
        self.ftp_handler = FTPHandler(
            os.getenv('FTP_HOST'),
            os.getenv('FTP_USER'),
            os.getenv('FTP_PASS'),
            os.getenv('FTP_IMG_PATH')
        )
        self.wp_handler = WordPressHandler(
            os.getenv('WP_API_URL'),
            os.getenv('WP_API_USER'),
            os.getenv('WP_API_PASS')
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

    def _connect_db(self):
        """Établit la connexion à la base de données PrestaShop."""
        try:
            self.db_connection = mysql.connector.connect(
                host=DB_CONFIG['host'],
                port=DB_CONFIG['port'],
                database=DB_CONFIG['database'],
                user=DB_CONFIG['user'],
                password=DB_CONFIG['password']
            )
            logger.info("Connexion à la base de données PrestaShop établie")
        except Exception as e:
            logger.error(f"Erreur de connexion à la base de données: {str(e)}")
            raise

    def _get_product_name(self, product_id):
        """
        Récupère le nom du produit depuis la base de données PrestaShop.
        
        Args:
            product_id (str): ID du produit
            
        Returns:
            str: Nom du produit ou None si non trouvé
        """
        try:
            if not self.db_connection:
                self._connect_db()

            cursor = self.db_connection.cursor(dictionary=True)
            
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
            cursor.close()
            
            if result:
                return result['name']
            else:
                logger.warning(f"Produit {product_id} non trouvé dans la base de données")
                return None
                
        except Exception as e:
            logger.error(f"Erreur lors de la récupération du nom du produit {product_id}: {str(e)}")
            return None

    def _get_product_stock(self, product_id):
        """
        Récupère le stock du produit depuis la base de données PrestaShop.
        
        Args:
            product_id (str): ID du produit
            
        Returns:
            int: Quantité en stock ou 0 si non trouvé
        """
        try:
            if not self.db_connection:
                self._connect_db()

            cursor = self.db_connection.cursor(dictionary=True)
            
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
            cursor.close()
            
            if result:
                return int(result['quantity'])
            else:
                logger.warning(f"Stock non trouvé pour le produit {product_id}")
                return 0
                
        except Exception as e:
            logger.error(f"Erreur lors de la récupération du stock du produit {product_id}: {str(e)}")
            return 0

    def __del__(self):
        """Ferme la connexion à la base de données lors de la destruction de l'objet."""
        if self.db_connection:
            self.db_connection.close()
            logger.info("Connexion à la base de données fermée")

    def extract_prestashop_data(self):
        """Extrait les données des produits depuis PrestaShop."""
        try:
            with self.ftp_handler as ftp:
                # Liste des dossiers de produits
                product_dirs = ftp.connection.nlst()
                for product_dir in product_dirs:
                    if re.match(r'^\d+$', product_dir):  # Vérifie si c'est un dossier de produit
                        try:
                            # Récupération du nom du produit
                            product_name = self._get_product_name(product_dir)
                            if not product_name:
                                continue

                            # Création du dossier pour le produit
                            product_folder = TEMP_DIR / product_name
                            product_folder.mkdir(parents=True, exist_ok=True)

                            # Récupération des images
                            images = ftp.get_product_images(product_dir)
                            stock = self._get_product_stock(product_dir)

                            # Organisation des images
                            for idx, image in enumerate(images, 1):
                                local_path = product_folder / f"{product_name}-{idx}.jpg"
                                ftp.download_image(image, local_path)

                            # Stockage des données du produit
                            self.products_data[product_name] = {
                                'id': product_dir,
                                'images': len(images),
                                'stock': stock,
                                'folder': str(product_folder)
                            }

                            logger.info(f"Données extraites pour le produit: {product_name}")

                        except Exception as e:
                            logger.error(f"Erreur lors de l'extraction du produit {product_dir}: {str(e)}")

        except Exception as e:
            logger.error(f"Erreur lors de l'extraction des données: {str(e)}")

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
        """Effectue la migration des images vers WooCommerce."""
        for product_name, data in self.products_data.items():
            try:
                product_folder = Path(data['folder'])
                images = sorted(product_folder.glob(f"{product_name}-*.jpg"))
                
                for idx, image_path in enumerate(images, 1):
                    is_main = idx == 1
                    self.wp_handler.upload_image(
                        str(image_path),
                        data['id'],
                        is_main_image=is_main
                    )
                    logger.info(f"Image {idx} du produit {product_name} migrée avec succès")

            except Exception as e:
                logger.error(f"Erreur lors de la migration du produit {product_name}: {str(e)}")

def main():
    """Fonction principale d'exécution."""
    migrator = ImageMigrator()
    
    try:
        # Phase 1: Extraction des données PrestaShop
        logger.info("Début de l'extraction des données PrestaShop")
        migrator.extract_prestashop_data()
        
        # Phase 2: Génération du rapport
        logger.info("Génération du rapport d'extraction")
        report_path = migrator.generate_report()
        print(f"\nRapport d'extraction généré: {report_path}")
        
        # Phase 3: Proposition de migration WooCommerce
        migrator.propose_woocommerce_upload()
        
    except Exception as e:
        logger.error(f"Erreur lors de l'exécution: {str(e)}")
    finally:
        # Nettoyage des fichiers temporaires
        if TEMP_DIR.exists():
            shutil.rmtree(TEMP_DIR)
            logger.info("Nettoyage des fichiers temporaires effectué")

if __name__ == "__main__":
    main() 