import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class LicensingTests(unittest.TestCase):
    def test_repository_declares_complete_gpl_v3_or_later_terms(self):
        license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("GNU GENERAL PUBLIC LICENSE", license_text)
        self.assertIn("Version 3, 29 June 2007", license_text)
        self.assertIn("END OF TERMS AND CONDITIONS", license_text)
        self.assertIn("GPL-3.0-or-later", readme)
        self.assertIn("without any warranty", readme)

    def test_third_party_and_manufacturer_boundaries_are_documented(self):
        notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")

        for component in (
            "PyQt6", "Qt 6", "pyqtgraph", "pySerial", "PyVISA",
            "OpenCV", "NumPy", "Python", "PyInstaller",
        ):
            with self.subTest(component=component):
                self.assertIn(component, notices)
        self.assertIn("not project licensors or endorsers", notices)
        self.assertIn("No manufacturer software", notices)

    def test_build_bundles_license_documents(self):
        spec = (ROOT / "UOSLabManager.spec").read_text(encoding="utf-8")
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")

        self.assertIn("('LICENSE', '.')", spec)
        self.assertIn("('THIRD_PARTY_NOTICES.md', '.')", spec)
        self.assertIn("third_party_license_files", spec)
        self.assertIn("numpy", requirements.splitlines())

    def test_main_window_has_about_and_full_license_actions(self):
        source = (ROOT / "gui" / "main_window.py").read_text(encoding="utf-8")
        ast.parse(source)
        self.assertIn("About UOSLabManager", source)
        self.assertIn("License and third-party notices", source)
        self.assertIn("absolutely no warranty", source)


if __name__ == "__main__":
    unittest.main()
