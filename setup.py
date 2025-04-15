"""
Configuration du package pour l'installation.
"""

from setuptools import setup, find_packages

setup(
    name="prestashop-wp-image-migrator",
    version="1.0.0",
    packages=find_packages(),
    install_requires=[
        "requests>=2.31.0",
        "python-dotenv>=1.0.0",
        "woocommerce>=3.0.0",
    ],
    author="Votre Nom",
    author_email="votre.email@example.com",
    description="Migration d'images de PrestaShop vers WordPress/WooCommerce",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/votre-repo/prestashop-wp-image-migrator",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.7",
) 