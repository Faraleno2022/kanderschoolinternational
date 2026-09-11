import os
import time
from django import template
from django.templatetags.static import static
from django.conf import settings
from django.utils.html import format_html, format_html_join

register = template.Library()

@register.simple_tag
def static_versioned(path):
    """
    Template tag pour ajouter automatiquement un paramètre de version
    aux fichiers statiques basé sur leur date de modification.
    
    Usage: {% static_versioned 'images/ecole.jpg' %}
    Résultat: /static/images/ecole.jpg?v=1634567890
    """
    try:
        # Obtenir l'URL statique normale
        static_url = static(path)
        
        # Construire le chemin complet du fichier
        if hasattr(settings, 'STATICFILES_DIRS') and settings.STATICFILES_DIRS:
            # En développement, chercher dans STATICFILES_DIRS
            for static_dir in settings.STATICFILES_DIRS:
                file_path = os.path.join(static_dir, path)
                if os.path.exists(file_path):
                    # Obtenir la date de modification du fichier
                    mtime = os.path.getmtime(file_path)
                    version = str(int(mtime))
                    return f"{static_url}?v={version}"
        
        # Si le fichier n'est pas trouvé, utiliser un timestamp actuel
        # pour forcer le rechargement
        version = str(int(time.time()))
        return f"{static_url}?v={version}"
        
    except Exception:
        # En cas d'erreur, retourner l'URL statique normale
        return static(path)

@register.simple_tag
def image_with_reload(path, alt_text="", css_class="", **kwargs):
    """
    Template tag pour créer une balise img avec rechargement automatique et optimisations.
    
    Usage: {% image_with_reload 'images/ecole.jpg' 'Description' 'hero-image' loading='eager' %}
    """
    try:
        # Obtenir l'URL avec version
        versioned_url = static_versioned(path)
        
        # Construire les attributs HTML
        attributes = []
        if alt_text:
            attributes.append(format_html('alt="{}"', alt_text))
        if css_class:
            attributes.append(format_html('class="{}"', css_class))
        
        # Gestion du lazy loading
        loading_type = kwargs.pop('loading', 'lazy')
        if loading_type in ['lazy', 'eager']:
            attributes.append(format_html('loading="{}"', loading_type))
        
        # Optimisations de performance
        attributes.append(format_html('decoding="{}"', 'async'))
        
        # Ajouter les attributs supplémentaires
        for key, value in kwargs.items():
            # Convertir les underscores en tirets pour les attributs HTML
            key = key.replace('_', '-')
            if not key.replace('-', '').isalnum() or key.lower().startswith('on'):
                continue
            attributes.append(format_html('{}="{}"', key, value))
        
        # Ajouter l'attribut onerror pour les images de fallback
        fallback_urls = {
            'images/ecole.jpg': 'https://images.unsplash.com/photo-1511634829096-045a111727eb?q=80&w=2400&auto=format&fit=crop&ixlib=rb-4.0.3',
            'images/carte1.jpg': 'https://images.unsplash.com/photo-1523050854058-8df90110c9f1?q=80&w=1200&auto=format&fit=crop&ixlib=rb-4.0.3',
            'images/carte2.jpg': 'https://images.unsplash.com/photo-1496307042754-b4aa456c4a2d?q=80&w=1200&auto=format&fit=crop&ixlib=rb-4.0.3'
        }
        
        fallback_url = fallback_urls.get(path, '')
        if fallback_url:
            # Améliorer la gestion d'erreur avec retry
            error_handler = f"""
                this.onerror=function(){{
                    if(!this.retryCount) this.retryCount=0;
                    if(this.retryCount<2){{
                        this.retryCount++;
                        setTimeout(()=>{{this.src=this.src+'?retry='+this.retryCount}},1000);
                    }} else {{
                        this.src='{fallback_url}';
                        this.onerror=null;
                    }}
                }};
            """.replace('\n', '').replace('  ', '')
            attributes.append(format_html('onerror="{}"', error_handler))
        
        # Construire la balise img complète
        attrs_str = format_html_join(' ', '{}', ((attr,) for attr in attributes))
        return format_html('<img src="{}" {}>', versioned_url, attrs_str)
        
    except Exception:
        # En cas d'erreur, retourner une balise img basique
        return format_html('<img src="{}" alt="{}" class="{}" loading="lazy">', static(path), alt_text, css_class)

@register.simple_tag
def cache_bust():
    """
    Génère un timestamp unique pour forcer le rechargement du cache.
    
    Usage: {% cache_bust %} dans une URL ou un paramètre
    """
    return str(int(time.time()))
