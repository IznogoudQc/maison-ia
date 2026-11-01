r"""Emplacements de l'application : dossier du projet en développement, %APPDATA%\MaisonIA une fois installée.

Installée (exécutable PyInstaller), l'application ne peut pas écrire dans Program Files : au premier
lancement, config.yaml et data/ sont copiés dans le dossier de l'utilisateur (on peut ensuite les
modifier, par exemple le catalogue d'objets), et les sauvegardes et journaux y sont écrits.
La clé Claude vient d'un .env ou du Gestionnaire d'identifiants Windows (jamais d'un fichier publié).
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_NAME = "MaisonIA"
KEYRING_SERVICE, KEYRING_USER = "maison-ia", "anthropic"


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_dir() -> Path:
    """Fichiers livrés avec l'application (config.yaml, data/)."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


def user_dir() -> Path:
    return Path(os.environ.get("APPDATA", Path.home())) / APP_NAME


def prepare_installed_app() -> Path:
    """Application installée : copie la config et les données de départ, puis travaille dans le dossier utilisateur."""
    if not frozen():
        return Path.cwd()
    target = user_dir()
    target.mkdir(parents=True, exist_ok=True)
    source = bundle_dir()
    if not (target / "config.yaml").exists():
        shutil.copy2(source / "config.yaml", target / "config.yaml")
    for item in (source / "data").rglob("*"):
        destination = target / "data" / item.relative_to(source / "data")
        if item.is_file() and not destination.exists():  # on ne remplace jamais un fichier modifié
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, destination)
    os.chdir(target)
    return target


def load_api_key() -> bool:
    """Met la clé dans l'environnement : .env (déjà chargé) ou Gestionnaire d'identifiants Windows."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return True
    try:
        import keyring
        key = keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
    except Exception:  # pas de trousseau disponible : mode simulé
        return False
    if key:
        os.environ["ANTHROPIC_API_KEY"] = key
    return bool(key)


def ask_and_store_api_key() -> bool:
    """Petite fenêtre (texte masqué) pour saisir la clé une fois ; elle est rangée dans Windows."""
    import tkinter
    from tkinter import messagebox, simpledialog

    import keyring

    root = tkinter.Tk()
    root.withdraw()
    key = simpledialog.askstring("Maison IA", "Colle ta clé Claude (ANTHROPIC_API_KEY).\n"
                                 "Elle reste sur cet ordinateur, dans le Gestionnaire d'identifiants Windows.",
                                 show="*", parent=root)
    if not key or not key.strip().startswith("sk-"):
        root.destroy()
        return False
    keyring.set_password(KEYRING_SERVICE, KEYRING_USER, key.strip())
    messagebox.showinfo("Maison IA", "Clé enregistrée. Mets llm.provider: claude dans config.yaml pour l'utiliser.",
                        parent=root)
    root.destroy()
    return True
