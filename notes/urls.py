from django.urls import path
from . import views
from .bulletin_intelligent import (
    bulletin_intelligent_view,
    bulletin_intelligent_pdf,
    bulletin_intelligent_excel,
    bulletins_classe_pdf
)
from .views_import import (
    importer_notes,
    telecharger_template_import,
    get_matieres_classe,
    get_evaluations_matiere,
    import_intelligent,
    telecharger_template_intelligent,
    saisie_intelligente,
    saisie_intelligente_save
)
from .views_maternelle import (
    saisie_evaluation_maternelle,
    saisie_eleve_maternelle,
    bulletin_maternelle,
    bulletin_maternelle_pdf,
    bulletins_classe_maternelle_pdf,
    api_get_eleves_classe,
    analyse_appreciations_auto
)
from .views_activites import (
    liste_activites,
    ajouter_activite,
    modifier_activite,
    detail_activite,
    supprimer_activite,
    supprimer_piece_jointe,
    api_eleves_par_classe_note,
)
from .views_culture import (
    activites_culturelles,
    ajouter_activite_culturelle,
    modifier_activite_culturelle,
    supprimer_activite_culturelle,
    basculer_publication_activite,
)
from .whatsapp_bulletin import envoyer_bulletin_whatsapp, apercu_message_whatsapp
from .export_resultats import exporter_resultats_pdf, exporter_resultats_excel
from .export_notes_complet import exporter_notes_complet_pdf, exporter_notes_complet_excel
from .bulletin_public import bulletin_public_pdf
from .export_statistiques_pdf import exporter_statistiques_pdf, exporter_conseils_pdf
from .certificats import certificats_appreciation_pdf
from .tableau_honneur import tableau_honneur, tableau_honneur_pdf
from .livret_scolaire import livret_scolaire_selection, livret_scolaire_pdf, livret_scolaire_annuel_pdf, livret_scolaire_classe_pdf

app_name = 'notes'

urlpatterns = [
    path('', views.tableau_bord, name='tableau_bord'),
    # Activités culturelles (publiées sur le site public)
    path('culture/', activites_culturelles, name='activites_culturelles'),
    path('culture/ajouter/', ajouter_activite_culturelle, name='ajouter_activite_culturelle'),
    path('culture/<int:activite_id>/modifier/', modifier_activite_culturelle, name='modifier_activite_culturelle'),
    path('culture/<int:activite_id>/supprimer/', supprimer_activite_culturelle, name='supprimer_activite_culturelle'),
    path('culture/<int:activite_id>/publier/', basculer_publication_activite, name='basculer_publication_activite'),
    path('classes/', views.gerer_classes, name='gerer_classes'),
    path('classes/modifier/<int:classe_id>/', views.modifier_classe, name='modifier_classe'),
    path('classes/supprimer/<int:classe_id>/', views.supprimer_classe, name='supprimer_classe'),
    path('matieres/', views.gerer_matieres, name='gerer_matieres'),
    path('matieres/modifier/<int:matiere_id>/', views.modifier_matiere, name='modifier_matiere'),
    path('matieres/supprimer/<int:matiere_id>/', views.supprimer_matiere, name='supprimer_matiere'),
    path('matieres/charger-defaut/<int:classe_id>/', views.charger_matieres_defaut, name='charger_matieres_defaut'),
    path('evaluations/', views.gerer_evaluations, name='gerer_evaluations'),
    path('evaluations/creer/', views.creer_evaluation, name='creer_evaluation'),
    path('eleves/', views.gerer_eleves, name='gerer_eleves'),
    path('saisir/', views.saisir_notes, name='saisir_notes'),
    path('consulter/', views.consulter_notes, name='consulter_notes'),
    path('bulletins/', views.bulletin_dynamique, name='generer_bulletins'),
    path('bulletin-dynamique/', views.bulletin_dynamique, name='bulletin_dynamique'),
    path('saisie-notes-guineen/', views.saisie_notes_simple, name='saisie_notes_guineen'),
    path('sauvegarder-notes-guineen/', views.sauvegarder_notes_guineen, name='sauvegarder_notes_guineen'),
    path('sauvegarder-appreciations-maternelle/', views.sauvegarder_appreciations_maternelle, name='sauvegarder_appreciations_maternelle'),
    path('statistiques/', views.statistiques, name='statistiques'),
    path('liste-saisie-pdf/', views.liste_saisie_pdf, name='liste_saisie_pdf'),
    path('sauvegarder-notes/', views.sauvegarder_notes, name='sauvegarder_notes'),
    path('supprimer-notes/', views.supprimer_notes, name='supprimer_notes'),
    path('imprimer-tableau-notes-pdf/', views.imprimer_tableau_notes_pdf, name='imprimer_tableau_notes_pdf'),
    path('imprimer-tableau-notes-html/', views.imprimer_tableau_notes_html, name='imprimer_tableau_notes_html'),
    
    # Bulletin Intelligent avec calculs automatiques et exports
    path('bulletin-intelligent/<int:eleve_id>/<int:classe_note_id>/<str:periode>/', 
         bulletin_intelligent_view, name='bulletin_intelligent'),
    path('bulletin-intelligent/<int:eleve_id>/<int:classe_note_id>/<str:periode>/pdf/', 
         bulletin_intelligent_pdf, name='bulletin_intelligent_pdf'),
    path('bulletin-intelligent/<int:eleve_id>/<int:classe_note_id>/<str:periode>/excel/', 
         bulletin_intelligent_excel, name='bulletin_intelligent_excel'),
    
    # PDF de tous les bulletins d'une classe
    path('bulletins-classe-pdf/<int:classe_note_id>/<str:periode>/', 
         bulletins_classe_pdf, name='bulletins_classe_pdf'),
    
    # Importation de notes
    path('importer/', importer_notes, name='importer_notes'),
    path('template-import/', telecharger_template_import, name='telecharger_template_import'),
    
    # API AJAX pour l'importation
    path('api/matieres-classe/', get_matieres_classe, name='api_matieres_classe'),
    path('api/evaluations-matiere/', get_evaluations_matiere, name='api_evaluations_matiere'),
    
    # WhatsApp Bulletin
    path('bulletin/whatsapp/envoyer/', envoyer_bulletin_whatsapp, name='envoyer_bulletin_whatsapp'),
    path('bulletin/whatsapp/apercu/', apercu_message_whatsapp, name='apercu_message_whatsapp'),
    
    # Bulletin public (téléchargement sans authentification via token)
    path('bulletin-public/<int:eleve_id>/<int:classe_note_id>/<str:periode>/', 
         bulletin_public_pdf, name='bulletin_public_pdf'),
    
    # Export des résultats par classe
    path('exporter-resultats-pdf/', exporter_resultats_pdf, name='exporter_resultats_pdf'),
    path('exporter-resultats-excel/', exporter_resultats_excel, name='exporter_resultats_excel'),
    
    # Export complet des notes par matière
    path('exporter-notes-complet-pdf/', exporter_notes_complet_pdf, name='exporter_notes_complet_pdf'),
    path('exporter-notes-complet-excel/', exporter_notes_complet_excel, name='exporter_notes_complet_excel'),
    
    # Export des statistiques en PDF avec graphiques et recommandations
    path('exporter-statistiques-pdf/', exporter_statistiques_pdf, name='exporter_statistiques_pdf'),
    
    # Export des conseils et prises de décision en PDF
    path('exporter-conseils-pdf/', exporter_conseils_pdf, name='exporter_conseils_pdf'),
    
    # Certificats d'appréciation pour les 5 premiers
    path('certificats-appreciation-pdf/', certificats_appreciation_pdf, name='certificats_appreciation_pdf'),
    
    # Tableau d'Honneur
    path('tableau-honneur/', tableau_honneur, name='tableau_honneur'),
    path('tableau-honneur-pdf/', tableau_honneur_pdf, name='tableau_honneur_pdf'),
    
    # ============================================================================
    # MODULE MATERNELLE - Évaluation et Bulletins
    # ============================================================================
    path('maternelle/saisie/', saisie_evaluation_maternelle, name='saisie_evaluation_maternelle'),
    path('maternelle/saisie/eleve/<int:eleve_id>/', saisie_eleve_maternelle, name='saisie_eleve_maternelle'),
    path('maternelle/bulletin/<int:evaluation_id>/', bulletin_maternelle, name='bulletin_maternelle'),
    path('maternelle/bulletin/<int:evaluation_id>/pdf/', bulletin_maternelle_pdf, name='bulletin_maternelle_pdf'),
    path('maternelle/bulletins-classe-pdf/', bulletins_classe_maternelle_pdf, name='bulletins_classe_maternelle_pdf'),
    path('maternelle/analyse-appreciations/', analyse_appreciations_auto, name='analyse_appreciations_auto'),
    path('maternelle/bulletins-classe-v2-pdf/', views.bulletins_classe_maternelle_v2_pdf, name='bulletins_classe_maternelle_v2_pdf'),
    path('maternelle/api/eleves/', api_get_eleves_classe, name='api_eleves_classe_maternelle'),
    
    # Nouveau système bulletin maternelle basé sur AppreciationMaternelle
    path('maternelle/bulletin-v2/<int:eleve_id>/<int:classe_id>/<str:trimestre>/', 
         views.bulletin_maternelle_v2, name='bulletin_maternelle_v2'),
    path('maternelle/bulletin-v2/<int:eleve_id>/<int:classe_id>/<str:trimestre>/pdf/', 
         views.bulletin_maternelle_v2_pdf, name='bulletin_maternelle_v2_pdf'),
    path('maternelle/saisie-bulletin/<int:eleve_id>/<int:classe_id>/<str:trimestre>/', 
         views.saisie_bulletin_maternelle, name='saisie_bulletin_maternelle'),
    path('maternelle/fiches-recommandations-pdf/', 
         views.fiches_recommandations_pdf, name='fiches_recommandations_pdf'),

    # Fiche de saisie des notes a imprimer pour les professeurs
    path('fiche-saisie-notes-pdf/', views.fiche_saisie_notes_pdf, name='fiche_saisie_notes_pdf'),

    # Fiche mensuelle avec toutes les matieres en colonnes
    path('fiche-report-notes-pdf/', views.fiche_report_notes_pdf, name='fiche_report_notes_pdf'),
    
    # Importation intelligente - Template avec toutes les matières en colonnes
    path('import-intelligent/', import_intelligent, name='import_intelligent'),
    path('template-intelligent/', telecharger_template_intelligent, name='telecharger_template_intelligent'),
    
    # Saisie intelligente - Toutes les matières en colonnes
    path('saisie-intelligente/', saisie_intelligente, name='saisie_intelligente'),
    path('saisie-intelligente/save/', saisie_intelligente_save, name='saisie_intelligente_save'),
    
    # Bulletin Maternelle Modèle 2 (format tableau avec activités)
    path('maternelle/bulletin-modele2/<int:eleve_id>/<int:classe_id>/<str:trimestre>/pdf/', 
         views.bulletin_maternelle_modele2_pdf, name='bulletin_maternelle_modele2_pdf'),
    path('maternelle/bulletins-classe-modele2-pdf/',
         views.bulletins_classe_maternelle_modele2_pdf, name='bulletins_classe_maternelle_modele2_pdf'),

    # ============================================================================
    # ACTIVITÉS JOURNALIÈRES
    # ============================================================================
    path('activites/', liste_activites, name='liste_activites'),
    path('activites/ajouter/', ajouter_activite, name='ajouter_activite'),
    path('activites/<int:activite_id>/', detail_activite, name='detail_activite'),
    path('activites/<int:activite_id>/modifier/', modifier_activite, name='modifier_activite'),
    path('activites/<int:activite_id>/supprimer/', supprimer_activite, name='supprimer_activite'),
    path('activites/pj/<int:pj_id>/supprimer/', supprimer_piece_jointe, name='supprimer_piece_jointe'),
    path('activites/api/eleves/', api_eleves_par_classe_note, name='api_eleves_classe_activite'),

    # ============================================================================
    # LIVRET SCOLAIRE — Parcours complet de l'élève
    # ============================================================================
    path('livret-scolaire/', livret_scolaire_selection, name='livret_scolaire'),
    path('livret-scolaire/<int:eleve_id>/pdf/', livret_scolaire_pdf, name='livret_scolaire_pdf'),
    path('livret-scolaire/<int:eleve_id>/annuel/', livret_scolaire_annuel_pdf, name='livret_scolaire_annuel_pdf'),
    path('livret-scolaire/classe/<int:classe_id>/pdf/', livret_scolaire_classe_pdf, name='livret_scolaire_classe_pdf'),
]
