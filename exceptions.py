"""
Exceptions personnalisées pour le projet de migration d'images.
"""

class MigrationError(Exception):
    """Classe de base pour toutes les exceptions de migration."""
    pass

class ProductNotFoundError(MigrationError):
    """Exception levée lorsqu'un produit n'est pas trouvé."""
    def __init__(self, product_name):
        self.product_name = product_name
        super().__init__(f"Produit non trouvé: {product_name}")

class FTPConnectionError(MigrationError):
    """Exception levée lors d'une erreur de connexion FTP."""
    def __init__(self, host, error):
        self.host = host
        self.error = error
        super().__init__(f"Erreur de connexion FTP ({host}): {error}")

class ImageUploadError(MigrationError):
    """Exception levée lors d'une erreur d'upload d'image."""
    def __init__(self, image_path, error):
        self.image_path = image_path
        self.error = error
        super().__init__(f"Erreur d'upload de l'image {image_path}: {error}")

class APIError(MigrationError):
    """Exception levée lors d'une erreur d'API."""
    def __init__(self, endpoint, status_code, response):
        self.endpoint = endpoint
        self.status_code = status_code
        self.response = response
        super().__init__(f"Erreur API ({endpoint}): {status_code} - {response}")

class FileSystemError(MigrationError):
    """Exception levée lors d'une erreur de système de fichiers."""
    def __init__(self, operation, path, error):
        self.operation = operation
        self.path = path
        self.error = error
        super().__init__(f"Erreur {operation} sur {path}: {error}")

class DatabaseError(MigrationError):
    """Exception levée lors d'une erreur de base de données."""
    def __init__(self, error):
        self.error = error
        super().__init__(f"Erreur de base de données: {error}") 