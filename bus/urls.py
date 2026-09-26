from django.urls import path
from . import views
from . import views_cantine
from .whatsapp_bus import apercu_message_whatsapp_abonnement, apercu_message_whatsapp_expiration
from .abonnement_public import abonnement_public_pdf

app_name = 'bus'

urlpatterns = [
    # Abonnements Bus
    path('', views.liste_abonnements, name='index'),
    path('liste/', views.liste_abonnements, name='liste'),
    path('export/breakdown/<str:kind>.csv', views.export_abonnements_breakdown_csv, name='export_breakdown_csv'),
    path('nouveau/', views.abonnement_create, name='nouveau'),
    path('<int:abo_id>/modifier/', views.abonnement_edit, name='modifier'),
    path('<int:abo_id>/supprimer/', views.supprimer_abonnement_bus, name='supprimer_abonnement_bus'),
    path('relances/', views.relances, name='relances'),
    path('relances/envoyer/', views.envoyer_relances_bus, name='envoyer_relances_bus'),
    path('relances/export/excel/', views.export_relances_excel, name='export_relances_excel'),
    path('<int:abo_id>/recu/pdf/', views.generer_recu_abonnement_pdf, name='recu_pdf'),
    
    # Abonnements Cantine
    path('cantine/', views_cantine.tableau_bord_cantine, name='tableau_bord_cantine'),
    path('cantine/liste/', views_cantine.liste_abonnements_cantine, name='liste_abonnements_cantine'),
    path('cantine/nouveau/', views_cantine.creer_abonnement_cantine, name='creer_abonnement_cantine'),
    path('cantine/<int:pk>/modifier/', views_cantine.modifier_abonnement_cantine, name='modifier_abonnement_cantine'),
    path('cantine/<int:pk>/supprimer/', views_cantine.supprimer_abonnement_cantine, name='supprimer_abonnement_cantine'),
    path('cantine/corbeille/', views_cantine.corbeille_cantine, name='corbeille_cantine'),
    path('cantine/corbeille/<int:archive_id>/restaurer/', views_cantine.restaurer_abonnement_cantine, name='restaurer_abonnement_cantine'),
    path('cantine/<int:abo_id>/recu/pdf/', views_cantine.generer_recu_cantine_pdf, name='recu_cantine_pdf'),
    path('cantine/export/excel/', views_cantine.export_cantine_excel, name='export_cantine_excel'),
    path('cantine/api/alertes/', views_cantine.alertes_cantine_json, name='alertes_cantine_json'),
    path('cantine/api/eleve/<int:eleve_id>/', views_cantine.get_eleve_info_json, name='get_eleve_info_json'),
    
    # WhatsApp - Abonnements Bus
    path('whatsapp/apercu-abonnement/', apercu_message_whatsapp_abonnement, name='apercu_whatsapp_abonnement'),
    path('whatsapp/apercu-expiration/', apercu_message_whatsapp_expiration, name='apercu_whatsapp_expiration'),
    
    # URL publique (téléchargement sans authentification via token - validité 7 jours)
    path('recu-public/<int:abonnement_id>/', abonnement_public_pdf, name='recu_public_pdf'),
]
