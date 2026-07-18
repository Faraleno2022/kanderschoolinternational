from django.urls import path
from . import views
from .views_tranches import export_tranches_par_classe_pdf, export_tranches_par_classe_excel
from . import views_rappels
from .whatsapp_recu import apercu_message_whatsapp_recu, apercu_message_whatsapp_note_rappel
from .recu_public import recu_public_pdf, note_rappel_public_pdf
from .views_rapport_comptable import (
    rapport_comptable,
    export_rapport_comptable_pdf,
    export_rapport_comptable_excel,
)

app_name = 'paiements'

urlpatterns = [
    # Tableau de bord
    path('', views.tableau_bord_paiements, name='tableau_bord'),
    
    # Gestion des paiements
    path('liste/', views.liste_paiements, name='liste_paiements'),
    path('detail/<int:paiement_id>/', views.detail_paiement, name='detail_paiement'),
    path('ajouter/', views.ajouter_paiement, name='ajouter_paiement'),
    path('ajouter/<int:eleve_id>/', views.ajouter_paiement, name='ajouter_paiement_eleve'),
    path('valider/<int:paiement_id>/', views.valider_paiement, name='valider_paiement'),
    path('relancer/<int:eleve_id>/', views.relancer_eleve, name='relancer_eleve'),
    path('relances/', views.liste_relances, name='liste_relances'),
    path('retards/envoyer/', views.envoyer_notifs_retards, name='envoyer_notifs_retards'),
    
    # Échéanciers
    path('echeancier/<int:eleve_id>/', views.echeancier_eleve, name='echeancier_eleve'),
    path('echeancier/creer/<int:eleve_id>/', views.creer_echeancier, name='creer_echeancier'),
    path('echeancier/assurer/<int:eleve_id>/', views.assurer_echeancier, name='assurer_echeancier'),
    path('echeancier/valider/<int:eleve_id>/', views.valider_echeancier, name='valider_echeancier'),
    
    # Génération de documents
    path('recu/<int:paiement_id>/pdf/', views.generer_recu_pdf, name='generer_recu_pdf'),
    path('note-rappel/<int:eleve_id>/pdf/', views.generer_note_rappel_pdf, name='generer_note_rappel_pdf'),
    path('notes-rappel/classe/<int:classe_id>/pdf/', views.generer_notes_rappel_classe_pdf, name='generer_notes_rappel_classe_pdf'),
    path('eleves-impayes/', views.liste_eleves_impayes, name='liste_eleves_impayes'),
    path('notes-rappel/tous/pdf/', views.generer_toutes_notes_rappel_pdf, name='generer_toutes_notes_rappel_pdf'),
    path('export/tranches-par-classe/pdf/', export_tranches_par_classe_pdf, name='export_tranches_par_classe_pdf'),
    path('export/tranches-par-classe/excel/', export_tranches_par_classe_excel, name='export_tranches_par_classe_excel'),
    path('export/liste/excel/', views.export_liste_paiements_excel, name='export_liste_paiements_excel'),
    path('export/recap-par-classe/excel/', views.export_recap_par_classe_excel, name='export_recap_par_classe_excel'),
    # Export par période (Excel)
    path('export/periode/excel/', views.export_paiements_periode_excel, name='export_paiements_periode_excel'),
    path('rapport/remises/', views.rapport_remises, name='rapport_remises'),
    
    # Rapports
    path('rapport/retards/', views.rapport_retards, name='rapport_retards'),
    path('rapport/encaissements/', views.rapport_encaissements, name='rapport_encaissements'),
    path('rapport/comptabilite/', rapport_comptable, name='rapport_comptable'),
    path('rapport/comptabilite/pdf/', export_rapport_comptable_pdf, name='export_rapport_comptable_pdf'),
    path('rapport/comptabilite/excel/', export_rapport_comptable_excel, name='export_rapport_comptable_excel'),
    
    # Élèves soldés (année scolaire réglée)
    path('eleves-soldes/', views.eleves_soldes_simple, name='liste_eleves_soldes'),
    
    # API JSON Paiements
    path('api/paiements/', views.api_paiements_list, name='api_paiements_list'),
    path('api/paiements/<int:pk>/', views.api_paiement_detail, name='api_paiement_detail'),
    
    # AJAX endpoints
    path('ajax/statistiques/', views.ajax_statistiques_paiements, name='ajax_statistiques_paiements'),
    path('ajax/eleve-info/', views.ajax_eleve_info, name='ajax_eleve_info'),
    path('ajax/calculer-remise/', views.ajax_calculer_remise, name='ajax_calculer_remise'),
    path('ajax/classes/', views.ajax_classes_par_ecole, name='ajax_classes_par_ecole'),
    path('ajax/montant-suggere/', views.ajax_montant_suggere, name='ajax_montant_suggere'),
    
    # Webhooks (Twilio)
    path('twilio/inbound/', views.twilio_inbound, name='twilio_inbound'),
    path('twilio/status-callback/', views.twilio_status_callback, name='twilio_status_callback'),
    
    # Remises
    path('remise/<int:paiement_id>/', views.appliquer_remise_paiement, name='appliquer_remise'),
    # Annulation de remise(s)
    path('remise/<int:paiement_id>/annuler/', views.annuler_remise_paiement, name='annuler_remise_paiement'),
    path('remise/<int:paiement_id>/annuler/<int:remise_id>/', views.annuler_remise_paiement, name='annuler_remise_paiement_unique'),
    path('calculateur-remise/', views.calculateur_remise, name='calculateur_remise'),
    
    # Système de rappels de paiement
    path('rappels/', views_rappels.gerer_rappels, name='gerer_rappels'),
    path('rappels/creer-automatiques/', views_rappels.creer_rappels_automatiques, name='creer_rappels_automatiques'),
    path('rappels/creer/<int:eleve_id>/', views_rappels.creer_rappel_individuel, name='creer_rappel_individuel'),
    path('rappels/eleves-retard/', views_rappels.eleves_en_retard, name='eleves_en_retard'),
    path('rappels/apercu-message/<int:eleve_id>/', views_rappels.apercu_message_rappel, name='apercu_message_rappel'),
    path('rappels/<int:relance_id>/marquer-envoye/', views_rappels.marquer_rappel_envoye, name='marquer_rappel_envoye'),
    path('rappels/statistiques/', views_rappels.statistiques_rappels, name='statistiques_rappels'),
    path('rappels/supprimer/<int:relance_id>/', views_rappels.supprimer_rappel, name='supprimer_rappel'),
    
    # WhatsApp - Envoi de reçus et notes de rappel
    path('whatsapp/apercu-recu/', apercu_message_whatsapp_recu, name='apercu_whatsapp_recu'),
    path('whatsapp/apercu-note-rappel/', apercu_message_whatsapp_note_rappel, name='apercu_whatsapp_note_rappel'),
    
    # URLs publiques (téléchargement sans authentification via token)
    path('recu-public/<int:paiement_id>/', recu_public_pdf, name='recu_public_pdf'),
    path('note-rappel-public/<int:eleve_id>/', note_rappel_public_pdf, name='note_rappel_public_pdf'),
]

