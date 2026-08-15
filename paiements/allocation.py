"""Règles communes d'affectation des paiements sur un échéancier."""

from decimal import Decimal
import re
import unicodedata

from .models import Paiement


ALLOCATION_COMPONENTS = (
    ("inscription", "frais_inscription_du", "frais_inscription_paye"),
    ("tranche_1", "tranche_1_due", "tranche_1_payee"),
    ("tranche_2", "tranche_2_due", "tranche_2_payee"),
    ("tranche_3", "tranche_3_due", "tranche_3_payee"),
)


def _decimal(value):
    return Decimal(str(value or 0))


def normalize_payment_type(value):
    """Normalise un libellé pour reconnaître inscription/réinscription."""
    if not isinstance(value, str):
        value = getattr(value, "nom", "") or ""
    normalized = unicodedata.normalize("NFKD", value).casefold()
    return "".join(char for char in normalized if not unicodedata.combining(char))


def registration_kind_for_type(value):
    """Retourne le tarif d'inscription explicitement demandé par le type."""
    normalized = normalize_payment_type(value)
    if "reinscription" in normalized:
        return "reinscription"
    if "inscription" in normalized:
        return "inscription"
    return None


def payment_type_plan(value):
    """Décode un type de paiement en postes métier explicites.

    Les accents, la casse et les variantes usuelles (``1ère tranche``,
    ``tranche 1`` ou ``T1``) sont acceptés. Le plan retourné est partagé par
    la suggestion et la validation serveur afin d'éviter deux répartitions
    contradictoires.
    """
    normalized = normalize_payment_type(value)
    registration_kind = registration_kind_for_type(normalized)
    tranches = set()
    patterns = {
        1: (
            r"\btranche\s*1\b",
            r"\b1(?:ere|er)?\s+tranche\b",
            r"\b(?:premier|premiere)\s+tranche\b",
            r"\bt\s*1\b",
        ),
        2: (
            r"\btranche\s*2\b",
            r"\b2(?:eme)?\s+tranche\b",
            r"\bdeuxieme\s+tranche\b",
            r"\bt\s*2\b",
        ),
        3: (
            r"\btranche\s*3\b",
            r"\b3(?:eme)?\s+tranche\b",
            r"\btroisieme\s+tranche\b",
            r"\bt\s*3\b",
        ),
    }
    for number, number_patterns in patterns.items():
        if any(re.search(pattern, normalized) for pattern in number_patterns):
            tranches.add(number)

    is_annual = "annuel" in normalized or "annuelle" in normalized
    is_tuition = "scolarite" in normalized
    if is_annual or (is_tuition and not tranches):
        tranches.update((1, 2, 3))

    return {
        "normalized": normalized,
        "registration_kind": registration_kind,
        "include_registration": registration_kind is not None,
        "tranches": tuple(sorted(tranches)),
    }


def allocate_amount_sequentially(echeancier, amount, initial_paid=None):
    """Affecte un montant: inscription, T1, T2 puis T3.

    La fonction ne sauvegarde rien. Elle retourne l'affectation du montant,
    les nouveaux cumuls payés et l'éventuel reliquat au-delà du total dû.
    """
    remaining = max(Decimal("0"), _decimal(amount))
    paid = {
        key: _decimal((initial_paid or {}).get(key, getattr(echeancier, paid_field, 0)))
        for key, _due_field, paid_field in ALLOCATION_COMPONENTS
    }
    allocation = {key: Decimal("0") for key, _due, _paid in ALLOCATION_COMPONENTS}

    for key, due_field, _paid_field in ALLOCATION_COMPONENTS:
        if remaining <= 0:
            break
        due = _decimal(getattr(echeancier, due_field, 0))
        available = max(Decimal("0"), due - paid[key])
        applied = min(remaining, available)
        if applied > 0:
            allocation[key] = applied
            paid[key] += applied
            remaining -= applied

    return allocation, paid, remaining


def reste_par_tranche_avec_couverture(echeancier, couverture_totale):
    """Répartit une couverture totale (encaissements + remises) sur les postes.

    Utilise le même ordre en cascade (inscription -> T1 -> T2 -> T3) que
    l'allocation réelle des paiements, pour que le "reste" par tranche
    reste cohérent avec le solde global (qui, lui, déduit les remises).
    Sans cette répartition, une remise réduit le solde global sans jamais
    réduire aucune tranche, et l'écart affiché induit le caissier en erreur
    sur le montant réellement encore payable.

    Retourne un dict {key: reste} pour chaque poste de ALLOCATION_COMPONENTS.
    """
    zero_paid = {key: Decimal('0') for key, _due, _paid in ALLOCATION_COMPONENTS}
    _allocation, paid, _remaining = allocate_amount_sequentially(
        echeancier, couverture_totale, initial_paid=zero_paid
    )
    return {
        key: max(Decimal('0'), _decimal(getattr(echeancier, due_field, 0)) - paid[key])
        for key, due_field, _paid_field in ALLOCATION_COMPONENTS
    }


def get_payment_allocation(paiement, echeancier=None):
    """Reconstruit l'affectation exacte d'un paiement validé pour les reçus."""
    if echeancier is None:
        try:
            echeancier = paiement.eleve.echeancier
        except Exception:
            return None

    running_paid = {key: Decimal("0") for key, _due, _paid in ALLOCATION_COMPONENTS}
    target_allocation = None
    validated = Paiement.objects.filter(
        eleve=paiement.eleve,
        statut="VALIDE",
    )
    # Certaines versions du projet portent l'année scolaire sur Paiement,
    # d'autres uniquement sur la classe et l'échéancier. Garder le moteur
    # compatible avec les deux schémas évite de mélanger les historiques.
    if hasattr(paiement, "annee_scolaire"):
        validated = validated.filter(annee_scolaire=paiement.annee_scolaire)
    elif getattr(echeancier, "annee_scolaire", None):
        validated = validated.filter(
            eleve__classe__annee_scolaire=echeancier.annee_scolaire,
        )
    validated = validated.order_by("date_paiement", "date_creation", "pk")

    for current in validated.iterator():
        allocation, running_paid, unapplied = allocate_amount_sequentially(
            echeancier,
            current.montant,
            initial_paid=running_paid,
        )
        allocation["non_affecte"] = unapplied
        if current.pk == paiement.pk:
            target_allocation = allocation

    return target_allocation


def allocate_discounts(echeancier, discounts, balances=None):
    """Ventile les remises validées sur les tranches réellement concernées.

    Les remises ne couvrent jamais l'inscription/réinscription. Les anciennes
    remises sans information de tranche sont appliquées à T1, T2 puis T3 afin
    de rester compatibles avec les données antérieures.
    """
    current_balances = dict(balances or {
        key: max(
            Decimal('0'),
            _decimal(getattr(echeancier, due_field, 0))
            - _decimal(getattr(echeancier, paid_field, 0)),
        )
        for key, due_field, paid_field in ALLOCATION_COMPONENTS
    })
    allocation = {
        key: Decimal('0') for key, _due, _paid in ALLOCATION_COMPONENTS
    }

    for discount in discounts:
        raw_selected = getattr(discount, 'tranches_concernees_liste', None)
        if raw_selected is None:
            raw_selected = getattr(discount, 'tranches_list', [])
        selected = []
        for raw_number in raw_selected:
            try:
                number = int(raw_number)
            except (TypeError, ValueError):
                continue
            if number in (1, 2, 3):
                selected.append(f"tranche_{number}")
        if not selected:
            selected = ['tranche_1', 'tranche_2', 'tranche_3']

        amount = max(Decimal('0'), _decimal(getattr(discount, 'montant_remise', 0)))
        for key in selected:
            if amount <= 0:
                break
            available = max(Decimal('0'), _decimal(current_balances.get(key, 0)))
            take = min(amount, available)
            allocation[key] += take
            current_balances[key] = available - take
            amount -= take

    return allocation, current_balances


def allocate_cash_and_discounts(echeancier, cash_amount, discounts):
    """Ventile une couverture en respectant d'abord la portée des remises.

    Une remise déduite du reçu doit réduire la tranche choisie avant que le
    paiement net ne soit distribué sur les autres postes. Si l'encaissement
    était ventilé en premier, une remise T1 pouvait être ignorée lorsque le
    paiement avait déjà rempli T1, laissant à tort un solde sur T3.

    Les montants enregistrés et effectivement imputés sont retournés
    séparément afin que les rapports signalent toute remise incohérente au
    lieu de la masquer.
    """
    discounts = list(discounts or ())
    full_balances = {
        key: max(Decimal('0'), _decimal(getattr(echeancier, due_field, 0)))
        for key, due_field, _paid_field in ALLOCATION_COMPONENTS
    }
    discount_allocation, _balances_after_discount = allocate_discounts(
        echeancier,
        discounts,
        balances=full_balances,
    )
    cash_allocation, covered_by_component, cash_unapplied = (
        allocate_amount_sequentially(
            echeancier,
            cash_amount,
            initial_paid=discount_allocation,
        )
    )
    balances = {
        key: max(
            Decimal('0'),
            _decimal(getattr(echeancier, due_field, 0))
            - covered_by_component[key],
        )
        for key, due_field, _paid_field in ALLOCATION_COMPONENTS
    }
    discount_recorded = sum(
        (
            max(
                Decimal('0'),
                _decimal(getattr(discount, 'montant_remise', 0)),
            )
            for discount in discounts
        ),
        Decimal('0'),
    )
    discount_applied = sum(discount_allocation.values(), Decimal('0'))

    return {
        'cash_allocation': cash_allocation,
        'cash_applied': sum(cash_allocation.values(), Decimal('0')),
        'cash_unapplied': cash_unapplied,
        'discount_allocation': discount_allocation,
        'discount_recorded': discount_recorded,
        'discount_applied': discount_applied,
        'discount_unapplied': max(
            Decimal('0'), discount_recorded - discount_applied,
        ),
        'covered_by_component': covered_by_component,
        'balances': balances,
        'total_coverage': sum(covered_by_component.values(), Decimal('0')),
        'balance': sum(balances.values(), Decimal('0')),
    }
