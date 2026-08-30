"""
Module pour le téléchargement public de reçus d'abonnement bus via un lien sécurisé.
Permet aux parents de télécharger sans se connecter au site.
Validité: 7 jours par défaut.
"""

import hashlib
import hmac
from datetime import datetime, timedelta
from django.conf import settings
from django.http import HttpResponse, Http404
from django.shortcuts import get_object_or_404
import logging

from .models import AbonnementBus

logger = logging.getLogger(__name__)


def get_secret_key():
    return getattr(settings, 'SECRET_KEY', 'default-secret-key')


def generer_token_abonnement(abonnement_id, duree_validite_jours=7):
    """
    Génère un token sécurisé pour accéder au reçu d'abonnement sans authentification.
    Valide pendant 7 jours par défaut.
    """
    expiration = datetime.now() + timedelta(days=duree_validite_jours)
    timestamp = int(expiration.timestamp())
    
    data = f"bus:{abonnement_id}:{timestamp}"
    
    signature = hmac.new(
        get_secret_key().encode(),
        data.encode(),
        hashlib.sha256
    ).hexdigest()[:32]
    
    return f"{timestamp}_{signature}"


def verifier_token_abonnement(abonnement_id, token):
    """Vérifie si le token est valide pour accéder au reçu d'abonnement."""
    try:
        parts = token.split('_')
        if len(parts) != 2:
            return False
        
        timestamp_str, signature_fournie = parts
        timestamp = int(timestamp_str)
        
        if datetime.now().timestamp() > timestamp:
            return False
        
        data = f"bus:{abonnement_id}:{timestamp}"
        signature_attendue = hmac.new(
            get_secret_key().encode(),
            data.encode(),
            hashlib.sha256
        ).hexdigest()[:32]
        
        return hmac.compare_digest(signature_fournie, signature_attendue)
        
    except Exception as e:
        logger.error(f"Erreur vérification token abonnement bus: {e}")
        return False


def generer_url_abonnement_public(request, abonnement_id):
    """Génère l'URL publique complète pour télécharger le reçu d'abonnement."""
    token = generer_token_abonnement(abonnement_id)
    base_url = request.build_absolute_uri('/')[:-1]
    return f"{base_url}/bus/recu-public/{abonnement_id}/?token={token}"


def abonnement_public_pdf(request, abonnement_id):
    """
    Vue publique pour télécharger le reçu d'abonnement bus PDF sans authentification.
    Nécessite un token valide dans les paramètres GET.
    Validité du lien: 7 jours.
    """
    token = request.GET.get('token', '')
    
    if not token:
        raise Http404("Lien invalide ou expiré. Veuillez demander un nouveau lien.")
    
    if not verifier_token_abonnement(abonnement_id, token):
        raise Http404("Lien invalide ou expiré. Veuillez demander un nouveau lien à l'école.")
    
    try:
        from io import BytesIO
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import A4
        
        abonnement = get_object_or_404(
            AbonnementBus.objects.select_related('eleve', 'eleve__classe', 'eleve__classe__ecole'),
            id=abonnement_id
        )
        eleve = abonnement.eleve
        
        # Préparer le buffer et le canvas
        buffer = BytesIO()
        c = canvas.Canvas(buffer, pagesize=A4)
        width, height = A4
        
        # Filigrane (optionnel)
        try:
            from ecole_moderne.pdf_utils import draw_logo_watermark
            ecole_obj = eleve.classe.ecole if eleve.classe else None
            draw_logo_watermark(c, width, height, ecole=ecole_obj)
        except Exception:
            pass
        
        # Mise en page
        left = 40
        top = height - 40
        line_h = 18
        
        # En-tête
        c.setFont('Helvetica-Bold', 18)
        c.drawString(left, top, "REÇU D'ABONNEMENT BUS SCOLAIRE")
        top -= 25
        
        ecole_obj = eleve.classe.ecole if eleve.classe else None
        if ecole_obj:
            c.setFont('Helvetica-Bold', 12)
            c.drawString(left, top, ecole_obj.nom)
            top -= 15
            c.setFont('Helvetica', 9)
            if ecole_obj.telephone:
                c.drawString(left, top, f"Tél: {ecole_obj.telephone}")
                top -= 12
            if ecole_obj.email:
                c.drawString(left, top, f"Email: {ecole_obj.email}")
                top -= 12
        
        top -= 20
        
        # Informations élève
        c.setFont('Helvetica-Bold', 12)
        c.drawString(left, top, "ÉLÈVE")
        top -= line_h
        c.setFont('Helvetica', 11)
        c.drawString(left, top, f"Nom: {eleve.prenom} {eleve.nom}")
        top -= line_h
        c.drawString(left, top, f"Matricule: {eleve.matricule}")
        top -= line_h
        if eleve.classe:
            c.drawString(left, top, f"Classe: {eleve.classe.nom}")
            top -= line_h
        top -= line_h
        
        # Détails de l'abonnement
        c.setFont('Helvetica-Bold', 12)
        c.drawString(left, top, "DÉTAILS DE L'ABONNEMENT")
        top -= line_h
        c.setFont('Helvetica', 11)
        c.drawString(left, top, f"Périodicité: {abonnement.get_periodicite_display()}")
        top -= line_h
        c.drawString(left, top, f"Montant: {abonnement.montant:,.0f} GNF".replace(",", " "))
        top -= line_h
        if abonnement.reference_paiement:
            c.drawString(left, top, f"Référence paiement: {abonnement.reference_paiement}")
            top -= line_h
        c.drawString(left, top, f"Date début: {abonnement.date_debut.strftime('%d/%m/%Y')}")
        top -= line_h
        c.drawString(left, top, f"Date expiration: {abonnement.date_expiration.strftime('%d/%m/%Y')}")
        top -= line_h
        c.setFont('Helvetica-Bold', 11)
        c.drawString(left, top, f"Statut: {abonnement.get_statut_display()}")
        top -= line_h
        
        if abonnement.zone:
            c.setFont('Helvetica', 11)
            c.drawString(left, top, f"Zone: {abonnement.zone}")
            top -= line_h
        if abonnement.point_arret:
            c.drawString(left, top, f"Point d'arrêt: {abonnement.point_arret}")
            top -= line_h
        
        # Finaliser
        c.showPage()
        c.save()
        
        buffer.seek(0)
        response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
        filename = f"abonnement_bus_{eleve.matricule}.pdf"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        logger.info(f"Reçu abonnement bus téléchargé via lien public: abonnement={abonnement_id}")
        
        return response
        
    except AbonnementBus.DoesNotExist:
        raise Http404("Abonnement non trouvé.")
    except Exception as e:
        logger.error(f"Erreur génération reçu abonnement public: {e}")
        raise Http404("Erreur lors de la génération du reçu. Veuillez réessayer.")
