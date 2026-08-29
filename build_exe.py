#!/usr/bin/env python
"""
MySchoolGN - Script de compilation automatique
===============================================
Ce script automatise la compilation de l'application en .exe
avec PyInstaller et prepare le dossier de distribution.
"""

import os
import sys
import shutil
import subprocess
from glob import glob

# Repertoire du projet
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(BASE_DIR, 'dist')
BUILD_DIR = os.path.join(BASE_DIR, 'build')
OUTPUT_DIR = os.path.join(DIST_DIR, 'MySchoolGN')


def step(msg):
    print(f"\n{'='*60}")
    print(f"  {msg}")
    print(f"{'='*60}\n")


def check_prereqs():
    """Verifie les prerequis."""
    step("Verification des prerequis")

    # Verifier PyInstaller
    try:
        import PyInstaller
        print(f"  [OK] PyInstaller {PyInstaller.__version__}")
    except ImportError:
        print("  [MANQUANT] PyInstaller - Installation en cours...")
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'pyinstaller'])
        print("  [OK] PyInstaller installe")

    # Verifier Django
    try:
        import django
        print(f"  [OK] Django {django.get_version()}")
    except ImportError:
        print("  [ERREUR] Django non installe!")
        sys.exit(1)

    # Verifier les autres dependances critiques
    for pkg_name, import_name in [('reportlab', 'reportlab'), ('openpyxl', 'openpyxl'),
                                   ('Pillow', 'PIL'), ('python-dotenv', 'dotenv')]:
        try:
            __import__(import_name)
            print(f"  [OK] {pkg_name}")
        except ImportError:
            print(f"  [MANQUANT] {pkg_name} - Installation...")
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', pkg_name])


def collect_static():
    """Collecte les fichiers statiques Django."""
    step("Collecte des fichiers statiques")
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ecole_moderne.settings')
    os.environ['DJANGO_DEBUG'] = 'true'
    os.environ['DJANGO_SECRET_KEY'] = 'build-key-temp'

    try:
        subprocess.check_call([
            sys.executable, 'manage.py', 'collectstatic', '--noinput'
        ], cwd=BASE_DIR)
        print("  [OK] Fichiers statiques collectes")
    except subprocess.CalledProcessError:
        print("  [AVERTISSEMENT] Erreur lors de collectstatic (non critique)")


def run_pyinstaller():
    """Execute PyInstaller avec le fichier spec."""
    step("Compilation avec PyInstaller")

    spec_file = os.path.join(BASE_DIR, 'myschool.spec')
    if not os.path.exists(spec_file):
        print(f"  [ERREUR] Fichier spec introuvable: {spec_file}")
        sys.exit(1)

    # Nettoyer les anciens builds
    for d in [BUILD_DIR, os.path.join(DIST_DIR, 'MySchoolGN')]:
        if os.path.exists(d):
            print(f"  Suppression de {d}...")
            shutil.rmtree(d)

    # Lancer PyInstaller
    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--clean',
        '--noconfirm',
        spec_file
    ]
    print(f"  Commande: {' '.join(cmd)}")
    subprocess.check_call(cmd, cwd=BASE_DIR)
    print("  [OK] Compilation terminee")


def copy_extra_files():
    """Copie les fichiers supplementaires dans le dossier de distribution."""
    step("Copie des fichiers supplementaires")

    if not os.path.exists(OUTPUT_DIR):
        print(f"  [ERREUR] Dossier de sortie introuvable: {OUTPUT_DIR}")
        return

    # Copier les templates (au cas ou PyInstaller les aurait manques)
    templates_src = os.path.join(BASE_DIR, 'templates')
    templates_dst = os.path.join(OUTPUT_DIR, 'templates')
    if os.path.exists(templates_src) and not os.path.exists(templates_dst):
        shutil.copytree(templates_src, templates_dst)
        print("  [OK] Templates copies")

    # Copier les fichiers statiques
    static_src = os.path.join(BASE_DIR, 'static')
    static_dst = os.path.join(OUTPUT_DIR, 'static')
    if os.path.exists(static_src) and not os.path.exists(static_dst):
        shutil.copytree(static_src, static_dst)
        print("  [OK] Fichiers statiques copies")

    # Ne jamais copier le dossier media complet : il contient les photos,
    # logos et documents des utilisateurs du poste de compilation. Nettoyer
    # aussi une eventuelle collecte PyInstaller, puis n'autoriser que les deux
    # ressources generiques necessaires a une installation neuve.
    for media_dst in [
        os.path.join(OUTPUT_DIR, 'media'),
        os.path.join(OUTPUT_DIR, '_internal', 'media'),
    ]:
        if os.path.exists(media_dst):
            shutil.rmtree(media_dst)

    default_media = [
        ('eleves', 'default', 'avatar.jpg'),
        ('ecoles', 'default', 'logo.png'),
    ]
    for relative_parts in default_media:
        media_src = os.path.join(BASE_DIR, 'media', *relative_parts)
        media_dst = os.path.join(OUTPUT_DIR, 'media', *relative_parts)
        if not os.path.isfile(media_src):
            raise FileNotFoundError(f"Media par defaut introuvable: {media_src}")
        os.makedirs(os.path.dirname(media_dst), exist_ok=True)
        shutil.copy2(media_src, media_dst)
        print(f"  [OK] Media par defaut copie : {os.path.join(*relative_parts)}")

    # NE PAS livrer les donnees du developpeur.
    # PyInstaller collecte db.sqlite3 dans `_internal` malgre son exclusion du
    # .spec : ne nettoyer que la racine laissait donc la base du dev dans la
    # distribution, prete a ecraser celle du client a la mise a jour.
    # run_server.py cree une base vierge au premier demarrage.
    for dev_file in ['db.sqlite3', 'license.dat', '.trial_start', '.secret_key', '.env']:
        for location in [OUTPUT_DIR, os.path.join(OUTPUT_DIR, '_internal')]:
            dev_dst = os.path.join(location, dev_file)
            if os.path.exists(dev_dst):
                os.remove(dev_dst)
                print(f"  [INFO] {os.path.relpath(dev_dst, OUTPUT_DIR)} du dev supprime du build")

    # Les licences nominatives du poste de compilation sont sensibles elles
    # aussi. Une licence client ne doit entrer que via l'installateur.
    for location in [OUTPUT_DIR, os.path.join(OUTPUT_DIR, '_internal')]:
        for license_path in glob(os.path.join(location, 'license_*.lic')):
            os.remove(license_path)
            print(f"  [INFO] {os.path.relpath(license_path, OUTPUT_DIR)} du dev supprime du build")

    # Creer les dossiers necessaires
    for folder in ['logs', 'media', 'backups']:
        folder_path = os.path.join(OUTPUT_DIR, folder)
        os.makedirs(folder_path, exist_ok=True)

    print("  [OK] Fichiers supplementaires copies")


def create_launcher_bat():
    """Cree un fichier .bat de lancement facile."""
    step("Creation du lanceur .bat")

    bat_content = '''@echo off
title MySchoolGN - Systeme de Gestion Scolaire
echo.
echo ============================================================
echo    MySchoolGN - Systeme de Gestion Scolaire
echo    Version Offline
echo ============================================================
echo.
echo Demarrage du serveur...
echo.
cd /d "%~dp0"
MySchoolGN.exe
pause
'''
    bat_path = os.path.join(OUTPUT_DIR, 'Demarrer_MySchoolGN.bat')
    with open(bat_path, 'w', encoding='utf-8') as f:
        f.write(bat_content)
    print(f"  [OK] Lanceur cree: {bat_path}")


def create_stop_bat():
    """Cree un fichier .bat pour arreter le serveur."""
    bat_content = '''@echo off
echo Arret de MySchoolGN...
taskkill /F /IM MySchoolGN.exe >nul 2>&1
echo Serveur arrete.
timeout /t 2 >nul
'''
    bat_path = os.path.join(OUTPUT_DIR, 'Arreter_MySchoolGN.bat')
    with open(bat_path, 'w', encoding='utf-8') as f:
        f.write(bat_content)
    print(f"  [OK] Script d'arret cree: {bat_path}")


def copy_gtk_dlls():
    """Copie les DLLs GTK/Pango/Cairo pour WeasyPrint offline."""
    step("Copie des DLLs GTK pour WeasyPrint")

    gtk_dll_dir = r'C:\msys64\mingw64\bin'
    internal_dir = os.path.join(OUTPUT_DIR, '_internal')

    if not os.path.isdir(gtk_dll_dir):
        print("  [AVERTISSEMENT] MSYS2 non trouve - DLLs GTK non copiees")
        return

    gtk_dlls = [
        'libpango-1.0-0.dll', 'libpangocairo-1.0-0.dll',
        'libpangoft2-1.0-0.dll', 'libpangowin32-1.0-0.dll',
        'libcairo-2.dll', 'libcairo-gobject-2.dll',
        'libgobject-2.0-0.dll', 'libglib-2.0-0.dll',
        'libgio-2.0-0.dll', 'libgmodule-2.0-0.dll',
        'libgdk_pixbuf-2.0-0.dll', 'libfontconfig-1.dll',
        'libfreetype-6.dll', 'libfribidi-0.dll',
        'libharfbuzz-0.dll', 'libintl-8.dll',
        'libiconv-2.dll', 'libpixman-1-0.dll',
        'libpng16-16.dll', 'libexpat-1.dll',
        'libpcre2-8-0.dll', 'zlib1.dll',
        'libffi-8.dll', 'libgraphite2.dll',
        'libbrotlidec.dll', 'libbrotlicommon.dll',
        'libbz2-1.dll', 'libstdc++-6.dll',
        'libgcc_s_seh-1.dll', 'libwinpthread-1.dll',
    ]

    copied = 0
    for dll in gtk_dlls:
        src = os.path.join(gtk_dll_dir, dll)
        dst = os.path.join(internal_dir, dll)
        if os.path.exists(src) and not os.path.exists(dst):
            shutil.copy2(src, dst)
            copied += 1
    print(f"  [OK] {copied} DLLs GTK copiees dans _internal/")

    # Copier les loaders GdkPixbuf
    loaders_src = r'C:\msys64\mingw64\lib\gdk-pixbuf-2.0\2.10.0\loaders'
    loaders_dst = os.path.join(internal_dir, 'lib', 'gdk-pixbuf-2.0', '2.10.0', 'loaders')
    if os.path.isdir(loaders_src) and not os.path.isdir(loaders_dst):
        shutil.copytree(loaders_src, loaders_dst)
        # Copier aussi le loaders.cache
        cache_src = os.path.join(os.path.dirname(loaders_src), 'loaders.cache')
        if os.path.exists(cache_src):
            shutil.copy2(cache_src, os.path.join(os.path.dirname(loaders_dst), 'loaders.cache'))
        print("  [OK] GdkPixbuf loaders copies")


def show_summary():
    """Affiche le resume de la compilation."""
    step("COMPILATION TERMINEE")

    # Calculer la taille du dossier
    total_size = 0
    for dirpath, dirnames, filenames in os.walk(OUTPUT_DIR):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            total_size += os.path.getsize(fp)
    size_mb = total_size / (1024 * 1024)

    print(f"  Dossier de sortie: {OUTPUT_DIR}")
    print(f"  Taille totale:     {size_mb:.1f} Mo")
    print(f"")
    print(f"  Fichiers principaux:")
    print(f"    - MySchoolGN.exe           (Application)")
    print(f"    - Demarrer_MySchoolGN.bat  (Lanceur)")
    print(f"    - Arreter_MySchoolGN.bat   (Arret)")
    print(f"")
    print(f"  Pour tester:")
    print(f"    1. Ouvrez le dossier: {OUTPUT_DIR}")
    print(f"    2. Double-cliquez sur 'Demarrer_MySchoolGN.bat'")
    print(f"    3. Le navigateur s'ouvrira sur http://127.0.0.1:8000")
    print(f"")
    print(f"  Pour creer l'installateur:")
    print(f"    - Installez Inno Setup (https://jrsoftware.org/isinfo.php)")
    print(f"    - Compilez le fichier 'installer_myschool.iss'")
    print(f"")


def generate_integrity_manifest():
    """Genere le manifeste d'integrite dans le dossier de distribution."""
    step("Generation du manifeste d'integrite")

    if not os.path.exists(OUTPUT_DIR):
        print("  [ERREUR] Dossier de sortie introuvable")
        return

    # Copier integrity_check.py TEMPORAIREMENT pour generer le manifeste
    ic_src = os.path.join(BASE_DIR, 'integrity_check.py')
    ic_dst = os.path.join(OUTPUT_DIR, 'integrity_check.py')
    if os.path.exists(ic_src):
        shutil.copy2(ic_src, ic_dst)

    # Generer le manifeste depuis le dossier de distribution
    try:
        env = os.environ.copy()
        env['PYTHONPATH'] = OUTPUT_DIR
        env['PYTHONIOENCODING'] = 'utf-8'
        env['PYTHONUTF8'] = '1'
        subprocess.check_call(
            [sys.executable, ic_dst, '--generate'],
            cwd=OUTPUT_DIR,
            env=env,
        )
        print("  [OK] Manifeste d'integrite genere")
    except subprocess.CalledProcessError as e:
        print(f"  [AVERTISSEMENT] Erreur generation manifeste : {e}")
    except Exception as e:
        print(f"  [AVERTISSEMENT] {e}")


def protect_source_files():
    """Supprime les fichiers source .py lisibles de la distribution.

    PROTECTION ANTI-MODIFICATION : Les modules critiques sont compiles
    en bytecode dans le PYZ par PyInstaller (via hiddenimports).
    Les copies .py lisibles sont supprimees pour empecher un attaquant
    de les ouvrir dans un editeur et modifier le code.
    """
    step("Protection anti-modification des fichiers source")

    if not os.path.exists(OUTPUT_DIR):
        print("  [ERREUR] Dossier de sortie introuvable")
        return

    critical_files = [
        'integrity_check.py',
        'license_manager.py',
        'load_env.py',
    ]

    removed = []
    for fname in critical_files:
        for location in [OUTPUT_DIR, os.path.join(OUTPUT_DIR, '_internal')]:
            fpath = os.path.join(location, fname)
            if os.path.exists(fpath):
                os.remove(fpath)
                removed.append(os.path.relpath(fpath, OUTPUT_DIR))

    for r in removed:
        print(f"  [OK] Source supprime : {r}")

    if not removed:
        print("  [INFO] Aucun fichier source expose trouve")

    print(f"  [OK] {len(removed)} fichier(s) source supprime(s) de la distribution")


def generate_guard_file():
    """Genere le fichier de garde .guard.dat pour la verification anti-modification.

    Ce fichier contient les empreintes HMAC des cles secretes des modules critiques.
    Il est verifie par run_server.py (compile dans l'EXE) au demarrage.
    Cle de garde differente des cles d'integrite et de licence.
    """
    step("Generation du fichier de garde anti-modification")

    if not os.path.exists(OUTPUT_DIR):
        print("  [ERREUR] Dossier de sortie introuvable")
        return

    import hmac as _hmac
    import hashlib as _hl
    import json

    # Cle de garde (identique a celle dans run_server.py)
    def _gk():
        _d = [138,190,148,164,175,168,168,171,128,137,152,134,169,179,174,147,
              166,170,183,162,181,152,128,178,166,181,163,152,245,247,245,243,
              152,148,162,164,178,181,162,152,140,162,190,152,177,246]
        return bytes(x ^ 0xC7 for x in _d)
    guard_key = _gk()

    # Importer les modules depuis les sources du projet
    _saved_path = sys.path[:]
    sys.path.insert(0, BASE_DIR)

    for mod_name in ['license_manager', 'integrity_check']:
        if mod_name in sys.modules:
            del sys.modules[mod_name]

    try:
        import license_manager
        import integrity_check

        # Calculer les empreintes des cles secretes
        lm_fp = _hmac.new(guard_key, license_manager._DEV_SECRET, _hl.sha256).hexdigest()
        ic_fp = _hmac.new(guard_key, integrity_check._INTEGRITY_KEY, _hl.sha256).hexdigest()
        combined = _hmac.new(guard_key, (lm_fp + ic_fp).encode(), _hl.sha256).hexdigest()

        # Signer
        sig = _hmac.new(guard_key, combined.encode(), _hl.sha256).hexdigest()

        guard_data = {'h': combined, 's': sig}

        guard_path = os.path.join(OUTPUT_DIR, '.guard.dat')
        with open(guard_path, 'w', encoding='utf-8') as f:
            json.dump(guard_data, f)

        print(f"  [OK] Fichier de garde genere : .guard.dat")
        print(f"  [OK] Empreintes des modules critiques enregistrees")

    except Exception as e:
        print(f"  [ERREUR] Impossible de generer le fichier de garde : {e}")
    finally:
        sys.path[:] = _saved_path


def main():
    print("")
    print("*" * 60)
    print("  MySchoolGN - Compilation en .exe")
    print("  AVEC PROTECTION ANTI-MODIFICATION")
    print("*" * 60)

    os.chdir(BASE_DIR)

    check_prereqs()
    collect_static()
    run_pyinstaller()
    copy_extra_files()
    copy_gtk_dlls()
    create_launcher_bat()
    create_stop_bat()
    generate_guard_file()
    generate_integrity_manifest()
    protect_source_files()
    show_summary()


if __name__ == '__main__':
    main()
