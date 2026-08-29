"""Tests de securite du build et de migration des donnees Windows."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import build_exe
from offline_data import MIGRATION_MARKER, migrate_legacy_data_layout


class LegacyDataMigrationTests(TestCase):
    def test_internal_data_is_migrated_once_without_deletion(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            internal = root / "_internal"
            (internal / "media" / "eleves" / "photos").mkdir(parents=True)
            (internal / "logs").mkdir(parents=True)

            legacy_db = internal / "db.sqlite3"
            legacy_db.write_bytes(b"legacy-database")
            legacy_photo = internal / "media" / "eleves" / "photos" / "photo.jpg"
            legacy_photo.write_bytes(b"legacy-photo")
            (internal / "logs" / "django.log").write_text("ancien log", encoding="utf-8")

            actions = migrate_legacy_data_layout(root)

            self.assertTrue(actions)
            self.assertEqual((root / "db.sqlite3").read_bytes(), b"legacy-database")
            self.assertEqual(
                (root / "media" / "eleves" / "photos" / "photo.jpg").read_bytes(),
                b"legacy-photo",
            )
            self.assertTrue((root / "logs" / "django.log").is_file())
            self.assertTrue((root / MIGRATION_MARKER).is_file())
            self.assertTrue(legacy_db.is_file(), "la sauvegarde legacy doit être conservée")

            # Le marqueur empêche une ancienne copie de remplacer des données
            # plus récentes lors des démarrages suivants.
            (root / "db.sqlite3").write_bytes(b"current-database")
            legacy_db.write_bytes(b"obsolete-database")
            self.assertEqual(migrate_legacy_data_layout(root), [])
            self.assertEqual((root / "db.sqlite3").read_bytes(), b"current-database")


class BuildDataSafetyTests(TestCase):
    def test_build_contains_only_allowlisted_default_media(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            output = root / "dist" / "MySchoolGN"
            internal = output / "_internal"

            for relative, content in (
                ("media/eleves/default/avatar.jpg", b"avatar"),
                ("media/ecoles/default/logo.png", b"logo"),
                ("media/eleves/photos/private.jpg", b"private"),
            ):
                path = source / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)

            (source / "templates").mkdir(parents=True)
            (source / "static").mkdir(parents=True)
            (output / "media" / "eleves" / "photos").mkdir(parents=True)
            (output / "media" / "eleves" / "photos" / "private.jpg").write_bytes(b"private")
            (internal / "media" / "eleves" / "photos").mkdir(parents=True)
            (internal / "media" / "eleves" / "photos" / "private.jpg").write_bytes(b"private")

            sensitive_names = [
                "db.sqlite3",
                ".env",
                ".secret_key",
                ".trial_start",
                "license.dat",
                "license_ecole.lic",
            ]
            for location in (output, internal):
                location.mkdir(parents=True, exist_ok=True)
                for name in sensitive_names:
                    (location / name).write_text("secret", encoding="utf-8")

            with patch.object(build_exe, "BASE_DIR", str(source)), patch.object(
                build_exe, "OUTPUT_DIR", str(output)
            ):
                build_exe.copy_extra_files()

            media_files = {
                path.relative_to(output).as_posix()
                for path in output.rglob("*")
                if path.is_file() and "media" in path.parts
            }
            self.assertEqual(
                media_files,
                {
                    "media/eleves/default/avatar.jpg",
                    "media/ecoles/default/logo.png",
                },
            )

            for location in (output, internal):
                for name in sensitive_names:
                    self.assertFalse((location / name).exists(), f"fuite détectée: {name}")

    def test_spec_never_collects_env_or_complete_media_directory(self):
        project_root = Path(__file__).resolve().parent.parent
        spec = (project_root / "myschool.spec").read_text(encoding="utf-8-sig")
        installer = (project_root / "installer_myschool.iss").read_text(
            encoding="utf-8-sig"
        )

        self.assertNotIn("_add_if_exists('.env'", spec)
        self.assertNotIn("_add_if_exists('media'", spec)
        self.assertIn("media\\*,_internal\\media\\*", installer)
        self.assertIn("media\\eleves\\default\\avatar.jpg", installer)
        self.assertIn("media\\ecoles\\default\\logo.png", installer)
