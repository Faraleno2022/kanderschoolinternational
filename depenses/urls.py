from django.urls import path
from . import views
from . import views_logistique
from . import views_bibliotheque
from . import views_fournitures
from . import views_recouvrement

app_name = 'depenses'

urlpatterns = [
    # Accueil du module Recouvrement : tableau de bord général + cartes
    path('', views_recouvrement.hub_recouvrement, name='hub'),

    # Tableau de bord des dépenses classiques
    path('tableau-bord/', views.tableau_bord, name='tableau_bord'),

    # Gestion des dépenses
    path('liste/', views.liste_depenses, name='liste_depenses'),
    path('ajouter/', views.ajouter_depense, name='ajouter_depense'),
    path('<int:depense_id>/', views.detail_depense, name='detail_depense'),
    path('<int:depense_id>/modifier/', views.modifier_depense, name='modifier_depense'),
    path('<int:depense_id>/supprimer/', views.supprimer_depense, name='supprimer_depense'),
    path('<int:depense_id>/valider/', views.valider_depense, name='valider_depense'),
    path('<int:depense_id>/marquer-payee/', views.marquer_payee, name='marquer_payee'),
    
    # Gestion des catégories
    path('categories/', views.gestion_categories, name='gestion_categories'),
    path('categories/<int:categorie_id>/modifier/', views.modifier_categorie, name='modifier_categorie'),
    path('categories/<int:categorie_id>/supprimer/', views.supprimer_categorie, name='supprimer_categorie'),
    
    # ===== RECOUVREMENT : ABONNEMENTS INFORMATIQUE =====
    # Déclaré avant les routes génériques <module> pour que « informatique »
    # ne soit pas capturé comme un sous-module simple.
    path('recouvrement/informatique/', views_recouvrement.dashboard_informatique,
         name='recouvrement_informatique_dashboard'),
    path('recouvrement/informatique/liste/', views_recouvrement.liste_informatique,
         name='recouvrement_informatique_liste'),
    path('recouvrement/informatique/nouveau/', views_recouvrement.ajouter_abonnement_informatique,
         name='recouvrement_informatique_ajouter'),
    path('recouvrement/informatique/<int:pk>/modifier/',
         views_recouvrement.modifier_abonnement_informatique,
         name='recouvrement_informatique_modifier'),
    path('recouvrement/informatique/<int:pk>/supprimer/',
         views_recouvrement.supprimer_abonnement_informatique,
         name='recouvrement_informatique_supprimer'),
    path('recouvrement/informatique/<int:pk>/carte/',
         views_recouvrement.carte_abonnement_informatique,
         name='recouvrement_informatique_carte'),
    path('recouvrement/informatique/export/excel/',
         views_recouvrement.export_informatique_excel,
         name='recouvrement_informatique_export_excel'),
    path('recouvrement/informatique/export/pdf/',
         views_recouvrement.export_informatique_pdf,
         name='recouvrement_informatique_export_pdf'),
    path('recouvrement/informatique/recherche-eleve/',
         views_recouvrement.rechercher_eleve_informatique,
         name='recouvrement_informatique_recherche_eleve'),

    # ===== RECOUVREMENT : CUISINE / DOCUMENTS / VERSEMENTS =====
    path('recouvrement/<str:module>/', views_recouvrement.dashboard_module,
         name='recouvrement_dashboard_module'),
    path('recouvrement/<str:module>/nouveau/', views_recouvrement.ajouter_operation,
         name='recouvrement_ajouter'),
    path('recouvrement/<str:module>/<int:pk>/modifier/', views_recouvrement.modifier_operation,
         name='recouvrement_modifier'),
    path('recouvrement/<str:module>/<int:pk>/supprimer/', views_recouvrement.supprimer_operation,
         name='recouvrement_supprimer'),
    path('recouvrement/<str:module>/export/excel/', views_recouvrement.export_module_excel,
         name='recouvrement_export_excel'),
    path('recouvrement/<str:module>/export/pdf/', views_recouvrement.export_module_pdf,
         name='recouvrement_export_pdf'),

    # ===== LOGISTIQUE =====
    path('logistique/', views_logistique.dashboard_logistique, name='dashboard_logistique'),
    path('logistique/biens/', views_logistique.liste_biens, name='liste_biens'),
    path('logistique/biens/nouveau/', views_logistique.creer_bien, name='creer_bien'),
    path('logistique/biens/<int:bien_id>/modifier/', views_logistique.modifier_bien, name='modifier_bien'),
    path('logistique/papier-ram/', views_logistique.liste_papier_ram, name='liste_papier_ram'),
    path('logistique/papier-ram/nouveau/', views_logistique.creer_papier_ram, name='creer_papier_ram'),

    # ===== FOURNITURES SCOLAIRES =====
    path('fournitures/', views_fournitures.dashboard_fournitures, name='dashboard_fournitures'),
    path('fournitures/produits/nouveau/', views_fournitures.ajouter_produit_fourniture, name='ajouter_produit_fourniture'),
    path('fournitures/produits/<int:produit_id>/modifier/', views_fournitures.modifier_produit_fourniture, name='modifier_produit_fourniture'),
    path('fournitures/produits/<int:produit_id>/vendre/', views_fournitures.vendre_fourniture, name='vendre_fourniture'),
    path('fournitures/ventes/<int:vente_id>/annuler/', views_fournitures.annuler_vente_fourniture, name='annuler_vente_fourniture'),
    
    # ===== BIBLIOTHÈQUE =====
    path('bibliotheque/', views_bibliotheque.dashboard_bibliotheque, name='dashboard_bibliotheque'),
    path('bibliotheque/catalogue/', views_bibliotheque.catalogue_livres, name='catalogue_livres'),
    path('bibliotheque/livres/nouveau/', views_bibliotheque.ajouter_livre, name='ajouter_livre'),
    path('bibliotheque/livres/<int:livre_id>/modifier/', views_bibliotheque.modifier_livre, name='modifier_livre'),
    path('bibliotheque/livres/<int:livre_id>/supprimer/', views_bibliotheque.supprimer_livre, name='supprimer_livre'),
    path('bibliotheque/categories/', views_bibliotheque.gestion_categories_livres, name='gestion_categories_livres'),
    path('bibliotheque/categories/<int:categorie_id>/modifier/', views_bibliotheque.modifier_categorie_livre, name='modifier_categorie_livre'),
    path('bibliotheque/categories/<int:categorie_id>/supprimer/', views_bibliotheque.supprimer_categorie_livre, name='supprimer_categorie_livre'),
    path('bibliotheque/emprunts/', views_bibliotheque.liste_emprunts, name='liste_emprunts'),
    path('bibliotheque/emprunts/nouveau/', views_bibliotheque.creer_emprunt, name='creer_emprunt'),
    path('bibliotheque/emprunts/<int:emprunt_id>/retour/', views_bibliotheque.retourner_livre, name='retourner_livre'),
    path('bibliotheque/reservations/', views_bibliotheque.liste_reservations, name='liste_reservations'),
    path('bibliotheque/reservations/nouvelle/', views_bibliotheque.creer_reservation, name='creer_reservation'),
    path('bibliotheque/reservations/<int:reservation_id>/notifier/', views_bibliotheque.notifier_reservation, name='notifier_reservation'),
    path('bibliotheque/reservations/<int:reservation_id>/annuler/', views_bibliotheque.annuler_reservation, name='annuler_reservation'),
    path('bibliotheque/reservations/<int:reservation_id>/emprunter/', views_bibliotheque.emprunter_reservation, name='emprunter_reservation'),
    path('bibliotheque/statistiques/', views_bibliotheque.statistiques_bibliotheque, name='statistiques_bibliotheque'),
]
