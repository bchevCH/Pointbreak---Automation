"""
Configuration globale du projet de migration d'images.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Charger les variables d'environnement au début
load_dotenv()

# Chemins et dossiers
BASE_DIR = Path(__file__).parent.absolute()
LOGS_DIR = BASE_DIR / "logs"
TEMP_DIR = BASE_DIR / "temp_images"

# Patterns de fichiers
IMAGE_PATTERNS = {
    "main": r"^{product_id}\.jpg$",
    "additional": r"^{product_id}-\d+\.jpg$"
}

# Configuration FTP
FTP_CONFIG = {
    "base_path": "/img/p/",
    "timeout": 30
}

# Configuration API
API_CONFIG = {
    "timeout": 30,
    "retry_attempts": 3,
    "retry_backoff_factor": 0.5,
    "retry_status_forcelist": [500, 502, 503, 504]
}

# Configuration des logs
LOG_CONFIG = {
    "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    "date_format": "%Y-%m-%d %H:%M:%S",
    "level": "INFO"
}

# Configuration de la base de données PrestaShop
DB_CONFIG = {
    "host": os.getenv('DB_HOST', 'localhost'),
    "port": int(os.getenv('DB_PORT', '3306')),
    "database": os.getenv('DB_NAME', 'prestashop'),
    "user": os.getenv('DB_USER', 'root'),
    "password": os.getenv('DB_PASS', ''),
    "prefix": os.getenv('DB_PREFIX', 'ps_')
}

# Configuration FTP depuis environnement
FTP_CONFIG.update({
    "host": os.getenv('FTP_HOST', ''),
    "user": os.getenv('FTP_USER', ''),
    "password": os.getenv('FTP_PASS', ''),
    "base_path": os.getenv('FTP_IMG_PATH', FTP_CONFIG["base_path"])
})

# Configuration API depuis environnement
API_CONFIG.update({
    "url": os.getenv('WP_API_URL', ''),
    "consumer_key": os.getenv('WP_API_USER', ''),
    "consumer_secret": os.getenv('WP_API_PASS', '')
})

# Création des dossiers nécessaires
for directory in [LOGS_DIR, TEMP_DIR]:
    directory.mkdir(exist_ok=True) 