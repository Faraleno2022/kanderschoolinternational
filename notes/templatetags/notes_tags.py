from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """Permet d'accéder à un élément du dictionnaire avec une clé variable"""
    if dictionary is None:
        return None
    return dictionary.get(key)


@register.filter
def mul(value, arg):
    """Multiplie deux valeurs"""
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError):
        return ''


@register.filter
def get_moyenne_generale(evaluation):
    """Récupère la moyenne générale d'une évaluation maternelle"""
    if evaluation is None:
        return None
    if hasattr(evaluation, 'get_moyenne_generale'):
        return evaluation.get_moyenne_generale()
    return None


@register.filter
def get_lettre_generale(evaluation):
    """Récupère la lettre générale d'une évaluation maternelle"""
    if evaluation is None:
        return None
    if hasattr(evaluation, 'get_lettre_generale'):
        return evaluation.get_lettre_generale()
    return None


@register.filter
def get_id(obj):
    """Récupère l'ID d'un objet"""
    if obj is None:
        return None
    return obj.id if hasattr(obj, 'id') else None


@register.filter
def get_note(note_obj):
    """Récupère la note d'un objet NoteMaternelle"""
    if note_obj is None:
        return ''
    return note_obj.note if hasattr(note_obj, 'note') else ''


@register.filter
def get_commentaire(note_obj):
    """Récupère le commentaire d'un objet NoteMaternelle"""
    if note_obj is None:
        return ''
    return note_obj.commentaire if hasattr(note_obj, 'commentaire') else ''


@register.filter
def split(value, separator=','):
    """Découpe les listes de mois utilisées dans les tableaux de saisie."""
    return str(value).split(separator) if value else []
