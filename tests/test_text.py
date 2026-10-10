import unittest

from awtrix_gpt.text import Highlighter, ascii_fold, collapse_whitespace, truncate_line


class AsciiFoldTests(unittest.TestCase):
    def test_strips_accents(self):
        self.assertEqual(ascii_fold("été à Marseille, déjà"), "ete a Marseille, deja")

    def test_maps_typographic_punctuation_instead_of_dropping_it(self):
        # French guillemets keep their inner spaces; only the glyphs change.
        self.assertEqual(ascii_fold("l’Europe – « oui »…"), "l'Europe - \" oui \"...")

    def test_ligatures(self):
        self.assertEqual(ascii_fold("cœur"), "coeur")


class TruncateLineTests(unittest.TestCase):
    def test_short_text_untouched(self):
        self.assertEqual(truncate_line("Bonjour Marseille", 70), "Bonjour Marseille")

    def test_collapses_newlines_and_double_spaces(self):
        self.assertEqual(truncate_line("un\n deux   trois", 70), "un deux trois")

    def test_cuts_on_word_boundary_within_budget(self):
        text = "Le gouvernement annonce une reforme des retraites pour 2027"
        out = truncate_line(text, 30)
        self.assertLessEqual(len(out), 30)
        self.assertTrue(out.endswith("..."))
        self.assertEqual(out, "Le gouvernement annonce...")

    def test_never_ends_on_separator(self):
        out = truncate_line("Retraites, le gouvernement recule encore une fois", 15)
        self.assertEqual(out, "Retraites...")

    def test_long_single_word_is_cut_mid_word(self):
        self.assertEqual(truncate_line("Anticonstitutionnellement", 10), "Anticon...")

    def test_zero_budget(self):
        self.assertEqual(truncate_line("abc", 0), "")

    def test_exact_width(self):
        self.assertEqual(truncate_line("1234567890", 10), "1234567890")


class HighlighterTests(unittest.TestCase):
    def setUp(self):
        self.h = Highlighter(
            words={"names": ["elisa", "martial"], "cities": ["marseille", "elisa"], "units": ["c"]},
            colors={"names": "#FFA500", "cities": "#00BFFF", "units": "#32CD32",
                    "numbers": "#FFD700", "default": "#FFFFFF"},
        )

    def test_known_words_coloured_case_insensitively(self):
        frags = self.h.fragments("Elisa va a MARSEILLE")
        by_word = {f["t"]: f["c"] for f in frags}
        self.assertEqual(by_word["Elisa"], "#FFA500")
        self.assertEqual(by_word["MARSEILLE"], "#00BFFF")
        self.assertEqual(by_word["va"], "#FFFFFF")

    def test_first_category_wins_on_duplicates(self):
        self.assertEqual(self.h.color_for("elisa"), "#FFA500")

    def test_numbers_get_the_number_colour(self):
        # "18C" stays one token (\w covers digits and letters): a token starting
        # with a digit takes the numbers colour, as in the original code.
        frags = self.h.fragments("18C et 40 km/h, 5 C")
        colors = {f["t"]: f["c"] for f in frags}
        self.assertEqual(colors["18C"], "#FFD700")
        self.assertEqual(colors["40"], "#FFD700")
        self.assertEqual(colors["5"], "#FFD700")
        self.assertEqual(colors["C"], "#32CD32")
        self.assertEqual(colors["km"], "#FFFFFF")

    def test_accents_are_folded_before_matching(self):
        frags = self.h.fragments("Élisa")
        self.assertEqual(frags, [{"t": "Elisa", "c": "#FFA500"}])

    def test_separators_are_kept_as_fragments_and_no_empty_fragments(self):
        frags = self.h.fragments("a, b")
        self.assertEqual([f["t"] for f in frags], ["a", ", ", "b"])
        self.assertTrue(all(f["t"] for f in frags))

    def test_from_config_tolerates_missing_sections(self):
        h = Highlighter.from_config({})
        self.assertEqual(h.fragments("x"), [{"t": "x", "c": "#FFFFFF"}])


class CollapseWhitespaceTests(unittest.TestCase):
    def test_collapse(self):
        self.assertEqual(collapse_whitespace("  a \n\t b  "), "a b")


if __name__ == "__main__":
    unittest.main()
