from django.urls import path
from . import views
from . import views_sante
from .views_import import importer_eleves, telecharger_template_eleves, exporter_eleves_classe
from .views_nouvelle_annee import (
    nouvelle_annee_apercu,
    nouvelle_annee_creer,
    gestion_annees,
    changer_annee_active,
)

app_name = 'eleves'

urlpatterns = [
    # Liste et recherche des élèves
    path('', views.liste_eleves, name='liste_eleves'),
    path('liste/', views.liste_eleves, name='liste_eleves'),
    
    # Détails d'un élève
    path('<int:eleve_id>/', views.detail_eleve, name='detail_eleve'),
    
    # Gestion des élèves
    path('ajouter/', views.ajouter_eleve, name='ajouter_eleve'),
    path('<int:eleve_id>/modifier/', views.modifier_eleve, name='modifier_eleve'),
    path('<int:eleve_id>/supprimer/', views.supprimer_eleve, name='supprimer_eleve'),
    path('supprimer-masse/', views.supprimer_eleves_masse, name='supprimer_eleves_masse'),
    
    # Gestion des classes
    path('classes/', views.gestion_classes, name='gestion_classes'),

    # Nouvelle année scolaire
    path('annees/', gestion_annees, name='gestion_annees'),
    path('annees/changer/', changer_annee_active, name='changer_annee_active'),
    path('nouvelle-annee/', nouvelle_annee_apercu, name='nouvelle_annee_apercu'),
    path('nouvelle-annee/creer/', nouvelle_annee_creer, name='nouvelle_annee_creer'),

    # Création d'école (hors admin)
    path('ecoles/creer/', views.creer_ecole, name='creer_ecole'),
    path('ecoles/creer/confirmation/', views.creer_ecole_confirmation, name='creer_ecole_confirmation'),
    path('ecoles/<int:ecole_id>/configurer/', views.configurer_ecole, name='configurer_ecole'),
    
    # Statistiques
    path('statistiques/', views.statistiques_eleves, name='statistiques_eleves'),
    
    # PDF
    path('<int:eleve_id>/fiche-inscription-pdf/', views.fiche_inscription_pdf, name='fiche_inscription_pdf'),
    path('<int:eleve_id>/ticket-retrait-pdf/', views.generer_ticket_retrait_pdf, name='ticket_retrait_pdf'),
    path('<int:eleve_id>/ticket-bus-pdf/', views.generer_ticket_bus_pdf, name='ticket_bus_pdf'),
    path('<int:eleve_id>/carte-scolaire-pdf/', views.generer_carte_scolaire_pdf, name='carte_scolaire_pdf'),
    path('<int:eleve_id>/carte-scolaire-preview/', views.carte_scolaire_preview, name='carte_scolaire_preview'),
    
    # Génération en masse de tickets par classe
    path('classe/<int:classe_id>/tickets-retrait-pdf/', views.generer_tickets_retrait_classe_pdf, name='tickets_retrait_classe_pdf'),
    path('classe/<int:classe_id>/tickets-bus-pdf/', views.generer_tickets_bus_classe_pdf, name='tickets_bus_classe_pdf'),
    path('classe/<int:classe_id>/cartes-scolaires-pdf/', views.generer_cartes_classe_pdf, name='cartes_scolaires_classe_pdf'),

    # Exports par classe
    path('export/classe/<int:classe_id>/pdf/', views.export_eleves_classe_pdf, name='export_eleves_classe_pdf'),
    path('export/classe/<int:classe_id>/excel/', views.export_eleves_classe_excel, name='export_eleves_classe_excel'),
    
    # Exports de tous les élèves
    path('export/tous/pdf/', views.export_tous_eleves_pdf, name='export_tous_eleves_pdf'),
    path('export/tous/excel/', views.export_tous_eleves_excel, name='export_tous_eleves_excel'),
    
    # AJAX
    path('ajax/classes-par-ecole/<int:ecole_id>/', views.ajax_classes_par_ecole, name='ajax_classes_par_ecole'),
    path('ajax/statistiques/', views.ajax_statistiques_eleves, name='ajax_statistiques_eleves'),
    path('ajax/rechercher-responsable-telephone/', views.ajax_rechercher_responsable_telephone, name='ajax_rechercher_responsable_telephone'),
    path('ajax/modifier-telephone-responsable/', views.ajax_modifier_telephone_responsable, name='ajax_modifier_telephone_responsable'),
    
    # Infirmerie — suivi santé des élèves
    path('infirmerie/', views_sante.infirmerie_dashboard, name='infirmerie'),
    path('<int:eleve_id>/sante/', views_sante.sante_eleve, name='sante_eleve'),
    path('<int:eleve_id>/sante/visite/ajouter/', views_sante.ajouter_visite, name='ajouter_visite'),
    path('infirmerie/visite/<int:visite_id>/modifier/', views_sante.modifier_visite, name='modifier_visite'),
    path('infirmerie/visite/<int:visite_id>/supprimer/', views_sante.supprimer_visite, name='supprimer_visite'),

    # Import/Export d'élèves
    path('importer/', importer_eleves, name='importer_eleves'),
    path('template-eleves/', telecharger_template_eleves, name='telecharger_template_eleves'),
    path('exporter/classe/<int:classe_id>/', exporter_eleves_classe, name='exporter_eleves_classe'),
]

