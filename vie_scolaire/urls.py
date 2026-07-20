from django.urls import path

from . import views_presence, views_devoirs

app_name = 'vie_scolaire'

urlpatterns = [
    # ── Pointage & Présence ────────────────────────────────────────────────
    path('', views_presence.presence_dashboard, name='presence_dashboard'),
    path('pointage/classe/<int:classe_id>/', views_presence.pointage_classe, name='pointage_classe'),
    path('rapport/', views_presence.rapport_presence, name='rapport_presence'),
    path('rapport/classe/<int:classe_id>/excel/', views_presence.export_rapport_presence_excel, name='export_rapport_excel'),
    path('rapport/classe/<int:classe_id>/pdf/', views_presence.export_rapport_presence_pdf, name='export_rapport_pdf'),
    path('eleve/<int:eleve_id>/historique/', views_presence.historique_presence_eleve, name='historique_presence_eleve'),

    # ── Suivi des devoirs ──────────────────────────────────────────────────
    path('devoirs/', views_devoirs.liste_devoirs, name='liste_devoirs'),
    path('devoirs/ajouter/', views_devoirs.ajouter_devoir, name='ajouter_devoir'),
    path('devoirs/<int:devoir_id>/modifier/', views_devoirs.modifier_devoir, name='modifier_devoir'),
    path('devoirs/<int:devoir_id>/supprimer/', views_devoirs.supprimer_devoir, name='supprimer_devoir'),
    path('devoirs/<int:devoir_id>/suivi/', views_devoirs.suivi_devoir, name='suivi_devoir'),
]
