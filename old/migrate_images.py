import os
import logging
import ftplib
import requests
import re
from dotenv import load_dotenv
from woocommerce import API

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('migration.log'),
        logging.StreamHandler()
    ]
)

# Chargement des variables d'environnement
load_dotenv()

class ImageMigrator:
    def __init__(self):
        # Configuration FTP
        self.ftp_host = os.getenv('FTP_HOST')
        self.ftp_user = os.getenv('FTP_USER')
        self.ftp_pass = os.getenv('FTP_PASS')
        self.ftp_img_path = os.getenv('FTP_IMG_PATH', '/img/p/')
        
        # Configuration WordPress
        self.wp_url = os.getenv('WP_API_URL')
        self.wp_user = os.getenv('WP_API_USER')
        self.wp_pass = os.getenv('WP_API_PASS')
        
        # Initialisation de l'API WooCommerce
        self.wcapi = API(
            url=self.wp_url,
            consumer_key=self.wp_user,
            consumer_secret=self.wp_pass,
            version="wc/v3"
        )

    def connect_ftp(self):
        """Établit la connexion FTP avec le serveur PrestaShop"""
        try:
            ftp = ftplib.FTP(self.ftp_host)
            ftp.login(self.ftp_user, self.ftp_pass)
            logging.info("Connexion FTP établie avec succès")
            return ftp
        except Exception as e:
            logging.error(f"Erreur de connexion FTP: {str(e)}")
            raise

    def get_wordpress_product_by_name(self, product_name):
        """Récupère un produit WordPress par son nom"""
        try:
            response = self.wcapi.get("products", params={"search": product_name})
            if response.status_code == 200:
                products = response.json()
                for product in products:
                    if product['name'].lower() == product_name.lower():
                        return product
            return None
        except Exception as e:
            logging.error(f"Erreur lors de la recherche du produit: {str(e)}")
            return None

    def download_image(self, ftp, image_path, local_path):
        """Télécharge une image depuis le serveur FTP"""
        try:
            with open(local_path, 'wb') as f:
                ftp.retrbinary(f'RETR {image_path}', f.write)
            logging.info(f"Image téléchargée: {image_path}")
            return True
        except Exception as e:
            logging.error(f"Erreur lors du téléchargement de l'image: {str(e)}")
            return False

    def upload_to_wordpress(self, image_path, product_id, is_main_image=False):
        """Upload une image vers WordPress et l'associe à un produit"""
        try:
            # Upload de l'image
            with open(image_path, 'rb') as f:
                files = {'file': f}
                response = requests.post(
                    f"{self.wp_url}/media",
                    auth=(self.wp_user, self.wp_pass),
                    files=files
                )
            
            if response.status_code == 201:
                image_id = response.json()['id']
                
                # Récupération des images actuelles du produit
                product = self.wcapi.get(f"products/{product_id}").json()
                current_images = product.get('images', [])
                
                # Préparation des nouvelles images
                if is_main_image:
                    # L'image principale devient la première
                    new_images = [{"id": image_id}] + current_images
                else:
                    # Les images secondaires sont ajoutées à la fin
                    new_images = current_images + [{"id": image_id}]
                
                # Mise à jour du produit avec les nouvelles images
                update_data = {"images": new_images}
                self.wcapi.put(f"products/{product_id}", update_data)
                logging.info(f"Image associée au produit {product_id} (principale: {is_main_image})")
                return True
            return False
        except Exception as e:
            logging.error(f"Erreur lors de l'upload de l'image: {str(e)}")
            return False

    def get_product_images(self, ftp, product_id):
        """Récupère toutes les images d'un produit depuis PrestaShop"""
        try:
            # Structure des dossiers PrestaShop pour les images
            # Exemple: /img/p/1/2/3/123.jpg (image principale)
            #          /img/p/1/2/3/123-1.jpg (image secondaire)
            
            # Construction du chemin du dossier
            product_id_str = str(product_id)
            folder_path = '/'.join(list(product_id_str))
            full_path = f"{self.ftp_img_path}{folder_path}/"
            
            # Liste des fichiers dans le dossier
            ftp.cwd(full_path)
            files = ftp.nlst()
            
            # Tri des images
            main_image = None
            additional_images = []
            
            for file in files:
                if file.endswith('.jpg'):
                    if re.match(f"^{product_id}\.jpg$", file):
                        main_image = file
                    elif re.match(f"^{product_id}-\d+\.jpg$", file):
                        additional_images.append(file)
            
            # Tri des images secondaires par numéro
            additional_images.sort(key=lambda x: int(x.split('-')[1].split('.')[0]))
            
            return main_image, additional_images
        except Exception as e:
            logging.error(f"Erreur lors de la récupération des images: {str(e)}")
            return None, []

    def migrate_product_images(self, product_name):
        """Migre les images d'un produit spécifique"""
        try:
            # Récupération du produit WordPress
            product = self.get_wordpress_product_by_name(product_name)
            if not product:
                logging.warning(f"Produit non trouvé: {product_name}")
                return False

            # Connexion FTP
            ftp = self.connect_ftp()
            
            # Création du dossier temporaire pour les images
            temp_dir = "temp_images"
            os.makedirs(temp_dir, exist_ok=True)

            try:
                # Récupération des images du produit
                main_image, additional_images = self.get_product_images(ftp, product['id'])
                
                if not main_image and not additional_images:
                    logging.warning(f"Aucune image trouvée pour le produit {product_name}")
                    return False

                # Migration de l'image principale
                if main_image:
                    local_path = os.path.join(temp_dir, main_image)
                    if self.download_image(ftp, main_image, local_path):
                        self.upload_to_wordpress(local_path, product['id'], is_main_image=True)
                
                # Migration des images secondaires
                for image in additional_images:
                    local_path = os.path.join(temp_dir, image)
                    if self.download_image(ftp, image, local_path):
                        self.upload_to_wordpress(local_path, product['id'], is_main_image=False)
                
                return True
            finally:
                ftp.quit()
                # Nettoyage des fichiers temporaires
                for file in os.listdir(temp_dir):
                    os.remove(os.path.join(temp_dir, file))
                os.rmdir(temp_dir)

        except Exception as e:
            logging.error(f"Erreur lors de la migration des images: {str(e)}")
            return False

def main():
    """Fonction principale pour tester la migration"""
    migrator = ImageMigrator()
    
    # Liste de test avec 2 produits fictifs
    test_products = [
        "Produit Test 1",
        "Produit Test 2"
    ]
    
    for product in test_products:
        logging.info(f"Début de la migration pour le produit: {product}")
        success = migrator.migrate_product_images(product)
        if success:
            logging.info(f"Migration réussie pour {product}")
        else:
            logging.error(f"Échec de la migration pour {product}")

if __name__ == "__main__":
    main() 