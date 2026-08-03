from django.contrib import admin
from .models import (
    CategorieDepense, Fournisseur, Depense, PieceJustificative,
    BudgetAnnuel, HistoriqueDepense
)
from .models_logistique import (
    CategorieArticle, Article, BienEtablissement, MouvementStock,
    Inventaire, LigneInventaire
)
from .models_bibliotheque import (
    CategorieLivre, Livre, Emprunt, Reservation,
    HistoriqueLivre, ParametreBibliotheque
)
from .models_fournitures import ProduitFourniture, VenteFourniture


# ===== DÉPENSES =====
@admin.register(CategorieDepense)
class CategorieDepenseAdmin(admin.ModelAdmin):
    list_display = ['code', 'nom', 'actif']
    list_filter = ['actif']
    search_fields = ['nom', 'code']


@admin.register(Fournisseur)
class FournisseurAdmin(admin.ModelAdmin):
    list_display = ['nom', 'type_fournisseur', 'telephone', 'email', 'actif']
    list_filter = ['type_fournisseur', 'actif']
    search_fields = ['nom', 'telephone', 'email']


@admin.register(Depense)
class DepenseAdmin(admin.ModelAdmin):
    list_display = ['numero_facture', 'libelle', 'fournisseur', 'montant_ttc', 'date_facture', 'statut']
    list_filter = ['statut', 'type_depense', 'categorie']
    search_fields = ['numero_facture', 'libelle', 'fournisseur__nom']
    date_hierarchy = 'date_facture'


# ===== LOGISTIQUE =====
@admin.register(CategorieArticle)
class CategorieArticleAdmin(admin.ModelAdmin):
    list_display = ['code', 'nom', 'type_categorie', 'actif']
    list_filter = ['type_categorie', 'actif']
    search_fields = ['nom', 'code']


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ['code_article', 'nom', 'categorie', 'stock_actuel', 'stock_minimum', 'prix_unitaire', 'etat']
    list_filter = ['categorie', 'etat', 'actif']
    search_fields = ['code_article', 'nom', 'marque', 'reference']
    readonly_fields = ['valeur_stock', 'alerte_stock']


@admin.register(BienEtablissement)
class BienEtablissementAdmin(admin.ModelAdmin):
    list_display = ['code_bien', 'nom', 'type_bien', 'localisation', 'etat', 'actif']
    list_filter = ['type_bien', 'etat', 'actif']
    search_fields = ['code_bien', 'nom', 'localisation']


@admin.register(MouvementStock)
class MouvementStockAdmin(admin.ModelAdmin):
    list_display = ['numero_mouvement', 'article', 'type_mouvement', 'quantite', 'date_mouvement', 'cree_par']
    list_filter = ['type_mouvement', 'motif', 'date_mouvement']
    search_fields = ['numero_mouvement', 'article__nom', 'destinataire']
    date_hierarchy = 'date_mouvement'
    readonly_fields = ['stock_avant', 'stock_apres']


@admin.register(Inventaire)
class InventaireAdmin(admin.ModelAdmin):
    list_display = ['numero_inventaire', 'date_inventaire', 'statut', 'nombre_articles', 'valeur_totale']
    list_filter = ['statut', 'date_inventaire']
    search_fields = ['numero_inventaire']
    date_hierarchy = 'date_inventaire'


@admin.register(LigneInventaire)
class LigneInventaireAdmin(admin.ModelAdmin):
    list_display = ['inventaire', 'article', 'stock_theorique', 'stock_physique', 'ecart']
    list_filter = ['inventaire']
    search_fields = ['article__nom']


# ===== FOURNITURES SCOLAIRES =====
@admin.register(ProduitFourniture)
class ProduitFournitureAdmin(admin.ModelAdmin):
    list_display = [
        'nom', 'ecole', 'quantite_stock', 'quantite_vendue',
        'quantite_restante', 'prix_achat_unitaire', 'prix_vente_unitaire', 'actif',
    ]
    list_filter = ['ecole', 'unite', 'actif']
    search_fields = ['nom', 'description', 'ecole__nom']
    readonly_fields = ['date_creation', 'date_modification']


@admin.register(VenteFourniture)
class VenteFournitureAdmin(admin.ModelAdmin):
    list_display = [
        'produit', 'quantite', 'montant_vente', 'solde',
        'acheteur', 'date_vente', 'statut',
    ]
    list_filter = ['statut', 'date_vente', 'produit__ecole']
    search_fields = ['produit__nom', 'acheteur', 'produit__ecole__nom']
    date_hierarchy = 'date_vente'
    readonly_fields = [
        'produit', 'quantite', 'prix_achat_unitaire', 'prix_vente_unitaire',
        'montant_achat', 'montant_vente', 'solde', 'date_vente', 'statut',
        'cree_par', 'annulee_par', 'date_creation', 'date_modification',
        'date_annulation',
    ]

    def has_add_permission(self, request):
        # Les ventes doivent passer par l'écran métier (contrôle transactionnel du stock).
        return False


# ===== BIBLIOTHÈQUE =====
@admin.register(CategorieLivre)
class CategorieLivreAdmin(admin.ModelAdmin):
    list_display = ['code', 'nom', 'actif']
    list_filter = ['actif']
    search_fields = ['nom', 'code']


@admin.register(Livre)
class LivreAdmin(admin.ModelAdmin):
    list_display = ['code_livre', 'titre', 'auteur', 'categorie', 'statut', 'exemplaires_disponibles', 'etat']
    list_filter = ['categorie', 'statut', 'etat', 'langue']
    search_fields = ['code_livre', 'isbn', 'titre', 'auteur', 'editeur']
    readonly_fields = ['est_disponible', 'taux_disponibilite']


@admin.register(Emprunt)
class EmpruntAdmin(admin.ModelAdmin):
    list_display = ['numero_emprunt', 'livre', 'eleve', 'date_emprunt', 'date_retour_prevue', 'statut', 'jours_retard']
    list_filter = ['statut', 'date_emprunt']
    search_fields = ['numero_emprunt', 'livre__titre', 'eleve__nom', 'eleve__prenom']
    date_hierarchy = 'date_emprunt'
    readonly_fields = ['est_en_retard', 'jours_restants']


@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = ['numero_reservation', 'livre', 'eleve', 'date_reservation', 'statut']
    list_filter = ['statut', 'date_reservation']
    search_fields = ['numero_reservation', 'livre__titre', 'eleve__nom']
    date_hierarchy = 'date_reservation'


@admin.register(ParametreBibliotheque)
class ParametreBibliothequeAdmin(admin.ModelAdmin):
    list_display = ['duree_emprunt_defaut', 'nombre_emprunts_max', 'penalite_retard_journalier']
    
    def has_add_permission(self, request):
        # Permettre seulement un seul enregistrement
        return not ParametreBibliotheque.objects.exists()
    
    def has_delete_permission(self, request, obj=None):
        return False
