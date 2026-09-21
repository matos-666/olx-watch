"""Classifier regression suite. Run: python3 -m unittest

Most titles are real OLX listings seen live in Sep 2026; the rest are edge
cases the filter must handle before they turn up. Every past bug has a
case here — keep adding them.
"""
import unittest
from datetime import datetime, timezone

from hunt import brands_of, classify

CASES = [
    # --- real listings: standalone cabs
    ("Blackstar HTV-412A", "cab"),
    ("Coluna 4x12  Harley Benton g412a", "cab"),
    ("Coluna Harley Benton 4x12 Celestion V30 (+ Thomann Cover HB G412A", "cab"),  # "+ cover" isn't a stack
    ("Coluna Marshall 1960 Lead 4x12", "cab"),
    ("Coluna Marshall 8412 usada (8 Ohms (Ω) 4 Celestion de 12 polegadas", "cab"),
    ("Coluna Orange PPC412 Compact", "cab"),                    # model code only, no "4x12"
    ("Coluna e Case Guitarra Laney Iron Heart 4x12", "cab"),    # "Guitarra" + cab word is fine
    ("Randall RS412XJ 4x12 – Original – Bom Estado", "cab"),
    ('Vendo coluna dvmark 4x12" neoclassic', "cab"),
    ("Coluna Hughes&Kettner Attax 412 400watts + case de transporte", "cab"),  # bare 412
    # --- real listings: head + cab
    ("Marshall AVT150H Valvestate 2000 + MG412A 4x12 + Footswitch Original", "stack"),  # head by model code only
    ("Marshall Valvestate 2000 AVT150H 150-Watt + Marshall MX412A Guitar", "stack"),
    ("Fender Mustang V Head + Coluna 4x12 + Footswitch Original", "stack"),
    ("Marshall 2555x Silver Jubilee com 4x12 correspondente", "stack"),
    ("Amplificador Cabeça hiwatt leeds 50r head mais coluna Marshall 1960", "stack"),
    # --- real listings that must be dropped
    ("Guitarra 12 cordas Harley Benton Custom Line CLJ-412E SB", None),
    ("Harley Benton CLJ-412E SB", None),                        # "E" = electro-acoustic suffix
    ("Coluna Palmer 2x12 c/ speakers Eminence", None),
    ("Coluna Orange PPC212 (Vintage 30) em bom estado!", None),
    ("Coluna Marshall sc212", None),
    ('PRICE DROP! Mesa Roadster Dual Rectifier 4-Channel 120-Watt 2x12"', None),
    ("Toyota Hilux 2.4 D-4D 4X4", None),
    ("4 Alto Falantes Celestion V30 Speakers", None),
    # --- edge cases not yet seen live
    ("Compro coluna 4x12 Marshall", None),                      # buyer, not seller
    ("Procuro 4x12 em bom estado", None),
    ("Aluguer backline: cabeça + 4x12", None),                  # rental
    ("Capa para coluna 4x12", "parts"),
    ("Rodas para coluna 4x12", "parts"),
    ("Coluna 4 x 12 Peavey 5150", "cab"),
    ("Coluna 4X12 ENGL", "cab"),
    ("Coluna 4×12 Laney", "cab"),
    ("Peavey 6505 head + 4x12", "stack"),
    ("Cab 4x12 ENGL Pro", "cab"),
    ("Mesa Boogie Rectifier 4x12 Standard", "cab"),
    ("Mesa de mistura Behringer 12 canais", None),
]

BRANDS = [
    ("Amplificador Cabeça hiwatt leeds 50r head mais coluna Marshall 1960", ["Hiwatt", "Marshall"]),
    ("Coluna Hughes&Kettner Attax 412", ["Hughes & Kettner"]),
    ("Mesa Boogie Rectifier 4x12 Standard", ["Mesa Boogie"]),
    ("Mesa de mistura Behringer 12 canais", ["Behringer"]),   # "mesa" = mixing desk
    ("Coluna Marshall 1960 4x12 com Celestion", ["Marshall"]),  # speaker brand hidden when a maker is named
]


class ClassifyTest(unittest.TestCase):
    def test_cases(self):
        for title, want in CASES:
            with self.subTest(title=title):
                self.assertEqual(classify(title), want)

    def test_brands(self):
        for title, want in BRANDS:
            with self.subTest(title=title):
                self.assertEqual(brands_of(title), want)


class AlertTest(unittest.TestCase):
    def _ad(self, **kw):
        base = dict(id=1, title="Coluna Marshall 1960 4x12", kind="cab", price="150 €",
                    price_value=150, url="https://x", city="Porto", region="Porto",
                    created="2026-09-20T11:59:00+01:00", refreshed="2026-09-20T11:59:00+01:00")
        base.update(kw)
        return base

    def test_good_price_and_brand(self):
        from watcher import format_alert
        msg = format_alert(self._ad(), now=datetime(2026, 9, 21, tzinfo=timezone.utc))
        self.assertIn("BOM PREÇO", msg)
        self.assertIn("Marshall", msg)
        self.assertNotIn("reativado", msg)

    def test_reactivated(self):
        from watcher import format_alert
        msg = format_alert(self._ad(created="2026-03-29T12:14:00+01:00", price_value=900),
                           now=datetime(2026, 9, 21, tzinfo=timezone.utc))
        self.assertIn("reativado", msg)
        self.assertNotIn("BOM PREÇO", msg)

    def test_html_is_escaped(self):
        # An unescaped "<" makes Telegram reject the message; the ad would be
        # marked seen anyway and the alert silently lost.
        from watcher import format_alert
        msg = format_alert(self._ad(title="Coluna 4x12 <como nova> & barata"))
        self.assertIn("&lt;como nova&gt; &amp; barata", msg)


if __name__ == "__main__":
    unittest.main()
