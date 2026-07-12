from django.core.exceptions import ValidationError


def validate_file_size(value, max_mb=15):
    """Refuse les fichiers dépassant max_mb (par défaut 15 Mo)."""
    max_bytes = max_mb * 1024 * 1024
    if value and value.size > max_bytes:
        raise ValidationError(f"Le fichier ne doit pas dépasser {max_mb} Mo (taille actuelle: {value.size / 1024 / 1024:.1f} Mo).")


def validate_photo_size(value):
    validate_file_size(value, max_mb=15)


def validate_logo_size(value):
    validate_file_size(value, max_mb=2)
