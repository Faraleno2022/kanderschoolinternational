"""Gestion des donnees persistantes de l'application Windows.

PyInstaller 6 place les modules dans ``_internal``. Les anciennes versions
de l'application ont donc pu y creer SQLite, les medias et les journaux. Les
versions actuelles utilisent un dossier de donnees stable, a cote de l'EXE.
Ce module assure une migration unique et recuperable de l'ancien agencement.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path


MIGRATION_MARKER = ".data_layout_v2"


def _copy_file_atomically(source: Path, destination: Path) -> None:
    """Copie un fichier sans exposer une destination partiellement ecrite."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".migration.tmp")
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def _merge_directory(source: Path, destination: Path) -> int:
    """Fusionne ``source`` dans ``destination`` et retourne le nombre de fichiers."""
    if not source.is_dir():
        return 0

    copied = 0
    for source_file in source.rglob("*"):
        if not source_file.is_file():
            continue
        relative = source_file.relative_to(source)
        _copy_file_atomically(source_file, destination / relative)
        copied += 1
    return copied


def migrate_legacy_data_layout(base_dir: str | os.PathLike[str]) -> list[str]:
    """Migre les donnees de ``_internal`` vers le dossier stable de l'EXE.

    La migration est idempotente. L'ancien emplacement est conserve comme
    sauvegarde de secours ; aucune donnee utilisateur n'est supprimee.
    """
    root = Path(base_dir).resolve()
    legacy_root = root / "_internal"
    marker = root / MIGRATION_MARKER
    if marker.exists() or not legacy_root.is_dir():
        return []

    actions: list[str] = []
    legacy_db = legacy_root / "db.sqlite3"
    current_db = root / "db.sqlite3"

    if legacy_db.is_file() and legacy_db.stat().st_size > 0:
        if not current_db.exists() or current_db.stat().st_size == 0:
            _copy_file_atomically(legacy_db, current_db)
            actions.append("base SQLite migree depuis _internal")

    for directory_name in ("media", "logs"):
        copied = _merge_directory(
            legacy_root / directory_name,
            root / directory_name,
        )
        if copied:
            actions.append(f"{copied} fichier(s) {directory_name} migre(s)")

    # Le marqueur n'est pose qu'apres toutes les copies reussies. En cas
    # d'interruption, le prochain demarrage peut reprendre la migration.
    marker.write_text("migration _internal -> racine terminee\n", encoding="utf-8")
    return actions
