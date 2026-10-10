import io
import unittest
from datetime import datetime

from PIL import Image

from awtrix_gpt.printing import add_text_to_image, format_french_timestamp, wrap_and_reverse_text, wrap_text


class WrapTests(unittest.TestCase):
    def test_wrap_text_respects_width(self):
        lines = wrap_text("Le soleil tape sur Marseille cachez vous ou sortez le pastis", 20)
        self.assertTrue(all(len(l) <= 20 for l in lines))
        self.assertEqual(" ".join(lines), "Le soleil tape sur Marseille cachez vous ou sortez le pastis")

    def test_paragraphs_and_reverse(self):
        self.assertEqual(wrap_and_reverse_text("un deux\ntrois", 32), "trois\nun deux")

    def test_long_word_stands_alone(self):
        self.assertEqual(wrap_text("a Anticonstitutionnellement b", 10), ["a", "Anticonstitutionnellement", "b"])

    def test_empty(self):
        self.assertEqual(wrap_and_reverse_text(""), "")


class TimestampTests(unittest.TestCase):
    def test_french_and_locale_independent(self):
        self.assertEqual(format_french_timestamp(datetime(2026, 10, 10, 14, 5)), "samedi 10 octobre 2026 à 14:05")
        self.assertEqual(format_french_timestamp(datetime(2026, 2, 2, 9, 0)), "lundi 02 février 2026 à 09:00")


class ImageTests(unittest.TestCase):
    def test_caption_added_below_rotated_image(self):
        buf = io.BytesIO()
        Image.new("RGB", (200, 100), "blue").save(buf, format="JPEG")
        out = Image.open(io.BytesIO(add_text_to_image(buf.getvalue(), "ligne 1\nligne 2")))
        self.assertEqual(out.width, 200)
        self.assertGreater(out.height, 100 + 2 * 40)


if __name__ == "__main__":
    unittest.main()
