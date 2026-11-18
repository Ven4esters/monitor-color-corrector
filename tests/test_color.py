import unittest
from math import isclose

from spectra.backends.base import D65, Monitor, valid_ramp
from spectra.backends.edid import decode_edid
from spectra.color import PROFILES, brightness, gains, make_ramp, preview_curve, recommend


def edid():
    block = bytearray(128)
    block[:8] = b"\x00\xff\xff\xff\xff\xff\xff\x00"
    block[8:10] = (4 << 10 | 5 << 5 | 12).to_bytes(2, "big")  # DEL
    block[10:12] = (0x1234).to_bytes(2, "little")
    block[23] = 120
    points = [round(x * 1024) for x in (0.64, 0.33, 0.30, 0.60, 0.15, 0.06, *D65)]
    for i, value in enumerate(points):
        block[25 + i // 4] |= (value & 3) << (6 - 2 * (i % 4))
        block[27 + i] = value >> 2
    block[54:59] = b"\x00\x00\x00\xfc\x00"
    block[59:72] = b"DELL U2723QE\n"
    block[127] = -sum(block[:127]) % 256
    return block


class ColorTests(unittest.TestCase):
    def setUp(self):
        self.display = Monitor("test", "Test", "DP-1", 1920, 1080, 60, True)

    def test_edid_model_nominal_gamma_and_chromaticity(self):
        parsed = decode_edid(edid())
        self.assertEqual(parsed["name"], "DELL U2723QE")
        self.assertAlmostEqual(parsed["gamma"], 2.2)
        self.assertLess(abs(parsed["white"][1] - D65[1]), 1 / 1024)
        self.assertAlmostEqual(parsed["primaries"][0][0], 0.64, delta=0.001)

    def test_missing_model_uses_vendor_product_not_made_up_name(self):
        block = edid()
        block[57] = 0xFF
        block[-1] = -sum(block[:-1]) % 256
        self.assertEqual(decode_edid(block)["name"], "DEL 1234")

    def test_invalid_edid_uses_reference_defaults(self):
        damaged = edid()
        damaged[1] = 0
        for raw in (b"", b"bad", bytes(damaged), bytes(128)):
            self.assertEqual(decode_edid(raw)["white"], D65)
            self.assertEqual(decode_edid(raw)["name"], "")

    def test_neutral_full_brightness_is_identity(self):
        ramp = make_ramp(self.display, "standard", 100, 256)
        self.assertEqual(ramp, [[n * 257 for n in range(256)]] * 3)

    def test_all_presets_monotone_bounded_and_different(self):
        for profile in PROFILES:
            for amount in (0, 1, 21, 70, 100):
                ramp = make_ramp(self.display, profile, amount, 1024)
                self.assertTrue(valid_ramp(ramp))
                self.assertEqual(brightness(ramp), amount)
                self.assertGreater(max(c[-1] for c in ramp), 0)  # safe minimum
                self.assertTrue(all(c == sorted(c) for c in ramp))
        warm = make_ramp(self.display, "warm", 80, 256)
        self.assertGreater(warm[0][-1], warm[2][-1])
        self.assertLess(
            make_ramp(self.display, "cinema", 80, 256)[1][128],
            make_ramp(self.display, "standard", 80, 256)[1][128],
        )

    def test_correction_depends_on_actual_native_white(self):
        cool = Monitor("2", "Cool", "DP-2", 1920, 1080, 60, False, 2.0, (0.281, 0.294))
        self.assertLess(gains(cool, D65)[2], gains(cool, D65)[0])
        self.assertNotEqual(
            make_ramp(cool, "standard", 70, 256), make_ramp(self.display, "standard", 70, 256)
        )
        preview = preview_curve(cool, make_ramp(cool, "standard", 70, 256))
        self.assertTrue(all(isclose(c[-1], 1.0, abs_tol=0.001) for c in preview))

    def test_recommendation_uses_selected_values(self):
        self.assertEqual(recommend([46, 94], "standard"), 70)
        self.assertNotEqual(recommend([46], "warm"), recommend([94], "warm"))
        self.assertLess(recommend([70], "cinema"), recommend([70], "standard"))

    def test_malformed_ramp_is_rejected(self):
        for bad in (
            None,
            [],
            [[], [], []],
            [[0], [0], [0]],
            [[0, 65536]] * 3,
            [[0, 3], [0, 1, 4], [0, 2]],
        ):
            self.assertFalse(valid_ramp(bad))
