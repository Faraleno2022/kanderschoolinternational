from django.urls import path
from . import views
from . import views_logistique
from . import views_bibliotheque

app_name = 'depenses'

urlpatterns = [
    # Tableau de bord principal
    path('', views.tableau_bord, name='tableau_bord'),
    
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
    
    # ===== LOGISTIQUE =====
    path('logistique/', views_logistique.dashboard_logistique, name='dashboard_logistique'),
    path('logistique/articles/', views_logistique.liste_articles, name='liste_articles'),
    path('logistique/articles/nouveau/', views_logistique.creer_article, name='creer_article'),
    path('logistique/articles/<int:article_id>/', views_logistique.detail_article, name='detail_article'),
    path('logistique/articles/<int:article_id>/modifier/', views_logistique.modifier_article, name='modifier_article'),
    path('logistique/articles/<int:article_id>/supprimer/', views_logistique.supprimer_article, name='supprimer_article'),
    path('logistique/categories/', views_logistique.gestion_categories_articles, name='gestion_categories_articles'),
    path('logistique/categories/<int:categorie_id>/modifier/', views_logistique.modifier_categorie_article, name='modifier_categorie_article'),
    path('logistique/biens/', views_logistique.liste_biens, name='liste_biens'),
    path('logistique/biens/nouveau/', views_logistique.creer_bien, name='creer_bien'),
    path('logistique/biens/<int:bien_id>/modifier/', views_logistique.modifier_bien, name='modifier_bien'),
    path('logistique/mouvements/', views_logistique.liste_mouvements, name='liste_mouvements'),
    path('logistique/mouvements/nouveau/', views_logistique.creer_mouvement, name='creer_mouvement'),
    path('logistique/inventaires/', views_logistique.liste_inventaires, name='liste_inventaires'),
    path('logistique/inventaires/nouveau/', views_logistique.creer_inventaire, name='creer_inventaire'),
    path('logistique/inventaires/<int:inventaire_id>/', views_logistique.detail_inventaire, name='detail_inventaire'),
    path('logistique/inventaires/<int:inventaire_id>/valider/', views_logistique.valider_inventaire, name='valider_inventaire'),
    path('logistique/export/excel/', views_logistique.export_stock_excel, name='export_stock_excel'),
    
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
    path('bibliotheque/statistiques/', views_bibliotheque.statistiques_bibliotheque, name='statistiques_bibliotheque'),
]
