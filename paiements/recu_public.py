"""
Module pour le téléchargement public de reçus et notes de rappel PDF via un lien sécurisé.
Permet aux parents de télécharger sans se connecter au site.
"""

import hashlib
import hmac
from datetime import datetime, timedelta
from django.conf import settings
from django.http import HttpResponse, Http404
from django.shortcuts import get_object_or_404
import logging

from .models import Paiement
from eleves.models import Eleve

logger = logging.getLogger(__name__)


def get_secret_key():
    return getattr(settings, 'SECRET_KEY', 'default-secret-key')


def generer_token_recu(paiement_id, duree_validite_jours=7):
    """
    Génère un token sécurisé pour accéder au reçu sans authentification.
    Valide pendant 7 jours par défaut.
    """
    expiration = datetime.now() + timedelta(days=duree_validite_jours)
    timestamp = int(expiration.timestamp())
    
    data = f"recu:{paiement_id}:{timestamp}"
    
    signature = hmac.new(
        get_secret_key().encode(),
        data.encode(),
        hashlib.sha256
    ).hexdigest()[:32]
    
    return f"{timestamp}_{signature}"


def verifier_token_recu(paiement_id, token):
    """Vérifie si le token est valide pour accéder au reçu."""
    try:
        parts = token.split('_')
        if len(parts) != 2:
            return False
        
        timestamp_str, signature_fournie = parts
        timestamp = int(timestamp_str)
        
        if datetime.now().timestamp() > timestamp:
            return False
        
        data = f"recu:{paiement_id}:{timestamp}"
        signature_attendue = hmac.new(
            get_secret_key().encode(),
            data.encode(),
            hashlib.sha256
        ).hexdigest()[:32]
        
        return hmac.compare_digest(signature_fournie, signature_attendue)
        
    except Exception as e:
        logger.error(f"Erreur vérification token reçu: {e}")
        return False


def generer_token_note_rappel(eleve_id, duree_validite_jours=7):
    """
    Génère un token sécurisé pour accéder à la note de rappel sans authentification.
    Valide pendant 7 jours par défaut.
    """
    expiration = datetime.now() + timedelta(days=duree_validite_jours)
    timestamp = int(expiration.timestamp())
    
    data = f"rappel:{eleve_id}:{timestamp}"
    
    signature = hmac.new(
        get_secret_key().encode(),
        data.encode(),
        hashlib.sha256
    ).hexdigest()[:32]
    
    return f"{timestamp}_{signature}"


def verifier_token_note_rappel(eleve_id, token):
    """Vérifie si le token est valide pour accéder à la note de rappel."""
    try:
        parts = token.split('_')
        if len(parts) != 2:
            return False
        
        timestamp_str, signature_fournie = parts
        timestamp = int(timestamp_str)
        
        if datetime.now().timestamp() > timestamp:
            return False
        
        data = f"rappel:{eleve_id}:{timestamp}"
        signature_attendue = hmac.new(
            get_secret_key().encode(),
            data.encode(),
            hashlib.sha256
        ).hexdigest()[:32]
        
        return hmac.compare_digest(signature_fournie, signature_attendue)
        
    except Exception as e:
        logger.error(f"Erreur vérification token note rappel: {e}")
        return False


def generer_url_recu_public(request, paiement_id):
    """Génère l'URL publique complète pour télécharger le reçu."""
    token = generer_token_recu(paiement_id)
    base_url = request.build_absolute_uri('/')[:-1]
    return f"{base_url}/paiements/recu-public/{paiement_id}/?token={token}"


def generer_url_note_rappel_public(request, eleve_id):
    """Génère l'URL publique complète pour télécharger la note de rappel."""
    token = generer_token_note_rappel(eleve_id)
    base_url = request.build_absolute_uri('/')[:-1]
    return f"{base_url}/paiements/note-rappel-public/{eleve_id}/?token={token}"


def recu_public_pdf(request, paiement_id):
    """
    Vue publique pour télécharger le reçu PDF sans authentification.
    Nécessite un token valide dans les paramètres GET.
    """
    token = request.GET.get('token', '')
    
    if not token:
        raise Http404("Lien invalide ou expiré. Veuillez demander un nouveau lien.")
    
    if not verifier_token_recu(paiement_id, token):
        raise Http404("Lien invalide ou expiré. Veuillez demander un nouveau lien à l'école.")
    
    try:
        from io import BytesIO
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.utils import ImageReader
        from django.db.models import Sum
        from ecole_moderne.pdf_utils import draw_logo_watermark
        import os
        
        paiement = get_object_or_404(
            Paiement.objects.select_related(
                'eleve', 'type_paiement', 'mode_paiement',
                'eleve__classe', 'eleve__classe__ecole',
                'classe_encaissement', 'ecole_encaissement',
            ),
            id=paiement_id,
            statut='VALIDE'
        )
        
        # Calcul total remises
        remises_total = paiement.remises.aggregate(total=Sum('montant_remise')).get('total') or 0

        # Situation financière globale de l'élève (via échéancier)
        from .models import EcheancierPaiement
        from decimal import Decimal
        ech = None
        ech = EcheancierPaiement.objects.filter(
            eleve_id=paiement.eleve_id,
            annee_scolaire=paiement.annee_scolaire,
            ecole_reference_id=paiement.ecole_encaissement_id,
        ).first()
        total_du = ech.total_du if ech else Decimal('0')
        total_paye = ech.total_paye if ech else Decimal('0')
        solde_restant = ech.solde_restant if ech else Decimal('0')

        # Préparer le buffer et le canvas
        buffer = BytesIO()
        c = canvas.Canvas(buffer, pagesize=A4)
        width, height = A4

        # Filigrane
        try:
            ecole_obj = paiement.ecole_historique
            draw_logo_watermark(c, width, height, ecole=ecole_obj)
        except Exception:
            pass

        # Mise en page simple
        left = 40
        top = height - 40
        line_h = 18

        # En-tête
        c.setFont('Helvetica-Bold', 18)
        c.drawString(left, top, "REÇU DE PAIEMENT")
        top -= 25

        ecole_obj = paiement.ecole_historique
        if ecole_obj:
            c.setFont('Helvetica-Bold', 12)
            c.drawString(left, top, ecole_obj.nom)
            top -= 15
            c.setFont('Helvetica', 9)
            if getattr(ecole_obj, 'telephone', None):
                c.drawString(left, top, f"Tél: {ecole_obj.telephone}")
                top -= 12
            if getattr(ecole_obj, 'email', None):
                c.drawString(left, top, f"Email: {ecole_obj.email}")
                top -= 12

        top -= 20

        # Informations du reçu
        c.setFont('Helvetica-Bold', 11)
        c.drawString(left, top, f"Numéro de reçu: {paiement.numero_recu or 'N/A'}")
        top -= line_h
        c.drawString(left, top, f"Date: {paiement.date_paiement.strftime('%d/%m/%Y')}")
        top -= line_h * 2

        # Informations élève
        c.setFont('Helvetica-Bold', 12)
        c.drawString(left, top, "ÉLÈVE")
        top -= line_h
        c.setFont('Helvetica', 11)
        c.drawString(left, top, f"Nom: {paiement.eleve.prenom or ''} {paiement.eleve.nom or ''}")
        top -= line_h
        c.drawString(left, top, f"Matricule: {paiement.eleve.matricule or 'N/A'}")
        top -= line_h
        if paiement.classe_historique:
            c.drawString(left, top, f"Classe: {paiement.classe_historique.nom}")
            top -= line_h
        top -= line_h

        # Détails du paiement
        c.setFont('Helvetica-Bold', 12)
        c.drawString(left, top, "DÉTAILS DU PAIEMENT")
        top -= line_h
        c.setFont('Helvetica', 11)
        c.drawString(left, top, f"Type: {paiement.type_paiement.nom if paiement.type_paiement else 'N/A'}")
        top -= line_h
        c.drawString(left, top, f"Mode: {paiement.mode_paiement.nom if paiement.mode_paiement else 'N/A'}")
        top -= line_h
        c.drawString(left, top, f"Montant: {paiement.montant:,.0f} GNF".replace(",", " "))
        top -= line_h

        # Afficher la ventilation réelle de ce paiement sur l'échéancier.
        from .views import _get_payment_allocation_breakdown
        allocation = _get_payment_allocation_breakdown(paiement)
        if allocation:
            top -= 5
            c.setFont('Helvetica-Bold', 11)
            c.drawString(left, top, "AFFECTATION DU PAIEMENT")
            top -= line_h
            c.setFont('Helvetica', 10)
            allocation_lines = (
                (allocation.get('label_inscription', 'Inscription'), allocation.get('inscription', 0)),
                ("1ère tranche", allocation.get('tranche_1', 0)),
                ("2ème tranche", allocation.get('tranche_2', 0)),
                ("3ème tranche", allocation.get('tranche_3', 0)),
            )
            for label, amount in allocation_lines:
                if amount:
                    c.drawString(left, top, f"{label}: {amount:,.0f} GNF".replace(",", " "))
                    top -= line_h

        top -= 10

        # Situation financière globale
        if total_du > 0:
            c.setFont('Helvetica-Bold', 12)
            c.drawString(left, top, "SITUATION FINANCIÈRE")
            top -= line_h
            c.setFont('Helvetica', 11)
            c.drawString(left, top, f"Total frais de scolarité: {total_du:,.0f} GNF".replace(",", " "))
            top -= line_h
            c.drawString(left, top, f"Total déjà payé: {total_paye:,.0f} GNF".replace(",", " "))
            top -= line_h
            c.setFont('Helvetica-Bold', 11)
            if solde_restant > 0:
                c.setFillColorRGB(0.8, 0, 0)
                c.drawString(left, top, f"Reste à payer: {solde_restant:,.0f} GNF".replace(",", " "))
                c.setFillColorRGB(0, 0, 0)
            else:
                c.setFillColorRGB(0, 0.5, 0)
                c.drawString(left, top, "Scolarité entièrement payée")
                c.setFillColorRGB(0, 0, 0)
            top -= line_h

        if remises_total > 0:
            top -= 10
            c.setFont('Helvetica-Bold', 11)
            c.drawString(left, top, "REMISES APPLIQUÉES")
            top -= line_h
            c.setFont('Helvetica', 10)
            for paiement_remise in paiement.remises.select_related('remise').all():
                nom = getattr(paiement_remise.remise, 'nom', 'Remise')
                portee = getattr(paiement_remise, 'portee_libelle', '')
                suffixe_portee = f" ({portee})" if portee else ''
                montant = Decimal(str(paiement_remise.montant_remise or 0))
                c.drawString(
                    left,
                    top,
                    f"- {nom}{suffixe_portee} : -{montant:,.0f} GNF".replace(",", " "),
                )
                top -= line_h

        top -= 10
        c.setFont('Helvetica-Bold', 11)
        c.drawString(left, top, f"Statut: {paiement.get_statut_display()}")
        
        # Finaliser
        c.showPage()
        c.save()
        
        buffer.seek(0)
        response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
        filename = f"recu_{paiement.numero_recu}.pdf"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        logger.info(f"Reçu téléchargé via lien public: paiement={paiement_id}")
        
        return response
        
    except Paiement.DoesNotExist:
        raise Http404("Paiement non trouvé ou non validé.")
    except Exception as e:
        logger.error(f"Erreur génération reçu public: {e}")
        raise Http404("Erreur lors de la génération du reçu. Veuillez réessayer.")


def note_rappel_public_pdf(request, eleve_id):
    """
    Vue publique pour télécharger la note de rappel PDF sans authentification.
    Nécessite un token valide dans les paramètres GET.
    """
    token = request.GET.get('token', '')
    
    if not token:
        raise Http404("Lien invalide ou expiré. Veuillez demander un nouveau lien.")
    
    if not verifier_token_note_rappel(eleve_id, token):
        raise Http404("Lien invalide ou expiré. Veuillez demander un nouveau lien à l'école.")
    
    try:
        from io import BytesIO
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import A4
        from django.db.models import Sum
        from decimal import Decimal
        from ecole_moderne.pdf_utils import draw_logo_watermark
        
        eleve = get_object_or_404(
            Eleve.objects.select_related('classe', 'classe__ecole'),
            id=eleve_id
        )

        # Calculer le solde via l'échéancier (source de vérité) ou ConfigurationPaiement
        from .models import EcheancierPaiement, ConfigurationPaiement
        montant_total = Decimal('0')
        montant_paye = Decimal('0')
        reste_a_payer = Decimal('0')

        ech = None
        try:
            ech = eleve.echeancier
        except EcheancierPaiement.DoesNotExist:
            ech = None

        if ech and ech.total_du > 0:
            montant_total = ech.total_du
            montant_paye = ech.total_paye
            reste_a_payer = ech.solde_restant
        else:
            # Fallback: ConfigurationPaiement
            try:
                config = ConfigurationPaiement.objects.get(classe=eleve.classe)
                montant_total = (config.montant_inscription or 0) + (config.montant_scolarite or 0)
            except (ConfigurationPaiement.DoesNotExist, Exception):
                montant_total = Decimal('0')

            montant_paye = Paiement.objects.filter(
                eleve=eleve, statut='VALIDE'
            ).aggregate(total=Sum('montant'))['total'] or Decimal('0')
            reste_a_payer = max(montant_total - montant_paye, Decimal('0'))
        
        # Préparer le buffer et le canvas
        buffer = BytesIO()
        c = canvas.Canvas(buffer, pagesize=A4)
        width, height = A4
        
        # Filigrane
        try:
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
        c.drawString(left, top, "NOTE DE RAPPEL DE PAIEMENT")
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
        
        # Situation financière
        c.setFont('Helvetica-Bold', 12)
        c.drawString(left, top, "SITUATION FINANCIÈRE")
        top -= line_h
        c.setFont('Helvetica', 11)
        c.drawString(left, top, f"Frais de scolarité: {montant_total:,.0f} GNF".replace(",", " "))
        top -= line_h
        c.drawString(left, top, f"Montant payé: {montant_paye:,.0f} GNF".replace(",", " "))
        top -= line_h
        c.setFont('Helvetica-Bold', 11)
        c.setFillColorRGB(0.8, 0, 0)  # Rouge
        c.drawString(left, top, f"RESTE À PAYER: {reste_a_payer:,.0f} GNF".replace(",", " "))
        c.setFillColorRGB(0, 0, 0)  # Noir
        top -= line_h * 2
        
        # Message
        c.setFont('Helvetica', 10)
        c.drawString(left, top, "Nous vous prions de bien vouloir régulariser cette situation")
        top -= 14
        c.drawString(left, top, "dans les meilleurs délais.")
        
        # Finaliser
        c.showPage()
        c.save()
        
        buffer.seek(0)
        response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
        filename = f"note_rappel_{eleve.matricule}.pdf"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        logger.info(f"Note de rappel téléchargée via lien public: eleve={eleve_id}")
        
        return response
        
    except Eleve.DoesNotExist:
        raise Http404("Élève non trouvé.")
    except Exception as e:
        logger.error(f"Erreur génération note rappel public: {e}")
        raise Http404("Erreur lors de la génération de la note de rappel. Veuillez réessayer.")
