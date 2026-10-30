import csv
import io
import os
import tempfile
import unittest

from ttne.app.display_config import store, translations
from ttne.app.display_config.translations import TranslationFileError

DEFAULT = (
    "ID,Screen,English (en),Español (es),Deutsch (de),中文 (简体) (zh-hans),العربية (ar)\n"
    "T001,Alarms,Alarms,Alarmas,Alarme,报警,الإنذارات\n"
    'T002,Outlets,Outlet %d,Salida %d,Ausgang %d,插座 %d,المخرج %d\n'
    'T003,Network,"IP: #A1C61A %s#\nMask: #A1C61A %s#",'
    '"IP: #A1C61A %s#\nMáscara: #A1C61A %s#",,,\n'
    '"T004",Update,"  Update\nFrom USB","Actualizar\ndesde USB",,,\n'
)


def rows(text):
    return list(csv.reader(io.StringIO(text.lstrip("﻿"))))


class TranslationsTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.default = os.path.join(self.directory.name, "translations.csv")
        self.custom = os.path.join(self.directory.name, "custom.csv")
        with open(self.default, "w", encoding="utf-8") as f:
            f.write(DEFAULT)

    def tearDown(self):
        self.directory.cleanup()

    def upload(self, text, encoding="utf-8"):
        result, report = translations.import_csv(text.encode(encoding), self.default)
        translations.save_custom(result, self.custom)
        return report

    def export(self):
        return rows(translations.export_csv(self.default, self.custom))

    def test_export_of_the_default_table(self):
        text = translations.export_csv(self.default, self.custom)
        self.assertTrue(text.startswith("﻿ID,Screen,English (en),Español (es)"))
        table = rows(text)
        self.assertEqual("Must keep unchanged", table[0][-1])
        self.assertEqual(["T002", "Outlets", "Outlet %d", "Salida %d"], table[2][:4])
        self.assertEqual("Placeholders: %d", table[2][-1])
        self.assertIn("Line breaks", table[4][-1])

    def test_reimporting_the_export_changes_nothing(self):
        report = self.upload(translations.export_csv(self.default, self.custom))
        self.assertEqual(0, report["changed"])
        self.assertEqual([], report["rejected"])
        self.assertFalse(os.path.exists(self.custom))

    def test_changed_text_and_new_language(self):
        table = self.export()
        table[0].insert(-1, "Français (fr)")
        for row, text in zip(table[1:], ["Alarmes", "Prise %d", "", ""]):
            row.insert(-1, text)
        table[1][3] = "Alarmas nuevas"
        out = io.StringIO()
        csv.writer(out).writerows(table)
        report = self.upload(out.getvalue())
        self.assertEqual(["fr"], report["new_languages"])
        self.assertEqual(3, report["changed"])
        self.assertEqual([], report["rejected"])

        # Stored: only the changes, plus the new language
        with open(self.custom, encoding="utf-8") as f:
            stored = rows(f.read())
        self.assertEqual(["ID", "Screen", "English (en)", "Español (es)", "Français (fr)"], stored[0])
        self.assertEqual(["T001", "Alarms", "Alarms", "Alarmas nuevas", "Alarmes"], stored[1])
        self.assertEqual(3, len(stored))

        exported = self.export()
        self.assertEqual("Français (fr)", exported[0][7])
        self.assertEqual("Alarmas nuevas", exported[1][3])
        self.assertEqual("Prise %d", exported[2][7])
        self.assertEqual("Ausgang %d", exported[2][4])
        codes = translations.language_codes(self.custom)
        self.assertEqual(["en", "es", "de", "zh-hans", "ar", "fr"], codes)

    def test_rejected_texts_are_reported(self):
        text = ("ID;English (en);Español (es);Deutsch (de);ไทย (th)\r\n"
                "T001;Alarms;Alarmas;Alarme;สัญญาณเตือน\r\n"
                "T002;Outlet %d;Salida;Ausgang %s;\r\n"
                'T003;"IP: #A1C61A %s#\r\nMask: #A1C61A %s#";"IP: %s\r\nMáscara: %s";;\r\n'
                "T009;Not a text;Nada;;\r\n"
                "T004;Update From USB;Actualizar USB;;\r\n")
        report = self.upload(text)
        reasons = {(r["id"], r["language"]): r["reason"] for r in report["rejected"]}
        self.assertEqual({
            ("T001", "th"): "unsupported_chars",
            ("T002", "es"): "placeholders",
            ("T002", "de"): "placeholders",
            ("T003", "es"): "colour_marks",
            ("T009", "en"): "unknown_text",
            ("T004", "en"): "unknown_text",   # the line break is part of the text
        }, reasons)
        self.assertEqual(["th"], report["new_languages"])
        self.assertEqual(2, report["accepted"])   # T001 es and de

    def test_whitespace_of_english_may_change(self):
        # Spreadsheets may trim the cell: still the same text
        report = self.upload("English (en),Español (es)\n"
                             '"Update\nFrom USB","Actualizar\ndesde un USB"\n')
        self.assertEqual(1, report["changed"])
        with open(self.custom, encoding="utf-8") as f:
            self.assertEqual("  Update\nFrom USB", rows(f.read())[1][2])

    def test_workbook_column_titles(self):
        report = self.upload("ID,Screen,English (reference),Spanish,German,"
                             "Chinese (Simplified),Arabic,Must keep unchanged\n"
                             "T001,Alarms,Alarms,Alarmas,Alarm,报警,الإنذارات,\n")
        self.assertEqual(1, report["changed"])
        self.assertEqual([], report["ignored_columns"])
        self.assertEqual(["es", "de", "zh-hans", "ar"], report["languages"])

    def test_placeholder_rules(self):
        problem = translations.text_problem
        self.assertIsNone(problem("Outlet %d: %.1f A", "Salida %d: %.1f A"))
        self.assertIsNone(problem("100%%", "100 %%"))
        self.assertEqual("placeholders", problem("Outlet %d", "Salida %d %n")[0])
        self.assertEqual("placeholders", problem("Outlet %d", "Salida %1$d")[0])
        self.assertEqual("placeholders", problem("%s of %d", "%d de %s")[0])
        self.assertEqual("placeholders", problem("Load", "Carga 50%")[0])
        self.assertEqual("control_chars", problem("A", "A\tB")[0])
        self.assertEqual("too_long", problem("A", "é" * 600)[0])
        self.assertEqual("unsupported_chars", problem("Yes", "ہاں")[0])   # Urdu
        self.assertIsNone(problem("Yes", "بله"))                           # Persian
        self.assertIsNone(problem("Yes", "Да"))
        self.assertIsNone(problem("Yes", "はい"))
        self.assertIsNone(problem("Yes", "כן"))

    def test_file_errors(self):
        with self.assertRaises(TranslationFileError) as ctx:
            self.upload("English,Español\nAlarms,Alarmas\n", encoding="utf-16")
        self.assertEqual("not_utf8", ctx.exception.code)
        with self.assertRaises(TranslationFileError) as ctx:
            self.upload("Text,Spanish\nAlarms,Alarmas\n")
        self.assertEqual("no_english", ctx.exception.code)
        many = ",".join(f"L{i} (x{chr(97 + i)})" for i in range(12))
        with self.assertRaises(TranslationFileError) as ctx:
            self.upload("English (en)," + many + "\nAlarms" + ",a" * 12 + "\n")
        self.assertEqual("too_many_languages", ctx.exception.code)

    def test_reset(self):
        self.upload("English (en),Italiano (it)\nAlarms,Allarmi\n")
        self.assertIn("it", translations.language_codes(self.custom))
        translations.reset(self.custom)
        self.assertFalse(os.path.exists(self.custom))
        self.assertNotIn("it", translations.language_codes(self.custom))

    def test_language_of_a_removed_column_goes_back_to_english(self):
        config_path = os.path.join(self.directory.name, ".cmdisplay.config")
        self.upload("English (en),Italiano (it)\nAlarms,Allarmi\n")
        original = translations.CUSTOM_FILE
        translations.CUSTOM_FILE = self.custom
        try:
            with open(config_path, "w") as f:
                f.write("rotation=2\nlanguage=it\n")
            store.drop_unknown_language(config_path)
            self.assertEqual("it", store.load_config(config_path).language)
            translations.reset(self.custom)
            store.drop_unknown_language(config_path)
            self.assertEqual("en", store.load_config(config_path).language)
        finally:
            translations.CUSTOM_FILE = original


if __name__ == "__main__":
    unittest.main()
