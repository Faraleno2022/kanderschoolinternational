#!/usr/bin/env python
"""
MySchoolGN - Lanceur autonome offline
=======================================
Auteur  : GS Hadja Kanfing Dian
Version : 1.0.0

Ce script lance le serveur Django en mode autonome (offline).
Conçu pour être compilé en .exe avec PyInstaller.
"""
import os
import sys
import threading
import time
import webbrowser
import socket
import hashlib
import hmac as _hmac_mod
import json as _json_mod
import secrets
import traceback
import datetime

# ─── Clé de garde anti-modification (obfusquée) ──────────────────────────────
def _gk_guard():
    _d = [138,190,148,164,175,168,168,171,128,137,152,134,169,179,174,147,
          166,170,183,162,181,152,128,178,166,181,163,152,245,247,245,243,
          152,148,162,164,178,181,162,152,140,162,190,152,177,246]
    return bytes(x ^ 0xC7 for x in _d)
_GUARD_KEY = _gk_guard()
del _gk_guard

# ─── Répertoire de base ────────────────────────────────────────────────────────
if getattr(sys, 'frozen', False):
    # Mode exe PyInstaller
    BASE_DIR = os.path.dirname(sys.executable)
    # Ajouter le dossier _MEIPASS pour trouver les modules
    if hasattr(sys, '_MEIPASS'):
        sys.path.insert(0, sys._MEIPASS)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, BASE_DIR)

# ─── Mode sans console (windowed) : rediriger stdout/stderr vers un log ────────
# En build PyInstaller avec console=False, sys.stdout / sys.stderr / sys.stdin
# valent None. Tout print() ou input() lèverait alors une exception.
# On redirige donc les sorties vers un fichier log et on neutralise stdin.
if sys.stdout is None or sys.stderr is None:
    try:
        # buffering=1 : line-buffered → le log est écrit immédiatement (diagnostic fiable)
        _log_file = open(os.path.join(BASE_DIR, 'myschool.log'), 'a', encoding='utf-8', errors='replace', buffering=1)
        if sys.stdout is None:
            sys.stdout = _log_file
        if sys.stderr is None:
            sys.stderr = _log_file
    except Exception:
        class _NullWriter:
            def write(self, *_a, **_k):
                return 0
            def flush(self):
                pass
        if sys.stdout is None:
            sys.stdout = _NullWriter()
        if sys.stderr is None:
            sys.stderr = _NullWriter()

if sys.stdin is None:
    class _NullReader:
        def readline(self, *_a, **_k):
            return ''
        def read(self, *_a, **_k):
            return ''
    sys.stdin = _NullReader()

# ─── DLLs GTK pour WeasyPrint (Windows) ───────────────────────────────────────
# Doit être fait AVANT tout import de Django / WeasyPrint
if os.name == 'nt':
    # En mode EXE, les DLLs GTK sont dans _internal/ (PyInstaller --onedir)
    # En mode dev, elles sont dans MSYS2
    _dll_dirs = [BASE_DIR]
    if getattr(sys, 'frozen', False):
        _internal = os.path.join(BASE_DIR, '_internal')
        if os.path.isdir(_internal):
            _dll_dirs.append(_internal)
    else:
        # Mode développement : utiliser MSYS2 si disponible
        _msys2_bin = r'C:\msys64\mingw64\bin'
        if os.path.isdir(_msys2_bin):
            _dll_dirs.append(_msys2_bin)

    # Ajouter tous les répertoires au PATH
    for _d in _dll_dirs:
        if _d not in os.environ.get('PATH', ''):
            os.environ['PATH'] = _d + os.pathsep + os.environ.get('PATH', '')

    # Python 3.8+ : répertoire explicite pour les DLLs (plus fiable que PATH)
    if hasattr(os, 'add_dll_directory'):
        for _d in _dll_dirs:
            if os.path.isdir(_d):
                try:
                    os.add_dll_directory(_d)
                except Exception:
                    pass

    # GdkPixbuf loaders : configurer le chemin vers les loaders bundlés
    if getattr(sys, 'frozen', False):
        _loaders_dir = os.path.join(BASE_DIR, '_internal', 'lib', 'gdk-pixbuf-2.0', '2.10.0', 'loaders')
        if os.path.isdir(_loaders_dir):
            os.environ['GDK_PIXBUF_MODULE_FILE'] = os.path.join(
                os.path.dirname(_loaders_dir), 'loaders.cache'
            )
            os.environ['GDK_PIXBUF_MODULEDIR'] = _loaders_dir

# ─── Générer une SECRET_KEY stable par installation ───────────────────────────
_secret_file = os.path.join(BASE_DIR, '.secret_key')
if os.path.exists(_secret_file):
    with open(_secret_file, 'r') as _f:
        _secret_key = _f.read().strip()
else:
    _secret_key = 'sk-' + secrets.token_hex(32)
    try:
        with open(_secret_file, 'w') as _f:
            _f.write(_secret_key)
    except Exception:
        _secret_key = 'offline-fallback-key-myschool-gn-v1-' + hashlib.md5(
            BASE_DIR.encode()
        ).hexdigest()

# ─── Variables d'environnement Django ─────────────────────────────────────────
os.environ['DJANGO_SETTINGS_MODULE'] = 'ecole_moderne.settings'
os.environ['DJANGO_DEBUG'] = 'true'
os.environ['DJANGO_SECRET_KEY'] = _secret_key
os.environ['OFFLINE_MODE'] = '1'
os.environ['TWILIO_DISABLED'] = '1'
os.environ['OPENAI_DISABLED'] = '1'

# Dossier de données Django (DB, media, logs)
os.environ['MYSCHOOL_BASE_DIR'] = BASE_DIR


def migrate_legacy_data():
    """Ramene les donnees PyInstaller 6 vers le dossier stable de l'EXE."""
    from offline_data import migrate_legacy_data_layout

    for action in migrate_legacy_data_layout(BASE_DIR):
        print(f"[MySchoolGN] {action}")


# ─── Fenêtre d'activation de licence (tkinter) ────────────────────────────────
def show_activation_window(mid: str, trial_days_left: int = 0, first_trial_prompt: bool = False) -> bool:
    """
    Affiche une fenêtre graphique d'activation de licence.
    - Si trial_days_left > 0 : le bouton "Continuer l'essai" est affiché.
    - Si first_trial_prompt=True : demande si l'utilisateur a deja une licence.
    - Si trial_days_left <= 0 : l'utilisateur DOIT activer pour continuer.
    Retourne True si l'application peut démarrer, False si l'utilisateur quitte.
    """
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox
    except ImportError:
        # tkinter non disponible (mode dev sans GUI) — accepter si essai actif
        return trial_days_left > 0

    result = [False]

    root = tk.Tk()
    root.title("MySchoolGN — Activation de la Licence")
    root.resizable(False, False)
    root.configure(bg='#ecf0f1')

    # ── Dimensions et centrage ──
    W, H = 540, 490 if first_trial_prompt else 460
    root.geometry(f"{W}x{H}")
    root.update_idletasks()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"{W}x{H}+{(sw - W) // 2}+{(sh - H) // 2}")
    root.lift()
    root.attributes('-topmost', True)
    root.after(200, lambda: root.attributes('-topmost', False))

    # ── En-tête ──
    hdr = tk.Frame(root, bg='#1a3a5c', height=72)
    hdr.pack(fill='x')
    hdr.pack_propagate(False)
    tk.Label(hdr, text="MySchoolGN",
             font=('Arial', 22, 'bold'), bg='#1a3a5c', fg='white').place(
        relx=0.5, rely=0.35, anchor='center')
    tk.Label(hdr, text="Système de Gestion Scolaire — GS Hadja Kanfing Dian",
             font=('Arial', 8), bg='#1a3a5c', fg='#aed6f1').place(
        relx=0.5, rely=0.75, anchor='center')

    # ── Corps ──
    body = tk.Frame(root, bg='#ecf0f1', padx=24, pady=16)
    body.pack(fill='both', expand=True)

    # Message de statut
    if first_trial_prompt and trial_days_left > 0:
        status_txt = ("Avez-vous deja une licence annuelle MySchoolGN ?\n"
                      "Si oui, cliquez sur Parcourir puis Activer la Licence.\n"
                      "Sinon, continuez avec la version d'essai gratuite de 30 jours.")
        status_col = '#1a5276'
    elif trial_days_left <= 0:
        status_txt = ("⚠  Votre période d'essai de 30 jours est expirée.\n"
                      "Veuillez activer votre licence pour continuer.")
        status_col = '#c0392b'
    else:
        status_txt = (f"Mode essai : {trial_days_left} jour(s) restant(s).\n"
                      "Activez votre licence pour un accès illimité.")
        status_col = '#d35400'

    tk.Label(body, text=status_txt, font=('Arial', 10), bg='#ecf0f1',
             fg=status_col, justify='left', wraplength=490).pack(
        anchor='w', pady=(0, 12))

    # ── ID Machine ──
    mid_frm = tk.LabelFrame(body, text="  Identifiant Machine  ",
                             bg='#ecf0f1', font=('Arial', 9, 'bold'),
                             fg='#1a3a5c', padx=10, pady=8, relief='groove')
    mid_frm.pack(fill='x', pady=(0, 10))
    tk.Label(mid_frm,
             text="Communiquez cet identifiant à GS Hadja Kanfing Dian pour obtenir votre licence :",
             font=('Arial', 8), bg='#ecf0f1', fg='#555').pack(anchor='w')
    mid_var = tk.StringVar(value=mid)
    tk.Entry(mid_frm, textvariable=mid_var, font=('Courier', 10, 'bold'),
             state='readonly', readonlybackground='#d5e8f7',
             relief='flat', bd=1, fg='#1a3a5c').pack(
        fill='x', pady=(4, 2), ipady=5)

    cb_btn = tk.Button(mid_frm, text="  Copier l'identifiant  ",
                       font=('Arial', 8), bg='#2980b9', fg='white',
                       relief='flat', padx=8, pady=3, cursor='hand2')
    cb_btn.pack(anchor='e', pady=(3, 0))

    def _copy_mid():
        root.clipboard_clear()
        root.clipboard_append(mid)
        cb_btn.config(text="  Copié !  ")
        root.after(2000, lambda: cb_btn.config(text="  Copier l'identifiant  "))
    cb_btn.config(command=_copy_mid)

    # ── Activation fichier .lic ──
    lic_frm = tk.LabelFrame(body,
                             text="  Activer avec un fichier de licence (.lic)  ",
                             bg='#ecf0f1', font=('Arial', 9, 'bold'),
                             fg='#1a3a5c', padx=10, pady=8, relief='groove')
    lic_frm.pack(fill='x', pady=(0, 8))

    lic_var = tk.StringVar(value="")
    lic_row = tk.Frame(lic_frm, bg='#ecf0f1')
    lic_row.pack(fill='x')
    tk.Entry(lic_row, textvariable=lic_var, font=('Arial', 9),
             state='readonly', readonlybackground='#f9f9f9',
             relief='flat', bd=1).pack(
        side='left', fill='x', expand=True, ipady=5)

    def _browse():
        p = filedialog.askopenfilename(
            title="Sélectionner votre fichier de licence",
            filetypes=[("Licence MySchoolGN", "*.lic"),
                       ("Tous les fichiers", "*.*")])
        if p:
            lic_var.set(p)
            status_lbl.config(text="", fg='#27ae60')

    tk.Button(lic_row, text="  Parcourir…  ", command=_browse,
              font=('Arial', 9), bg='#7f8c8d', fg='white',
              relief='flat', padx=6, pady=5, cursor='hand2').pack(
        side='left', padx=(6, 0))

    status_lbl = tk.Label(lic_frm, text="", font=('Arial', 9),
                          bg='#ecf0f1', fg='#27ae60')
    status_lbl.pack(anchor='w', pady=(4, 0))

    def _do_activate():
        p = lic_var.get().strip()
        if not p:
            messagebox.showwarning(
                "Fichier manquant",
                "Veuillez sélectionner un fichier .lic avant d'activer.")
            return
        try:
            import license_manager
            res = license_manager.activate_from_file(p)
        except Exception as ex:
            messagebox.showerror("Erreur", f"Erreur lors de l'activation :\n{ex}")
            return
        if res.get('valid'):
            school = res.get('school', '')
            days = res.get('days_left', 0)
            edition = res.get('edition', 'Standard')
            messagebox.showinfo(
                "Activation réussie",
                f"Licence activée avec succès !\n\n"
                f"École    : {school}\n"
                f"Édition  : {edition}\n"
                f"Validité : {days} jour(s)")
            result[0] = True
            root.destroy()
        else:
            reason = res.get('reason', 'Erreur inconnue.')
            status_lbl.config(text=f"Erreur : {reason}", fg='#c0392b')
            messagebox.showerror("Activation échouée", reason)

    # ── Boutons d'action ──
    btn_frm = tk.Frame(body, bg='#ecf0f1')
    btn_frm.pack(fill='x', pady=(4, 0))

    tk.Button(btn_frm, text="   Activer la Licence   ",
              command=_do_activate,
              font=('Arial', 11, 'bold'), bg='#27ae60', fg='white',
              relief='flat', padx=10, pady=8, cursor='hand2').pack(side='left')

    if trial_days_left > 0:
        def _continue_trial():
            result[0] = True
            root.destroy()
        tk.Button(btn_frm,
                  text=f"   Continuer avec l'essai ({trial_days_left}j)   ",
                  command=_continue_trial,
                  font=('Arial', 10), bg='#e67e22', fg='white',
                  relief='flat', padx=10, pady=8, cursor='hand2').pack(
            side='left', padx=(10, 0))

    def _on_close():
        if not result[0]:
            if messagebox.askyesno("Quitter", "Quitter MySchoolGN ?"):
                root.destroy()
                os._exit(0)   # Fermeture complète : tue tous les threads/processus
        else:
            root.destroy()

    tk.Button(btn_frm, text="  Quitter  ", command=_on_close,
              font=('Arial', 10), bg='#95a5a6', fg='white',
              relief='flat', padx=10, pady=8, cursor='hand2').pack(side='right')

    root.protocol("WM_DELETE_WINDOW", _on_close)
    root.mainloop()
    return result[0]


# ─── Protection anti-modification (garde) ──────────────────────────────────────
def _tamper_exit():
    """Arrêt immédiat si modification détectée."""
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "MySchoolGN — Erreur critique",
            "L'application a été modifiée de manière non autorisée.\n\n"
            "L'application ne peut pas démarrer.\n\n"
            "Veuillez réinstaller MySchoolGN depuis le programme\n"
            "officiel ou contactez GS Hadja Kanfing Dian."
        )
        root.destroy()
    except Exception:
        pass
    os._exit(1)


def _guard_check():
    """Vérification secondaire anti-modification (défense en profondeur)."""
    if not getattr(sys, 'frozen', False):
        return  # Mode développement

    guard_path = os.path.join(BASE_DIR, '.guard.dat')
    if not os.path.exists(guard_path):
        return  # Pas de fichier garde

    try:
        with open(guard_path, 'r', encoding='utf-8') as f:
            guard_data = _json_mod.load(f)

        stored_hash = guard_data.get('h', '')
        stored_sig = guard_data.get('s', '')

        # Vérifier la signature du fichier garde
        expected_sig = _hmac_mod.new(
            _GUARD_KEY, stored_hash.encode(), hashlib.sha256
        ).hexdigest()
        if not _hmac_mod.compare_digest(stored_sig, expected_sig):
            _tamper_exit()

        # Vérifier les empreintes des modules critiques
        import license_manager
        import integrity_check

        lm_fp = _hmac_mod.new(
            _GUARD_KEY, license_manager._DEV_SECRET, hashlib.sha256
        ).hexdigest()
        ic_fp = _hmac_mod.new(
            _GUARD_KEY, integrity_check._INTEGRITY_KEY, hashlib.sha256
        ).hexdigest()
        combined = _hmac_mod.new(
            _GUARD_KEY, (lm_fp + ic_fp).encode(), hashlib.sha256
        ).hexdigest()

        if not _hmac_mod.compare_digest(combined, stored_hash):
            _tamper_exit()

        # Canary : vérifier que la validation rejette les données invalides
        test = license_manager._validate_license_data({
            'license_data': 'GUARD_TEST', 'signature': 'INVALID'
        })
        if test.get('valid', False):
            _tamper_exit()

    except (ImportError, FileNotFoundError):
        pass
    except Exception:
        pass


# ─── Vérification d'intégrité ──────────────────────────────────────────────────
def check_integrity():
    """Vérifie que les fichiers critiques n'ont pas été modifiés."""
    try:
        import integrity_check
        result = integrity_check.verify()
        if not result['valid']:
            print("")
            print("!" * 60)
            print("   ALERTE : Fichiers de l'application modifiés !")
            print("!" * 60)
            print(f"   {result['reason']}")
            print("")
            print("   L'application a été corrompue ou modifiée.")
            print("   Veuillez réinstaller depuis le programme officiel.")
            print("   Contact : GS Hadja Kanfing Dian")
            print("!" * 60)
            print("")
            try:
                import tkinter as tk
                from tkinter import messagebox
                root = tk.Tk()
                root.withdraw()
                messagebox.showerror(
                    "MySchoolGN — Intégrité compromise",
                    "Des fichiers de l'application ont été modifiés.\n\n"
                    "L'application ne peut pas démarrer.\n\n"
                    "Veuillez réinstaller MySchoolGN depuis le programme\n"
                    "officiel ou contactez GS Hadja Kanfing Dian."
                )
                root.destroy()
            except Exception:
                pass
            os._exit(1)
        else:
            if result.get('reason') != 'dev_mode':
                print("  [Intégrité] ✓ Vérification OK")
    except ImportError:
        pass  # Mode développement, integrity_check non disponible
    except Exception as e:
        print(f"  [Intégrité] Avertissement : {e}")


# ─── Vérification de la licence ────────────────────────────────────────────────
def check_license():
    """Vérifie la licence au démarrage. Affiche une fenêtre si activation requise."""
    try:
        import license_manager
        status = license_manager.check_license_or_trial()
    except Exception as e:
        print(f"[Licence] Avertissement vérification : {e}")
        return True  # Continuer si le module est absent (dev mode)

    mid = ''
    try:
        import license_manager as _lm
        mid = _lm.get_machine_id()
    except Exception:
        pass

    if status.get('valid'):
        # Licence valide OU essai encore actif
        if status.get('trial'):
            days_left = status.get('days_left', 0)
            if status.get('trial_started'):
                print("  [ESSAI GRATUIT] Premiere utilisation detectee.")
                print("  [ESSAI GRATUIT] L'utilisateur peut activer une licence annuelle ou continuer l'essai.")
                show_activation_window(mid, trial_days_left=days_left, first_trial_prompt=True)
            elif days_left <= 7:
                print(f"  [ESSAI] Il vous reste {days_left} jour(s) d'essai.")
                print(f"  [ESSAI] Contactez GS Hadja Kanfing Dian pour acheter une licence.")
                show_activation_window(mid, trial_days_left=days_left)
            else:
                from datetime import datetime, timedelta
                exp = (datetime.utcnow() + timedelta(days=days_left)).strftime('%d/%m/%Y')
                print(f"  [ESSAI GRATUIT] {days_left} jour(s) restant(s) — expire le {exp}")
                print(f"  [ESSAI GRATUIT] Contactez GS Hadja Kanfing Dian pour obtenir une licence.")
        else:
            school = status.get('school', '')
            edition = status.get('edition', 'Standard')
            days_left = status.get('days_left', 0)
            if days_left <= 30:
                print(f"  [Licence] Expire dans {days_left} jour(s). "
                      f"Renouvelez auprès de GS Hadja Kanfing Dian.")
            else:
                print(f"  [Licence] Valide — {school} ({edition}) — {days_left}j restant(s).")
    else:
        # Essai expiré ou aucune licence → fenêtre bloquante (pas de bouton "Continuer")
        days_left = status.get('days_left', 0)
        print("")
        print("  [Licence] Activation requise — ouverture de la fenêtre d'activation...")
        can_start = show_activation_window(mid, trial_days_left=days_left)
        if not can_start:
            os._exit(0)   # Fermeture totale sans laisser Django démarrer

    return True


# ─── Utilitaires ──────────────────────────────────────────────────────────────
def find_free_port(start_port=8000, max_port=8100):
    """Trouve un port libre disponible."""
    for port in range(start_port, max_port):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('127.0.0.1', port))
                return port
        except OSError:
            continue
    return start_port


def setup_database():
    """Initialise / migre la base de données SQLite.
    
    En cas de mise à jour, sauvegarde automatiquement la DB avant migration.
    """
    # Cette etape doit preceder django.setup() : les settings utilisent deja
    # le nouvel emplacement stable pour SQLite, les medias et les journaux.
    migrate_legacy_data()

    import django
    django.setup()
    from django.conf import settings
    from django.core.management import call_command

    # Le chemin vient de Django, jamais d'une supposition : PyInstaller 6 a
    # deplace le code dans `_internal`, et la base a suivi. Deviner ce chemin
    # revenait a sauvegarder un fichier vide pendant que la vraie base, elle,
    # n'etait pas protegee.
    db_path = str(settings.DATABASES['default']['NAME'])
    is_new_db = not os.path.exists(db_path) or os.path.getsize(db_path) == 0

    # Sauvegarder la DB existante avant migration (protection des données client)
    if not is_new_db:
        backup_dir = os.path.join(BASE_DIR, 'backups')
        os.makedirs(backup_dir, exist_ok=True)
        import shutil
        backup_name = f"db_avant_migration_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.sqlite3"
        backup_path = os.path.join(backup_dir, backup_name)
        try:
            shutil.copy2(db_path, backup_path)
            print(f"[MySchoolGN] Sauvegarde DB → {backup_name}")
            # Garder seulement les 5 dernières sauvegardes automatiques
            _cleanup_old_backups(backup_dir, prefix='db_avant_migration_', keep=5)
        except Exception as e:
            print(f"[MySchoolGN] Avertissement sauvegarde DB : {e}")

    print("[MySchoolGN] Migration de la base de données...")
    call_command('migrate', '--run-syncdb', verbosity=0)

    if is_new_db:
        print("[MySchoolGN] Nouvelle installation détectée.")
        try:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            if not User.objects.filter(username='admin').exists():
                User.objects.create_superuser(
                    username='admin',
                    password='admin1234',
                    email='admin@myschool.local'
                )
                print("[MySchoolGN] Compte admin créé : admin / admin1234")
        except Exception as e:
            print(f"[MySchoolGN] Avertissement création admin : {e}")

    print("[MySchoolGN] Préparation des fichiers statiques...")
    try:
        call_command('collectstatic', '--noinput', verbosity=0)
    except Exception:
        pass


def _cleanup_old_backups(backup_dir, prefix='db_avant_migration_', keep=5):
    """Supprime les anciennes sauvegardes automatiques, garde les N plus récentes."""
    try:
        backups = sorted([
            f for f in os.listdir(backup_dir)
            if f.startswith(prefix) and f.endswith('.sqlite3')
        ])
        for old in backups[:-keep]:
            os.remove(os.path.join(backup_dir, old))
    except Exception:
        pass


def _find_modern_browser():
    """Cherche un navigateur moderne (Edge Chromium, Chrome, Firefox) sous Windows."""
    if os.name != 'nt':
        return None
    import shutil
    import subprocess
    # Chemins connus des navigateurs modernes sous Windows
    candidates = [
        # Edge Chromium
        os.path.join(os.environ.get('PROGRAMFILES(X86)', ''), 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
        os.path.join(os.environ.get('PROGRAMFILES', ''), 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
        os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
        # Google Chrome
        os.path.join(os.environ.get('PROGRAMFILES(X86)', ''), 'Google', 'Chrome', 'Application', 'chrome.exe'),
        os.path.join(os.environ.get('PROGRAMFILES', ''), 'Google', 'Chrome', 'Application', 'chrome.exe'),
        os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Google', 'Chrome', 'Application', 'chrome.exe'),
        # Firefox
        os.path.join(os.environ.get('PROGRAMFILES', ''), 'Mozilla Firefox', 'firefox.exe'),
        os.path.join(os.environ.get('PROGRAMFILES(X86)', ''), 'Mozilla Firefox', 'firefox.exe'),
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    # Tenter via PATH
    for name in ('msedge', 'chrome', 'firefox'):
        found = shutil.which(name)
        if found:
            return found
    return None


def _wait_server_ready(port, timeout=30.0):
    """Attend que le serveur Django réponde sur le port avant d'ouvrir la fenêtre."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                if s.connect_ex(('127.0.0.1', port)) == 0:
                    return True
        except OSError:
            pass
        time.sleep(0.3)
    return False


def open_browser(port):
    """Ouvre l'application dans sa PROPRE fenêtre (mode application).

    Utilise Edge/Chrome en mode --app= : une fenêtre dédiée sans barre
    d'adresse ni onglets, comme une application native (pas le navigateur).
    """
    # Attendre que le serveur réponde plutôt qu'un simple sleep fixe
    if not _wait_server_ready(port, timeout=30.0):
        time.sleep(2.5)
    url = f'http://127.0.0.1:{port}'
    print(f"[MySchoolGN] Ouverture de la fenêtre → {url}")

    # Profil dédié pour garantir une fenêtre isolée (ne se fond pas dans
    # une fenêtre Edge/Chrome déjà ouverte avec des onglets)
    profile_dir = os.path.join(BASE_DIR, '.appwindow')
    try:
        os.makedirs(profile_dir, exist_ok=True)
    except Exception:
        profile_dir = None

    browser_path = _find_modern_browser()
    # Edge et Chrome (Chromium) supportent --app= ; Firefox non.
    if browser_path and os.path.basename(browser_path).lower() in (
            'msedge.exe', 'chrome.exe', 'msedge', 'chrome'):
        try:
            import subprocess
            args = [
                browser_path,
                f'--app={url}',
                '--window-size=1280,820',
                '--no-first-run',
                '--no-default-browser-check',
            ]
            if profile_dir:
                args.append(f'--user-data-dir={profile_dir}')
            subprocess.Popen(args)
            print(f"[MySchoolGN] Fenêtre ouverte avec : {os.path.basename(browser_path)} (mode application)")
            return
        except Exception as e:
            print(f"[MySchoolGN] Erreur ouverture fenêtre application ({e}), repli navigateur")

    # Repli : ouvrir dans le navigateur par défaut
    if browser_path:
        try:
            import subprocess
            subprocess.Popen([browser_path, url])
            print(f"[MySchoolGN] Ouvert avec : {os.path.basename(browser_path)}")
            return
        except Exception as e:
            print(f"[MySchoolGN] Erreur lancement navigateur ({e}), utilisation par défaut")
    webbrowser.open(url)


def show_banner(port, license_status=None):
    """Affiche la bannière de démarrage."""
    school = ''
    edition = 'Standard'
    mode_label = 'Mode Essai'
    if license_status:
        if not license_status.get('trial'):
            school = license_status.get('school', '')
            edition = license_status.get('edition', 'Standard')
            mode_label = f'Édition {edition}'
        else:
            days_left = license_status.get('days_left', 0)
            mode_label = f'Essai — {days_left}j restant(s)'

    print("")
    print("=" * 60)
    print("   MySchoolGN - Système de Gestion Scolaire")
    print(f"   {mode_label}")
    if school:
        print(f"   {school}")
    print("=" * 60)
    print("")
    print(f"   Adresse : http://127.0.0.1:{port}")
    print(f"   Admin   : http://127.0.0.1:{port}/admin/")
    print("")
    print("   Identifiants par défaut :")
    print("     Utilisateur : admin")
    print("     Mot de passe: admin1234")
    print("")
    print("   Appuyez sur Ctrl+C pour arrêter le serveur")
    print("=" * 60)
    print("")


# ─── Affichage d'erreur fatale (mode sans console) ─────────────────────────────
def _show_fatal_error(message):
    """Affiche une erreur dans une fenêtre (pas de console en mode windowed)."""
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("MySchoolGN — Erreur", message)
        root.destroy()
    except Exception:
        pass


# ─── Point d'entrée principal ──────────────────────────────────────────────────
def main():
    """Point d'entrée principal."""
    print("")
    print("*" * 60)
    print("   MySchoolGN — GS Hadja Kanfing Dian")
    print("   Démarrage en mode offline...")
    print("*" * 60)
    print(f"   Répertoire : {BASE_DIR}")

    # Vérification anti-modification (garde)
    _guard_check()

    # Vérification d'intégrité (anti-modification)
    check_integrity()

    # Vérification de la licence
    license_status = None
    try:
        import license_manager
        license_status = license_manager.check_license_or_trial()
    except Exception:
        pass
    check_license()

    # Créer les dossiers nécessaires
    for folder in ['logs', 'media', 'staticfiles',
                   'media/photos_eleves', 'media/logos_ecoles']:
        folder_path = os.path.join(BASE_DIR, folder)
        os.makedirs(folder_path, exist_ok=True)

    # Trouver un port libre
    port = find_free_port()

    # Initialiser la base de données
    try:
        setup_database()
    except Exception as e:
        print(f"[MySchoolGN] Erreur initialisation : {e}")
        traceback.print_exc()  # Traceback complète (la vraie cause) dans myschool.log
        print("[MySchoolGN] Tentative de démarrage sans migration...")

    # Afficher la bannière
    show_banner(port, license_status)

    # Ouvrir le navigateur en arrière-plan
    browser_thread = threading.Thread(
        target=open_browser, args=(port,), daemon=True
    )
    browser_thread.start()

    # Lancer le serveur Django
    try:
        import django
        from django.apps import apps as _apps
        # django.setup() a déjà été appelé dans setup_database().
        # On ne le rappelle QUE si le registre n'est pas prêt, pour éviter
        # l'erreur "populate() isn't reentrant" qui masquerait la vraie cause.
        if not _apps.ready:
            django.setup()
        from django.core.management import call_command
        call_command('runserver', f'127.0.0.1:{port}', '--noreload')
    except KeyboardInterrupt:
        print("\n[MySchoolGN] Arrêt du serveur...")
        print("[MySchoolGN] Au revoir !")
    except Exception as e:
        print(f"\n[MySchoolGN] Erreur : {e}")
        traceback.print_exc()  # Traceback complète dans myschool.log (diagnostic)
        _show_fatal_error(f"Erreur au démarrage du serveur :\n\n{e}")


if __name__ == '__main__':
    _log_path = os.path.join(BASE_DIR, 'startup_error.log')
    try:
        main()
    except SystemExit:
        raise
    except Exception as _crash:
        _msg = (
            f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
            f"CRASH AU DÉMARRAGE\n"
            f"{traceback.format_exc()}\n"
        )
        try:
            with open(_log_path, 'a', encoding='utf-8') as _f:
                _f.write(_msg)
        except Exception:
            pass
        print(_msg)
        _show_fatal_error(
            "MySchoolGN n'a pas pu démarrer.\n\n"
            f"Détail technique :\n{_crash}\n\n"
            f"Un rapport a été enregistré dans :\n{_log_path}"
        )
