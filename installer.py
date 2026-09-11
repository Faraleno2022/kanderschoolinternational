#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
MySchoolGN - Installateur Automatique
=======================================
Auteur  : GS Hadja Kanfing Dian
Version : 1.0.0

Cet installateur copie MySchoolGN vers C:/MySchoolGN/
et cree un raccourci sur le Bureau.
Supporte le mode Mise à jour : préserve les données existantes.
"""

import os
import sys
import shutil
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import winreg
import ctypes
from pathlib import Path

# ─── Répertoire source (là où se trouve cet installateur) ─────────────────────
if getattr(sys, 'frozen', False):
    SRC_DIR = Path(sys.executable).parent
else:
    SRC_DIR = Path(__file__).parent

INSTALL_DIR  = Path("C:/MySchoolGN")
APP_NAME     = "MySchoolGN"
APP_VERSION  = "1.0.0"
PUBLISHER    = "GS Hadja Kanfing Dian"
EXE_NAME     = "MySchoolGN.exe"
ICON_NAME    = "myschool.ico"

# ─── Détection mode mise à jour ───────────────────────────────────────────────
IS_UPDATE = (INSTALL_DIR / EXE_NAME).exists()

# Fichiers/dossiers à NE PAS écraser lors d'une mise à jour (données utilisateur)
UPDATE_PRESERVE_FILES = {'db.sqlite3', 'license.dat', '.trial_start',
                          '.secret_key', '.env', '.integrity.dat'}
UPDATE_PRESERVE_DIRS  = {'media', 'backups', 'logs'}


# ─── Création du raccourci .lnk ───────────────────────────────────────────────
def create_shortcut(target: str, shortcut_path: str, icon: str = None,
                    description: str = "", working_dir: str = ""):
    """
    Crée un raccourci Windows .lnk via PowerShell (méthode la plus fiable).
    Fallback VBScript si PowerShell est bloqué.
    """
    wdir = working_dir or str(Path(target).parent)
    icon_loc = icon if icon else target

    # ── Méthode 1 : PowerShell (disponible sur tout Windows moderne) ──────────
    try:
        import subprocess
        icon_line = f'$sc.IconLocation = "{icon_loc},0"; '
        ps_script = (
            f'$ws = New-Object -ComObject WScript.Shell; '
            f'$sc = $ws.CreateShortcut("{shortcut_path}"); '
            f'$sc.TargetPath = "{target}"; '
            f'$sc.WorkingDirectory = "{wdir}"; '
            f'$sc.Description = "{description}"; '
            f'{icon_line}'
            f'$sc.Save()'
        )
        result = subprocess.run(
            ['powershell', '-NoProfile', '-NonInteractive',
             '-ExecutionPolicy', 'Bypass',
             '-Command', ps_script],
            capture_output=True, timeout=15
        )
        if result.returncode == 0 and Path(shortcut_path).exists():
            return True
    except Exception:
        pass

    # ── Méthode 2 : VBScript (fallback universel) ─────────────────────────────
    try:
        import tempfile, subprocess
        icon_line2 = f'oSC.IconLocation = "{icon_loc},0"\n'
        vbs = (
            'Set oWS = WScript.CreateObject("WScript.Shell")\n'
            f'Set oSC = oWS.CreateShortcut("{shortcut_path}")\n'
            f'oSC.TargetPath = "{target}"\n'
            f'oSC.WorkingDirectory = "{wdir}"\n'
            f'oSC.Description = "{description}"\n'
            f'{icon_line2}'
            'oSC.Save()\n'
        )
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.vbs', encoding='ascii', errors='ignore', delete=False
        ) as f:
            vbs_path = f.name
            f.write(vbs)
        subprocess.run(['cscript', '//NoLogo', vbs_path],
                       capture_output=True, timeout=15)
        try:
            os.remove(vbs_path)
        except Exception:
            pass
        if Path(shortcut_path).exists():
            return True
    except Exception:
        pass

    # ── Méthode 3 : win32com (si disponible) ─────────────────────────────────
    try:
        import win32com.client
        shell = win32com.client.Dispatch("WScript.Shell")
        sc = shell.CreateShortCut(shortcut_path)
        sc.Targetpath = target
        sc.WorkingDirectory = wdir
        sc.Description = description
        sc.IconLocation = f"{icon_loc},0"
        sc.save()
        return True
    except Exception:
        pass

    return False


def get_desktop() -> Path:
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders")
        desktop, _ = winreg.QueryValueEx(key, "Desktop")
        return Path(desktop)
    except Exception:
        return Path.home() / "Desktop"


def get_startmenu() -> Path:
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders")
        programs, _ = winreg.QueryValueEx(key, "Programs")
        return Path(programs)
    except Exception:
        return Path.home() / "AppData/Roaming/Microsoft/Windows/Start Menu/Programs"


# ─── Logique d'installation / mise à jour ─────────────────────────────────────
def do_install(log_func, progress_func, done_func, license_source=None):
    try:
        if IS_UPDATE:
            # ── MODE MISE À JOUR ──────────────────────────────────────────────
            log_func("=== Mode Mise à jour détecté ===")
            log_func(f"Installation existante : {INSTALL_DIR}")
            log_func("─" * 50)

            # Arrêter l'application si elle est en cours d'exécution
            log_func("Arrêt de l'application en cours (si active)...")
            import subprocess, time
            try:
                subprocess.run(
                    ['taskkill', '/F', '/IM', EXE_NAME, '/T'],
                    capture_output=True, timeout=10
                )
                time.sleep(1)
                log_func("  Application arrêtée.")
            except Exception:
                pass
            progress_func(10)

            # Copier les fichiers (racine du SRC_DIR) sans écraser les données
            log_func("Mise à jour des fichiers de l'application ...")
            items = list(SRC_DIR.iterdir())
            skip_installer = {EXE_NAME, "Installer_MySchoolGN.exe",
                               "installer.py", "installer.exe"}
            total = len(items)
            updated = 0
            preserved = 0

            for i, item in enumerate(items):
                # Ignorer l'installateur lui-même
                if item.name in skip_installer:
                    progress_func(10 + int(75 * (i + 1) / total))
                    continue

                # Préserver les données utilisateur (fichiers)
                if item.name in UPDATE_PRESERVE_FILES:
                    log_func(f"  [PRESERVE] {item.name}")
                    preserved += 1
                    progress_func(10 + int(75 * (i + 1) / total))
                    continue

                # Préserver les données utilisateur (dossiers)
                if item.name in UPDATE_PRESERVE_DIRS:
                    log_func(f"  [PRESERVE] {item.name}/")
                    preserved += 1
                    progress_func(10 + int(75 * (i + 1) / total))
                    continue

                dst = INSTALL_DIR / item.name
                try:
                    if item.is_dir():
                        if dst.exists():
                            shutil.rmtree(dst)
                        shutil.copytree(item, dst)
                    else:
                        shutil.copy2(item, dst)
                    log_func(f"  {item.name}")
                    updated += 1
                except Exception as e:
                    log_func(f"  [AVERT] {item.name} : {e}")
                progress_func(10 + int(75 * (i + 1) / total))

            progress_func(100)
            log_func(f"\n  {updated} fichiers mis à jour, {preserved} préservés.")
            log_func("\n✓ Mise à jour terminée avec succès !")
            log_func(f"  Dossier : {INSTALL_DIR}")
            log_func("  Vos données ont été préservées.")
            done_func(True)

        else:
            # ── MODE INSTALLATION FRAÎCHE ─────────────────────────────────────
            # ── 1. Créer le répertoire d'installation
            log_func("Création du répertoire C:\\MySchoolGN ...")
            INSTALL_DIR.mkdir(parents=True, exist_ok=True)
            progress_func(5)

            # ── 2. Copier tous les fichiers
            log_func("Copie des fichiers de l'application ...")
            items = list(SRC_DIR.iterdir())
            # Exclure les fichiers d'essai/licence/données dev pour que le client parte de zéro
            skip = {"Installer_MySchoolGN.exe", "installer.py",
                    ".trial_start", "license.dat", ".secret_key",
                    "db.sqlite3", ".env", ".integrity.dat"}
            total = len(items)

            for i, item in enumerate(items):
                if item.name in skip:
                    continue
                dst = INSTALL_DIR / item.name
                try:
                    if item.is_dir():
                        if dst.exists():
                            shutil.rmtree(dst)
                        shutil.copytree(item, dst)
                    else:
                        shutil.copy2(item, dst)
                    log_func(f"  {item.name}")
                except Exception as e:
                    log_func(f"  [AVERT] {item.name} : {e}")
                progress_func(5 + int(75 * (i + 1) / total))

            # ── 3. Créer le raccourci Bureau
            log_func("Creation du raccourci sur le Bureau ...")
            target     = str(INSTALL_DIR / EXE_NAME)
            ico_file   = INSTALL_DIR / ICON_NAME
            icon       = str(ico_file) if ico_file.exists() else target
            desktop    = get_desktop()
            lnk_path   = str(desktop / f"{APP_NAME}.lnk")
            ok = create_shortcut(target, lnk_path, icon,
                                 "MySchoolGN - Systeme de Gestion Scolaire",
                                 str(INSTALL_DIR))
            log_func(f"  Raccourci Bureau : {'OK' if ok else 'echec'}")
            progress_func(85)

            # ── 4. Raccourci Menu Démarrer
            log_func("Creation du raccourci Menu Demarrer ...")
            sm_dir = get_startmenu() / APP_NAME
            sm_dir.mkdir(parents=True, exist_ok=True)
            create_shortcut(target, str(sm_dir / f"{APP_NAME}.lnk"), icon,
                            "Demarrer MySchoolGN", str(INSTALL_DIR))
            progress_func(90)

            # ── 5. Enregistrement dans le registre Windows
            log_func("Enregistrement dans le registre Windows ...")
            reg_path = (r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
                        r"\MySchoolGN")
            try:
                key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, reg_path)
                winreg.SetValueEx(key, "DisplayName",     0, winreg.REG_SZ,
                                  "MySchoolGN - Système de Gestion Scolaire")
                winreg.SetValueEx(key, "DisplayVersion",  0, winreg.REG_SZ, APP_VERSION)
                winreg.SetValueEx(key, "Publisher",       0, winreg.REG_SZ, PUBLISHER)
                winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, str(INSTALL_DIR))
                winreg.SetValueEx(key, "DisplayIcon",     0, winreg.REG_SZ, icon)
                winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ,
                                  str(INSTALL_DIR / "desinstaller.bat"))
                winreg.SetValueEx(key, "NoModify",        0, winreg.REG_DWORD, 1)
                winreg.SetValueEx(key, "NoRepair",        0, winreg.REG_DWORD, 1)
                winreg.CloseKey(key)
            except Exception as e:
                log_func(f"  [AVERT] Registre : {e}")
            progress_func(98)

            # ── 6. Créer le script de désinstallation
            log_func("Création du désinstallateur ...")
            uninst = INSTALL_DIR / "desinstaller.bat"
            uninst.write_text(
                "@echo off\n"
                "echo Desinstallation de MySchoolGN...\n"
                "taskkill /F /IM MySchoolGN.exe >nul 2>&1\n"
                f'rd /s /q "{INSTALL_DIR}"\n'
                f'del /f /q "%USERPROFILE%\\Desktop\\{APP_NAME}.lnk" >nul 2>&1\n'
                "reg delete \"HKCU\\Software\\Microsoft\\Windows\\CurrentVersion"
                "\\Uninstall\\MySchoolGN\" /f >nul 2>&1\n"
                "echo Desinstallation terminee.\n"
                "pause\n",
                encoding="utf-8"
            )

            if license_source:
                log_func("Activation de la licence fournie ...")
                try:
                    shutil.copy2(license_source, INSTALL_DIR / "license.dat")
                    shutil.copy2(license_source, INSTALL_DIR / Path(license_source).name)
                    log_func("  Licence installee avec succes.")
                except Exception as e:
                    log_func(f"  [AVERT] Licence non installee : {e}")
            else:
                log_func("  Aucune licence fournie : essai gratuit de 30 jours au premier lancement.")

            progress_func(100)
            log_func("\n✓ Installation terminée avec succès !")
            log_func(f"  Dossier : {INSTALL_DIR}")
            log_func("  Raccourci créé sur le Bureau.")
            done_func(True)

    except Exception as e:
        log_func(f"\n✗ Erreur : {e}")
        done_func(False)


# ─── Interface graphique ───────────────────────────────────────────────────────
class InstallerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        if IS_UPDATE:
            self.title(f"Mise à jour de {APP_NAME}")
        else:
            self.title(f"Installation de {APP_NAME}")
        self.resizable(False, False)
        self.configure(bg="#1a2744")

        # Centrer la fenêtre
        w, h = 620, 560
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

        # Icône
        ico = SRC_DIR / ICON_NAME
        if ico.exists():
            try:
                self.iconbitmap(str(ico))
            except Exception:
                pass

        self._build_ui()

    def _build_ui(self):
        BG     = "#1a2744"
        ACCENT = "#f5a623"
        WHITE  = "#ffffff"
        GREEN  = "#27ae60"

        # ── En-tête ──────────────────────────────────────────────────────────
        header = tk.Frame(self, bg=BG, height=100)
        header.pack(fill="x")
        header.pack_propagate(False)

        tk.Label(header, text="MySchoolGN", font=("Segoe UI", 22, "bold"),
                 fg=WHITE, bg=BG).pack(pady=(18, 0))

        if IS_UPDATE:
            sub_text = "Mise à jour disponible  •  GS Hadja Kanfing Dian"
        else:
            sub_text = "Système de Gestion Scolaire  •  GS Hadja Kanfing Dian"
        tk.Label(header, text=sub_text,
                 font=("Segoe UI", 9), fg="#a0b0c8", bg=BG).pack()

        # ── Séparateur ───────────────────────────────────────────────────────
        tk.Frame(self, bg=ACCENT, height=3).pack(fill="x")

        # ── Corps ────────────────────────────────────────────────────────────
        body = tk.Frame(self, bg="#f5f7fa")
        body.pack(fill="both", expand=True, padx=0, pady=0)

        # Info installation
        info_frame = tk.Frame(body, bg="#f5f7fa")
        info_frame.pack(fill="x", padx=28, pady=(20, 8))

        if IS_UPDATE:
            info_label_text = "Mise à jour vers :"
        else:
            info_label_text = "Répertoire d'installation :"

        tk.Label(info_frame, text=info_label_text,
                 font=("Segoe UI", 9, "bold"), fg="#333", bg="#f5f7fa").pack(anchor="w")

        path_frame = tk.Frame(info_frame, bg="#dde3ea", bd=0, relief="flat")
        path_frame.pack(fill="x", pady=(4, 0))
        tk.Label(path_frame, text=f"  {INSTALL_DIR}  ",
                 font=("Consolas", 10), fg="#1a2744", bg="#dde3ea",
                 anchor="w").pack(side="left", pady=6)

        if IS_UPDATE:
            tk.Label(info_frame,
                     text="Vos données (base de données, licence, médias) seront préservées.",
                     font=("Segoe UI", 9), fg=GREEN, bg="#f5f7fa",
                     justify="left").pack(anchor="w", pady=(6, 0))

        # Barre de progression
        prog_frame = tk.Frame(body, bg="#f5f7fa")
        prog_frame.pack(fill="x", padx=28, pady=(14, 6))

        tk.Label(prog_frame, text="Progression :",
                 font=("Segoe UI", 9, "bold"), fg="#333", bg="#f5f7fa").pack(anchor="w")

        self.progress_var = tk.DoubleVar(value=0)
        style = ttk.Style()
        style.theme_use("default")
        style.configure("Blue.Horizontal.TProgressbar",
                         troughcolor="#dde3ea",
                         background=ACCENT,
                         thickness=20)
        self.pb = ttk.Progressbar(prog_frame, variable=self.progress_var,
                                   maximum=100, length=540,
                                   style="Blue.Horizontal.TProgressbar")
        self.pb.pack(pady=(4, 0), fill="x")

        self.pct_label = tk.Label(prog_frame, text="0 %",
                                   font=("Segoe UI", 9), fg="#555", bg="#f5f7fa")
        self.pct_label.pack(anchor="e")

        # Zone de log
        log_frame = tk.Frame(body, bg="#f5f7fa")
        log_frame.pack(fill="both", expand=True, padx=28, pady=(4, 10))

        tk.Label(log_frame, text="Journal :",
                 font=("Segoe UI", 9, "bold"), fg="#333", bg="#f5f7fa").pack(anchor="w")

        text_frame = tk.Frame(log_frame, bg="#1e1e2e", bd=1, relief="solid")
        text_frame.pack(fill="both", expand=True, pady=(4, 0))

        self.log_text = tk.Text(text_frame, bg="#1e1e2e", fg="#c8d8f0",
                                 font=("Consolas", 9), relief="flat",
                                 state="disabled", wrap="word", height=10)
        sb = tk.Scrollbar(text_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log_text.pack(fill="both", expand=True, padx=6, pady=6)

        # ── Séparateur + Barre de boutons ────────────────────────────────────
        tk.Frame(self, bg=ACCENT, height=2).pack(fill="x")

        btn_frame = tk.Frame(self, bg="#dfe6e9", pady=14, padx=20)
        btn_frame.pack(fill="x")

        if IS_UPDATE:
            btn_label   = "  Mettre à jour  "
            status_text = "Prêt à mettre à jour."
        else:
            btn_label   = "  Installer  "
            status_text = "Prêt à installer."

        self.install_btn = tk.Button(
            btn_frame, text=btn_label,
            font=("Segoe UI", 11, "bold"),
            bg=ACCENT, fg="#1a2744",
            activebackground="#e09010", activeforeground="#1a2744",
            relief="flat", cursor="hand2", padx=24, pady=11, bd=0,
            command=self._start_install
        )
        self.install_btn.pack(side="right", padx=(8, 0))

        self.cancel_btn = tk.Button(
            btn_frame, text="  Annuler  ",
            font=("Segoe UI", 11, "bold"),
            bg="#e74c3c", fg="white",
            activebackground="#c0392b", activeforeground="white",
            relief="flat", cursor="hand2", padx=18, pady=11, bd=0,
            command=self.destroy
        )
        self.cancel_btn.pack(side="right", padx=(0, 6))

        self.status_label = tk.Label(btn_frame, text=status_text,
                                      font=("Segoe UI", 9), fg="#555",
                                      bg="#dfe6e9")
        self.status_label.pack(side="left", padx=4)

    # ── Méthodes ─────────────────────────────────────────────────────────────
    def _log(self, msg: str):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
        self.update_idletasks()

    def _set_progress(self, val: float):
        self.progress_var.set(val)
        self.pct_label.configure(text=f"{int(val)} %")
        self.update_idletasks()

    def _start_install(self):
        license_source = None
        if IS_UPDATE:
            action_text = "Mise à jour..."
            status_text = "Mise à jour en cours, veuillez patienter..."
            log_start   = "Démarrage de la mise à jour..."
        else:
            has_license = messagebox.askyesno(
                "Licence MySchoolGN",
                "Avez-vous deja une licence annuelle MySchoolGN ?\n\n"
                "Oui : selectionnez votre fichier .lic pour l'ajouter pendant l'installation.\n"
                "Non : l'installation continuera avec la version d'essai gratuite de 30 jours."
            )
            if has_license:
                license_source = filedialog.askopenfilename(
                    title="Selectionner le fichier de licence annuelle",
                    filetypes=[("Licence MySchoolGN", "*.lic"), ("Tous les fichiers", "*.*")]
                )
                if not license_source:
                    messagebox.showinfo(
                        "Licence non selectionnee",
                        "Aucun fichier de licence n'a ete selectionne.\n"
                        "L'installation continuera avec l'essai gratuit de 30 jours."
                    )
            action_text = "Installation..."
            status_text = "Installation en cours, veuillez patienter..."
            log_start   = "Démarrage de l'installation..."

        self.install_btn.configure(state="disabled", text=f"  {action_text}")
        self.cancel_btn.configure(state="disabled")
        self.status_label.configure(text=status_text)
        self._log(log_start)
        self._log(f"Source      : {SRC_DIR}")
        self._log(f"Destination : {INSTALL_DIR}")
        self._log("─" * 50)

        t = threading.Thread(
            target=do_install,
            args=(self._log, self._set_progress, self._on_done, license_source),
            daemon=True
        )
        t.start()

    def _on_done(self, success: bool):
        self.after(0, self._finish, success)

    def _finish(self, success: bool):
        if success:
            if IS_UPDATE:
                status_text = "✓ Mise à jour réussie ! Cliquez sur Terminer."
            else:
                status_text = "✓ Installation réussie ! Cliquez sur Terminer."
            self.install_btn.configure(
                text="  Terminer  ",
                bg="#27ae60", fg="white",
                state="normal",
                command=self._launch_and_close
            )
            self.cancel_btn.configure(state="disabled")
            self.status_label.configure(text=status_text, fg="#27ae60")
        else:
            self.install_btn.configure(
                text="  Réessayer  ",
                state="normal",
                command=self._start_install
            )
            self.cancel_btn.configure(state="normal")
            self.status_label.configure(
                text="✗ Échec. Consultez le journal.",
                fg="#e74c3c"
            )

    def _launch_and_close(self):
        import subprocess
        exe = INSTALL_DIR / EXE_NAME
        if exe.exists():
            subprocess.Popen([str(exe)], cwd=str(INSTALL_DIR),
                             creationflags=0x00000008)  # DETACHED_PROCESS
        self.destroy()


# ─── Point d'entrée ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = InstallerApp()
    app.mainloop()
