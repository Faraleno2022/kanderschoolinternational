; MySchoolGN - Inno Setup Installer Script
; ==========================================
; Auteur  : GS Hadja Kanfing Dian
; Version : 1.2.0
;
; Prérequis : Inno Setup 6+ (https://jrsoftware.org/isinfo.php)
;
; Pour compiler :
;   1. Installez Inno Setup
;   2. Ouvrez ce fichier dans Inno Setup Compiler
;   3. Appuyez sur Ctrl+F9 (Compile)
;   4. L'installateur est créé dans le dossier "Output"
;
; Supporte :
;   - Installation fraîche
;   - Mise à jour (préserve base de données, licences, médias, config)

[Setup]
; ── Identification ─────────────────────────────────────────────────────────────
AppId={{B7E4A2D1-F3C8-4B91-A5E6-GS2024HADJA01}
AppName=MySchoolGN
AppVersion=1.2.0
AppVerName=MySchoolGN 1.2.0
AppPublisher=GS Hadja Kanfing Dian
AppPublisherURL=https://myschoolgn.space
AppSupportURL=https://myschoolgn.space
AppCopyright=Copyright © 2024 GS Hadja Kanfing Dian. Tous droits réservés.

; ── Installation ───────────────────────────────────────────────────────────────
DefaultDirName={autopf}\MySchoolGN
DefaultGroupName=MySchoolGN
AllowNoIcons=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; Fermeture automatique de l application avant mise a jour
CloseApplications=force
RestartApplications=no

; ── Sortie ─────────────────────────────────────────────────────────────────────
OutputDir=Output
OutputBaseFilename=MySchoolGN_Setup_v1.2.0

; ── Icône et splash ────────────────────────────────────────────────────────────
SetupIconFile=myschool.ico

; ── Compression ────────────────────────────────────────────────────────────────
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes

; ── Interface ──────────────────────────────────────────────────────────────────
WizardStyle=modern
WizardSizePercent=120
DisableWelcomePage=no

; ── Désinstallation ────────────────────────────────────────────────────────────
UninstallDisplayName=MySchoolGN - Système de Gestion Scolaire
UninstallDisplayIcon={autopf}\MySchoolGN\MySchoolGN.exe
CreateUninstallRegKey=yes

; ── Version info (visible dans Programmes et fonctionnalités) ──────────────────
VersionInfoVersion=1.2.0.0
VersionInfoCompany=GS Hadja Kanfing Dian
VersionInfoDescription=MySchoolGN - Système de Gestion Scolaire
VersionInfoCopyright=Copyright © 2024 GS Hadja Kanfing Dian

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon";   Description: "Créer un raccourci sur le Bureau";         GroupDescription: "Raccourcis :"
Name: "startmenuicon"; Description: "Créer une entrée dans le menu Démarrer";   GroupDescription: "Raccourcis :"
Name: "autostart";     Description: "Lancer MySchoolGN au démarrage de Windows"; GroupDescription: "Options :";   Flags: unchecked

[Files]
; Application compilée. Toutes les données modifiables et tous les secrets sont
; exclus par sécurité, même si le script de build devait être contourné.
Source: "dist\MySchoolGN\*"; DestDir: "{app}"; Excludes: "db.sqlite3,_internal\db.sqlite3,.env,_internal\.env,.secret_key,_internal\.secret_key,.trial_start,_internal\.trial_start,license.dat,_internal\license.dat,license_*.lic,_internal\license_*.lic,.data_layout_v2,_internal\.data_layout_v2,media\*,_internal\media\*"; Flags: ignoreversion recursesubdirs createallsubdirs

; Seules les ressources media génériques sont autorisées dans l'installateur.
Source: "dist\MySchoolGN\media\eleves\default\avatar.jpg"; DestDir: "{app}\media\eleves\default"; Flags: ignoreversion
Source: "dist\MySchoolGN\media\ecoles\default\logo.png"; DestDir: "{app}\media\ecoles\default"; Flags: ignoreversion

; Script de désinstallation
Source: "desinstaller.bat"; DestDir: "{app}"; Flags: ignoreversion

; Script d'arrêt du serveur (raccourci menu Démarrer)
Source: "Arreter_MySchoolGN.bat"; DestDir: "{app}"; Flags: ignoreversion

; Le gestionnaire de licence est compilé dans MySchoolGN.exe et protégé par
; le manifeste d'intégrité. Ne jamais livrer sa source Python modifiable.

; Icône
Source: "myschool.ico"; DestDir: "{app}"; Flags: ignoreversion

[Dirs]
; Dossiers avec permissions d'écriture
Name: "{app}\logs";                 Permissions: users-modify
Name: "{app}\media";                Permissions: users-modify
Name: "{app}\media\photos_eleves";  Permissions: users-modify
Name: "{app}\media\logos_ecoles";   Permissions: users-modify
Name: "{app}\backups";              Permissions: users-modify
Name: "{app}\staticfiles";          Permissions: users-modify

[Icons]
; Bureau
Name: "{autodesktop}\MySchoolGN"; Filename: "{app}\MySchoolGN.exe"; WorkingDir: "{app}"; IconFilename: "{app}\myschool.ico"; Comment: "MySchoolGN - Système de Gestion Scolaire"; Tasks: desktopicon

; Menu Démarrer
Name: "{group}\MySchoolGN";                        Filename: "{app}\MySchoolGN.exe";         WorkingDir: "{app}"; IconFilename: "{app}\myschool.ico"; Comment: "Démarrer MySchoolGN"
Name: "{group}\Arrêter MySchoolGN";                Filename: "{app}\Arreter_MySchoolGN.bat"; WorkingDir: "{app}"; Comment: "Arrêter le serveur MySchoolGN"
Name: "{group}\{cm:UninstallProgram,MySchoolGN}";  Filename: "{uninstallexe}"

; Démarrage automatique (optionnel)
Name: "{userstartup}\MySchoolGN"; Filename: "{app}\MySchoolGN.exe"; WorkingDir: "{app}"; Tasks: autostart

[Registry]
; Enregistrement pour le panneau "Programmes et fonctionnalités"
Root: HKCU; Subkey: "Software\GS Hadja Kanfing Dian\MySchoolGN"; ValueType: string; ValueName: "Version";    ValueData: "1.2.0"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\GS Hadja Kanfing Dian\MySchoolGN"; ValueType: string; ValueName: "InstallDir"; ValueData: "{app}";  Flags: uninsdeletevalue

[Run]
; Proposer de lancer l'application après installation
Filename: "{app}\MySchoolGN.exe"; Description: "Démarrer MySchoolGN maintenant"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Arrêter le serveur avant la désinstallation
Filename: "taskkill"; Parameters: "/F /IM MySchoolGN.exe"; Flags: runhidden; RunOnceId: "KillServer"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\staticfiles"
Type: filesandordirs; Name: "{app}\__pycache__"
Type: files;          Name: "{app}\.secret_key"
Type: files;          Name: "{app}\install_path.txt"

[Messages]
WelcomeLabel1=Bienvenue dans l'assistant d'installation de MySchoolGN
WelcomeLabel2=Ce programme va installer MySchoolGN - Système de Gestion Scolaire sur votre ordinateur.%n%nMySchoolGN est une solution complète de gestion scolaire développée par GS Hadja Kanfing Dian. Elle fonctionne entièrement hors ligne.%n%nFermez toutes les autres applications avant de continuer.
FinishedHeadingLabel=Installation de MySchoolGN terminée !
FinishedLabel=MySchoolGN a été installé avec succès sur votre ordinateur.%n%nIdentifiants par défaut :%n  Utilisateur : admin%n  Mot de passe  : admin1234%n%nL'application s'ouvre dans sa propre fenêtre.%n%nNOTE : Si aucune licence annuelle n'a été ajoutée pendant l'installation, une période d'essai de 30 jours démarre automatiquement.

[Code]

// ──────────────────────────────────────────────────────────────────────────────
// Variables globales pour la gestion des mises à jour
// ──────────────────────────────────────────────────────────────────────────────
var
  IsUpdate: Boolean;
  BackupTempDir: String;
  LicenseQuestionAsked: Boolean;
  SelectedLicenseFile: String;

// ── Détection si c'est une mise à jour ───────────────────────────────────────
function IsUpgradeInstall(): Boolean;
var
  ExePath: String;
begin
  ExePath := WizardDirValue + '\MySchoolGN.exe';
  Result := FileExists(ExePath);
end;

// ── Afficher l'ID machine à la fin pour l'activation ─────────────────────────
function GetMachineId(): String;
var
  MachineGuid: String;
begin
  if RegQueryStringValue(HKEY_LOCAL_MACHINE,
    'SOFTWARE\Microsoft\Cryptography', 'MachineGuid', MachineGuid) then
    Result := MachineGuid
  else
    Result := 'Indisponible';
end;

// ── Arrêter l'application si elle est en cours d'exécution ───────────────────
procedure KillRunningApp();
var
  ResultCode: Integer;
begin
  Exec('taskkill', '/F /IM MySchoolGN.exe /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(500);
end;

// ── Emplacements des donnees persistantes ────────────────────────────────────
// La version actuelle utilise toujours la racine de l'installation. Une
// ancienne version PyInstaller 6 peut cependant avoir écrit dans `_internal`.
function FichierNonVide(const FileName: String): Boolean;
var
  FileBytes: Int64;
begin
  Result := FileExists(FileName) and FileSize64(FileName, FileBytes) and (FileBytes > 0);
end;

function CheminBaseExistante(): String;
var
  RootPath, InternalPath: String;
begin
  RootPath := ExpandConstant('{app}\db.sqlite3');
  InternalPath := ExpandConstant('{app}\_internal\db.sqlite3');

  // Après migration, la base racine est canonique. Sur une ancienne version,
  // la racine était souvent un leurre vide : dans ce cas utiliser _internal.
  if FichierNonVide(RootPath) then
    Result := 'db.sqlite3'
  else if FichierNonVide(InternalPath) then
    Result := '_internal\db.sqlite3'
  else if FileExists(RootPath) then
    Result := 'db.sqlite3'
  else
    Result := '_internal\db.sqlite3';
end;

function CheminDossierExistant(const DirName: String): String;
begin
  if (CheminBaseExistante() = '_internal\db.sqlite3') and
     DirExists(ExpandConstant('{app}\_internal\') + DirName) then
    Result := '_internal\' + DirName
  else
    Result := DirName;
end;

// ── Copier un fichier vers le dossier de sauvegarde temporaire ───────────────
procedure BackupFileAs(const SourceName, BackupName: String);
var
  SrcPath, DstPath: String;
begin
  SrcPath := ExpandConstant('{app}\') + SourceName;
  DstPath := BackupTempDir + '\' + BackupName;
  if FileExists(SrcPath) then
  begin
    Log('Sauvegarde : ' + SourceName + ' -> ' + BackupName);
    ForceDirectories(ExtractFileDir(DstPath));
    if not CopyFile(SrcPath, DstPath, False) then
      RaiseException('Impossible de sauvegarder le fichier critique : ' + SourceName);
  end;
end;

procedure BackupFile(const FileName: String);
begin
  BackupFileAs(FileName, FileName);
end;

// ── Restaurer un fichier depuis le dossier de sauvegarde temporaire ──────────
procedure RestoreFile(const FileName: String);
var
  SrcPath, DstPath: String;
begin
  SrcPath := BackupTempDir + '\' + FileName;
  DstPath := ExpandConstant('{app}\') + FileName;
  if FileExists(SrcPath) then
  begin
    Log('Restauration : ' + FileName);
    ForceDirectories(ExtractFileDir(DstPath));
    if not CopyFile(SrcPath, DstPath, False) then
      RaiseException('Impossible de restaurer le fichier critique : ' + FileName);
  end;
end;

// ── Copier récursivement un dossier ──────────────────────────────────────────
procedure BackupDirectoryAs(const SourceDirName, BackupDirName: String);
var
  SrcDir, DstDir: String;
  FindRec: TFindRec;
begin
  SrcDir := ExpandConstant('{app}\') + SourceDirName;
  DstDir := BackupTempDir + '\' + BackupDirName;
  if DirExists(SrcDir) then
  begin
    Log('Sauvegarde dossier : ' + SourceDirName + ' -> ' + BackupDirName);
    ForceDirectories(DstDir);
    if FindFirst(SrcDir + '\*', FindRec) then
    try
      repeat
        if (FindRec.Name <> '.') and (FindRec.Name <> '..') then
        begin
          if (FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then
            BackupDirectoryAs(
              SourceDirName + '\' + FindRec.Name,
              BackupDirName + '\' + FindRec.Name
            )
          else
            if not CopyFile(SrcDir + '\' + FindRec.Name, DstDir + '\' + FindRec.Name, False) then
              RaiseException('Impossible de sauvegarder : ' + SourceDirName + '\' + FindRec.Name);
        end;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
end;

procedure BackupDirectory(const DirName: String);
begin
  BackupDirectoryAs(DirName, DirName);
end;

// ── Restaurer récursivement un dossier ───────────────────────────────────────
procedure RestoreDirectory(const DirName: String);
var
  SrcDir, DstDir: String;
  FindRec: TFindRec;
begin
  SrcDir := BackupTempDir + '\' + DirName;
  DstDir := ExpandConstant('{app}\') + DirName;
  if DirExists(SrcDir) then
  begin
    Log('Restauration dossier : ' + DirName);
    ForceDirectories(DstDir);
    if FindFirst(SrcDir + '\*', FindRec) then
    try
      repeat
        if (FindRec.Name <> '.') and (FindRec.Name <> '..') then
        begin
          if (FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then
            RestoreDirectory(DirName + '\' + FindRec.Name)
          else
            if not CopyFile(SrcDir + '\' + FindRec.Name, DstDir + '\' + FindRec.Name, False) then
              RaiseException('Impossible de restaurer : ' + DirName + '\' + FindRec.Name);
        end;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
end;

// ── Supprimer récursivement un dossier temporaire ────────────────────────────
procedure CleanupBackupDir();
begin
  if DirExists(BackupTempDir) then
    DelTree(BackupTempDir, True, True, True);
end;

// ── Sauvegarde des données utilisateur avant l'installation ──────────────────
procedure BackupUserData();
var
  FindRec: TFindRec;
  AppDir: String;
begin
  BackupTempDir := ExpandConstant('{tmp}\MySchoolGN_UpdateBackup');
  CleanupBackupDir();
  ForceDirectories(BackupTempDir);

  // Fichiers de données critiques
  // Toujours restaurer dans le nouvel emplacement canonique a la racine.
  BackupFileAs(CheminBaseExistante(), 'db.sqlite3');
  BackupFile('.secret_key');
  BackupFile('.trial_start');
  BackupFile('.env');
  BackupFile('license.dat');

  // Tous les fichiers de licence (license_*.lic)
  AppDir := ExpandConstant('{app}\');
  if FindFirst(AppDir + 'license_*.lic', FindRec) then
  try
    repeat
      BackupFile(FindRec.Name);
    until not FindNext(FindRec);
  finally
    FindClose(FindRec);
  end;

  // Dossier media (photos élèves, logos écoles, etc.)
  BackupDirectoryAs(CheminDossierExistant('media'), 'media');

  // Dossier backups
  BackupDirectory('backups');

  // Dossier logs
  BackupDirectoryAs(CheminDossierExistant('logs'), 'logs');
end;

// ── Restauration des données utilisateur après l'installation ────────────────
procedure RestoreUserData();
var
  FindRec: TFindRec;
begin
  // Fichiers de données critiques
  RestoreFile('db.sqlite3');
  RestoreFile('.secret_key');
  RestoreFile('.trial_start');
  RestoreFile('.env');
  RestoreFile('license.dat');

  // Restaurer tous les fichiers de licence
  if FindFirst(BackupTempDir + '\license_*.lic', FindRec) then
  try
    repeat
      RestoreFile(FindRec.Name);
    until not FindNext(FindRec);
  finally
    FindClose(FindRec);
  end;

  // Restaurer le dossier media
  RestoreDirectory('media');

  // Restaurer le dossier backups
  RestoreDirectory('backups');

  // Restaurer le dossier logs
  RestoreDirectory('logs');

  // Nettoyage du dossier temporaire
  CleanupBackupDir();
end;

// ── Question licence pendant l'installation fraîche ─────────────────────────
procedure AskLicenseBeforeInstall();
var
  LicenseFile: String;
begin
  LicenseQuestionAsked := True;
  SelectedLicenseFile := '';

  if WizardSilent() then
    Exit;

  if MsgBox(
    'Avez-vous déjà une licence annuelle MySchoolGN ?' + #13#10 + #13#10 +
    'Oui : sélectionnez votre fichier .lic pour l''ajouter pendant l''installation.' + #13#10 +
    'Non : MySchoolGN continuera avec la version d''essai gratuite de 30 jours.',
    mbConfirmation, MB_YESNO
  ) = IDYES then
  begin
    LicenseFile := '';
    if GetOpenFileName(
      'Sélectionner le fichier de licence annuelle',
      LicenseFile,
      '',
      'Fichiers de licence (*.lic;*.dat)|*.lic;*.dat|Tous les fichiers (*.*)|*.*',
      'lic'
    ) then
    begin
      SelectedLicenseFile := LicenseFile;
      MsgBox(
        'Licence sélectionnée.' + #13#10 + #13#10 +
        'Elle sera ajoutée automatiquement pendant l''installation.',
        mbInformation, MB_OK
      );
    end
    else
    begin
      MsgBox(
        'Aucune licence sélectionnée.' + #13#10 +
        'MySchoolGN continuera avec l''essai gratuit de 30 jours.',
        mbInformation, MB_OK
      );
    end;
  end;
end;

procedure InstallSelectedLicense();
var
  DestFile: String;
begin
  if SelectedLicenseFile = '' then
  begin
    Log('Aucune licence fournie : essai gratuit de 30 jours au premier lancement.');
    Exit;
  end;

  DestFile := ExpandConstant('{app}\license.dat');
  if CopyFile(SelectedLicenseFile, DestFile, False) then
  begin
    CopyFile(SelectedLicenseFile, ExpandConstant('{app}\') + ExtractFileName(SelectedLicenseFile), False);
    Log('Licence installée : ' + ExtractFileName(SelectedLicenseFile));
    MsgBox(
      'Licence ajoutée avec succès.' + #13#10 + #13#10 +
      'MySchoolGN démarrera en version activée.',
      mbInformation, MB_OK
    );
  end
  else
  begin
    Log('Licence non installée : impossible de copier le fichier sélectionné.');
    MsgBox(
      'Impossible de copier la licence dans le dossier d''installation.' + #13#10 +
      'Vous pourrez l''activer plus tard depuis MySchoolGN.',
      mbError, MB_OK
    );
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = wpReady) and (not IsUpdate) and (not LicenseQuestionAsked) then
    AskLicenseBeforeInstall();
end;

// ── Adapter les messages selon le mode (installation / mise à jour) ──────────
procedure CurPageChanged(CurPageID: Integer);
var
  WelcomeMsg: String;
  FinishedMsg: String;
begin
  if CurPageID = wpWelcome then
  begin
    IsUpdate := IsUpgradeInstall();
    if IsUpdate then
    begin
      WizardForm.WelcomeLabel1.Caption := 'Mise à jour de MySchoolGN';
      WelcomeMsg := 'Ce programme va mettre à jour MySchoolGN vers la version 1.2.0 sur votre ordinateur.' + #13#10 + #13#10 +
        'Vos données seront automatiquement préservées :' + #13#10 +
        '  • Base de données (élèves, notes, etc.)' + #13#10 +
        '  • Licences et période d''essai' + #13#10 +
        '  • Photos et médias' + #13#10 +
        '  • Sauvegardes' + #13#10 + #13#10 +
        'L''application sera fermée automatiquement pendant la mise à jour.' + #13#10 + #13#10 +
        'Cliquez sur Suivant pour continuer.';
      WizardForm.WelcomeLabel2.Caption := WelcomeMsg;
    end;
  end;

  if CurPageID = wpFinished then
  begin
    if IsUpdate then
    begin
      WizardForm.FinishedHeadingLabel.Caption := 'Mise à jour de MySchoolGN terminée !';
      FinishedMsg := 'MySchoolGN a été mis à jour avec succès.' + #13#10 + #13#10 +
        'Toutes vos données ont été préservées :' + #13#10 +
        '  • Base de données intacte' + #13#10 +
        '  • Licences conservées' + #13#10 +
        '  • Photos et médias restaurés' + #13#10 + #13#10 +
        'L''application s''ouvre dans votre navigateur sur http://127.0.0.1:8000';
      WizardForm.FinishedLabel.Caption := FinishedMsg;
    end;
  end;
end;

// ── Étapes d'installation : sauvegarde avant, restauration après ─────────────
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
  begin
    if IsUpdate then
    begin
      Log('=== Mode Mise à jour détecté ===');
      // Arrêter l'application
      KillRunningApp();
      // Sauvegarder les données utilisateur
      BackupUserData();
      Log('Sauvegarde des données terminée.');
    end;
  end;

  if CurStep = ssPostInstall then
  begin
    if IsUpdate then
    begin
      Log('Restauration des données utilisateur...');
      RestoreUserData();
      Log('Restauration terminée. Mise à jour réussie.');
    end;
    if not IsUpdate then
    begin
      InstallSelectedLicense();
    end;
  end;
end;

// ── Sauvegarde de la base de données avant désinstallation ───────────────────
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DbPath:     String;
  BackupDir:  String;
  BackupPath: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    DbPath := ExpandConstant('{app}\') + CheminBaseExistante();
    if FileExists(DbPath) then
    begin
      if MsgBox(
        'Voulez-vous sauvegarder votre base de données avant la désinstallation ?' + #13#10 + #13#10 +
        'La sauvegarde sera placée dans :' + #13#10 +
        ExpandConstant('{userdocs}\MySchoolGN_Backup'),
        mbConfirmation, MB_YESNO
      ) = IDYES then
      begin
        BackupDir  := ExpandConstant('{userdocs}\MySchoolGN_Backup');
        ForceDirectories(BackupDir);
        BackupPath := BackupDir + '\db_backup_' +
                      GetDateTimeString('yyyymmdd_hhnnss', #0, #0) + '.sqlite3';
        CopyFile(DbPath, BackupPath, False);
        MsgBox(
          'Base de données sauvegardée dans :' + #13#10 + BackupPath,
          mbInformation, MB_OK
        );
      end;
    end;
  end;
end;

// ── Message de fin avec ID machine ───────────────────────────────────────────
function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo,
  MemoTypeInfo, MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
begin
  if IsUpdate then
  begin
    Result := '═══ MISE À JOUR ═══' + NewLine + NewLine +
              MemoDirInfo + NewLine + NewLine +
              MemoGroupInfo + NewLine + NewLine +
              MemoTasksInfo + NewLine + NewLine +
              '─────────────────────────────────────────' + NewLine +
              'DONNÉES PRÉSERVÉES' + NewLine +
              'Les données suivantes seront automatiquement préservées :' + NewLine +
              '  • Base de données (db.sqlite3)' + NewLine +
              '  • Fichiers de licence' + NewLine +
              '  • Photos et médias' + NewLine +
              '  • Sauvegardes' + NewLine +
              '  • Configuration (.secret_key, .env)' + NewLine +
              '─────────────────────────────────────────';
  end
  else
  begin
    Result := MemoDirInfo + NewLine + NewLine +
              MemoGroupInfo + NewLine + NewLine +
              MemoTasksInfo + NewLine + NewLine +
              '─────────────────────────────────────────' + NewLine +
              'ACTIVATION DE LICENCE' + NewLine +
              'Pendant l''installation, MySchoolGN demandera si vous avez' + NewLine +
              'une licence annuelle. Si oui, elle sera ajoutée immédiatement.' + NewLine +
              'Sinon, l''essai gratuit de 30 jours démarre automatiquement.' + NewLine +
              '─────────────────────────────────────────';
  end;
end;
