# -*- mode: python ; coding: utf-8 -*-
"""
MySchoolGN - PyInstaller Spec File
====================================
Auteur  : GS Hadja Kanfing Dian
Version : 1.0.0

Pour compiler :
    venv\\Scripts\\python.exe -m PyInstaller --clean --noconfirm myschool.spec
"""

import os
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

PROJECT_DIR = SPECPATH

# ─── Hidden imports ────────────────────────────────────────────────────────────
hiddenimports = []

# Django core (sans GIS qui exige GDAL)
hiddenimports += collect_submodules('django', filter=lambda name: 'gis' not in name)
hiddenimports += collect_submodules('django.contrib.admin')
hiddenimports += collect_submodules('django.contrib.auth')
hiddenimports += collect_submodules('django.contrib.contenttypes')
hiddenimports += collect_submodules('django.contrib.sessions')
hiddenimports += collect_submodules('django.contrib.messages')
hiddenimports += collect_submodules('django.contrib.staticfiles')
hiddenimports += collect_submodules('django.contrib.humanize')
hiddenimports += collect_submodules('django.template')
hiddenimports += collect_submodules('django.db.backends.sqlite3')

# Applications du projet
for _app in ['eleves', 'paiements', 'depenses', 'salaires', 'utilisateurs',
             'rapports', 'administration', 'bus', 'notes', 'abonnements',
             'chatbot', 'ecole_moderne', 'synchronisation']:
    try:
        hiddenimports += collect_submodules(_app)
    except Exception:
        pass

# Librairies tierces
hiddenimports += collect_submodules('reportlab')
hiddenimports += collect_submodules('openpyxl')
hiddenimports += collect_submodules('PIL')

# django-axes (protection brute-force, present dans INSTALLED_APPS)
try:
    hiddenimports += collect_submodules('axes')
except Exception:
    pass

# whitenoise (WhiteNoiseMiddleware reference par chaine dans MIDDLEWARE
# -> non detectable statiquement par PyInstaller, charge a l'init WSGI)
try:
    hiddenimports += collect_submodules('whitenoise')
except Exception:
    pass

# Pandas (import/export eleves)
try:
    hiddenimports += collect_submodules('pandas')
    hiddenimports += collect_submodules('numpy')
except Exception:
    pass

# WeasyPrint et ses dependances
for _wp_pkg in ['weasyprint', 'pydyf', 'fonttools', 'cssselect2',
                'tinycss2', 'tinyhtml5', 'brotli', 'zopfli']:
    try:
        hiddenimports += collect_submodules(_wp_pkg)
    except Exception:
        pass

# cffi / pycparser (requis par weasyprint.text.ffi via FFI().cdef())
# IMPORTANT: pycparser.ply.yacc utilise les DOCSTRINGS comme règles de grammaire
# → optimize=2 (qui supprime les docstrings) casse le parser → on utilise optimize=1
for _cffi_pkg in ['cffi', 'pycparser', 'pycparser.ply']:
    try:
        hiddenimports += collect_submodules(_cffi_pkg)
    except Exception:
        pass
hiddenimports += [
    'cffi', 'cffi.api', 'cffi.cparser', 'cffi.backend_ctypes',
    'pycparser', 'pycparser.c_parser', 'pycparser.c_lexer',
    'pycparser.ply', 'pycparser.ply.yacc', 'pycparser.ply.lex',
    'pycparser.lextab', 'pycparser.yacctab',
]

# Modules explicites
hiddenimports += [
    # Django management
    'django.core.management.commands.migrate',
    'django.core.management.commands.collectstatic',
    'django.core.management.commands.runserver',
    'django.db.backends.sqlite3.base',
    'django.db.backends.sqlite3.introspection',
    'django.contrib.admin.apps',
    # Projet
    'ecole_moderne.settings',
    'ecole_moderne.urls',
    'ecole_moderne.wsgi',
    'ecole_moderne.static_views',
    'ecole_moderne.middleware',
    'ecole_moderne.security_middleware',
    'ecole_moderne.image_cache_middleware',
    'ecole_moderne.image_optimization_middleware',
    # Utils
    'load_env',
    'dotenv',
    'sqlite3',
    '_sqlite3',
    'sqlparse',
    'asgiref',
    'asgiref.sync',
    'asgiref.local',
    'six',
    'dateutil',
    'dateutil.parser',
    'dateutil.relativedelta',
    # Tkinter (fenêtre d'activation de licence)
    'tkinter',
    'tkinter.ttk',
    'tkinter.filedialog',
    'tkinter.messagebox',
    '_tkinter',
    # Encodages Windows
    'encodings',
    'encodings.utf_8',
    'encodings.ascii',
    'encodings.latin_1',
    'encodings.cp1252',
    'encodings.cp850',
    # Reseau / stdlib
    'socket',
    'webbrowser',
    'threading',
    'winreg',
    'hmac',
    'hashlib',
    'base64',
    'json',
    # JWT / auth
    'jwt',
    'jwt.algorithms',
    # Intégrité
    'integrity_check',
    # Licence (import dynamique dans run_server.py)
    'license_manager',
]

# ─── Données à inclure ─────────────────────────────────────────────────────────
datas = []

def _add_if_exists(src_rel, dst):
    src = os.path.join(PROJECT_DIR, src_rel)
    if os.path.exists(src):
        datas.append((src, dst))

# Dossiers applicatifs uniquement. Les medias sont des donnees utilisateur et
# ne doivent jamais etre captures depuis le poste de compilation. Les deux
# ressources par defaut sont ajoutees explicitement par build_exe.py.
_add_if_exists('templates', 'templates')
_add_if_exists('static', 'static')
_add_if_exists('staticfiles', 'staticfiles')

# Base de données : NE PAS inclure la DB du dev dans le build
# Elle sera créée automatiquement via 'migrate' au premier lancement chez le client
# _add_if_exists('db.sqlite3', '.')

# Le fichier .env contient des secrets et ne doit jamais entrer dans le build.

# PROTECTION ANTI-MODIFICATION :
# Les modules critiques (integrity_check, license_manager, load_env) sont
# inclus via hiddenimports (compilés en bytecode dans le PYZ).
# Ils ne sont PAS copiés comme fichiers .py lisibles.
# Cela empêche un attaquant de les ouvrir dans un éditeur.

# Templates et templatetags + migrations de chaque app
for _app in ['eleves', 'paiements', 'depenses', 'salaires', 'utilisateurs',
             'rapports', 'administration', 'bus', 'notes', 'abonnements', 'chatbot',
             'synchronisation']:
    _add_if_exists(os.path.join(_app, 'templates'), os.path.join(_app, 'templates'))
    _add_if_exists(os.path.join(_app, 'templatetags'), os.path.join(_app, 'templatetags'))
    _add_if_exists(os.path.join(_app, 'fixtures'), os.path.join(_app, 'fixtures'))
    _add_if_exists(os.path.join(_app, 'migrations'), os.path.join(_app, 'migrations'))

# Migrations ecole_moderne
_add_if_exists('ecole_moderne/migrations', 'ecole_moderne/migrations')

# Données Django (templates admin, etc.)
datas += collect_data_files('django.contrib.admin')
datas += collect_data_files('django.contrib.auth')
datas += collect_data_files('django')

# django-axes : migrations, templates, locale
try:
    datas += collect_data_files('axes')
except Exception:
    pass

# ReportLab (polices)
try:
    datas += collect_data_files('reportlab')
except Exception:
    pass

# WeasyPrint (feuilles CSS par défaut)
try:
    datas += collect_data_files('weasyprint')
except Exception:
    pass

try:
    datas += collect_data_files('tinycss2')
except Exception:
    pass

# pycparser : tables PLY pré-générées (lextab.py, yacctab.py, ply/*.py)
# Ces fichiers sont indispensables pour que cffi/WeasyPrint fonctionnent
# dans l'exe PyInstaller sans avoir à régénérer le parser depuis les docstrings
try:
    datas += collect_data_files('pycparser')
except Exception:
    pass
try:
    import pycparser as _pcp
    _pcp_dir = os.path.dirname(_pcp.__file__)
    # Inclure explicitement les tables pré-compilées et le sous-dossier ply
    for _f in ['lextab.py', 'yacctab.py', '_c_ast.cfg', '_build_tables.py']:
        _fp = os.path.join(_pcp_dir, _f)
        if os.path.exists(_fp):
            datas.append((_fp, 'pycparser'))
    _ply_dir = os.path.join(_pcp_dir, 'ply')
    if os.path.isdir(_ply_dir):
        datas.append((_ply_dir, 'pycparser/ply'))
except Exception:
    pass

# Pillow
try:
    datas += collect_data_files('PIL')
except Exception:
    pass

# ─── Icône ────────────────────────────────────────────────────────────────────
_icon_candidates = [
    os.path.join(PROJECT_DIR, 'myschool.ico'),
    os.path.join(PROJECT_DIR, 'static', 'logos', 'logo.ico'),
]
_icon = next((c for c in _icon_candidates if os.path.exists(c)), None)

# ─── DLLs GTK/Pango/Cairo pour WeasyPrint (depuis MSYS2) ──────────────────────
_gtk_dll_dir = r'C:\msys64\mingw64\bin'
_gtk_dlls = [
    'libpango-1.0-0.dll',
    'libpangocairo-1.0-0.dll',
    'libpangoft2-1.0-0.dll',
    'libpangowin32-1.0-0.dll',
    'libcairo-2.dll',
    'libcairo-gobject-2.dll',
    'libgobject-2.0-0.dll',
    'libglib-2.0-0.dll',
    'libgio-2.0-0.dll',
    'libgmodule-2.0-0.dll',
    'libgdk_pixbuf-2.0-0.dll',
    'libfontconfig-1.dll',
    'libfreetype-6.dll',
    'libfribidi-0.dll',
    'libharfbuzz-0.dll',
    'libintl-8.dll',
    'libiconv-2.dll',
    'libpixman-1-0.dll',
    'libpng16-16.dll',
    'libexpat-1.dll',
    'libpcre2-8-0.dll',
    'zlib1.dll',
    'libffi-8.dll',
    'libgraphite2.dll',
    'libbrotlidec.dll',
    'libbrotlicommon.dll',
    'libbz2-1.dll',
    'libstdc++-6.dll',
    'libgcc_s_seh-1.dll',
    'libwinpthread-1.dll',
]
_gtk_binaries = []
for _dll in _gtk_dlls:
    _dll_path = os.path.join(_gtk_dll_dir, _dll)
    if os.path.exists(_dll_path):
        _gtk_binaries.append((_dll_path, '.'))
    else:
        print(f'[ATTENTION] DLL manquante: {_dll}')

# GdkPixbuf loaders (nécessaires pour le rendu d'images dans les PDFs)
_pixbuf_loaders_dir = r'C:\msys64\mingw64\lib\gdk-pixbuf-2.0\2.10.0\loaders'
if os.path.isdir(_pixbuf_loaders_dir):
    import glob as _glob
    for _loader in _glob.glob(os.path.join(_pixbuf_loaders_dir, '*.dll')):
        _gtk_binaries.append((_loader, 'lib/gdk-pixbuf-2.0/2.10.0/loaders'))
    _loaders_cache = os.path.join(os.path.dirname(_pixbuf_loaders_dir), 'loaders.cache')
    if os.path.exists(_loaders_cache):
        datas.append((_loaders_cache, 'lib/gdk-pixbuf-2.0/2.10.0'))

# ─── Analyse ──────────────────────────────────────────────────────────────────
a = Analysis(
    [os.path.join(PROJECT_DIR, 'run_server.py')],
    pathex=[PROJECT_DIR],
    binaries=[] + _gtk_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'scipy',
        'IPython',
        'jupyter',
        'notebook',
        'pytest',
        'mypy',
        'black',
        'flake8',
        'django.contrib.gis',
        'mysqlclient',
        'PyMySQL',
        # 'license_manager' is now a regular Python module (integrity-protected)
    ],
    noarchive=False,
    # optimize=1 : supprime seulement les assert statements (pas les docstrings)
    # optimize=2 était utilisé avant mais il supprime les DOCSTRINGS, ce qui casse
    # pycparser.ply.yacc qui utilise les docstrings comme règles de grammaire
    # → WeasyPrint (via cffi → pycparser) levait "Unable to build parser"
    optimize=1,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MySchoolGN',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='MySchoolGN',
)

# ─── Post-build: license_manager.py is now protected by integrity manifest ─────
print('[Protection] license_manager.py is integrity-protected (no .pyd needed).')
