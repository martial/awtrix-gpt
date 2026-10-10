"""The rewriter must shorten real headlines and refuse invented ones."""

import unittest

from awtrix_gpt.news import Headline
from awtrix_gpt.news_rewrite import (build_news_lines_llm, grounding_failure,
                                     rewrite_headline, significant_words)

LONG = ("Manifestations contre la reforme des retraites dans plusieurs villes de France "
        "selon les syndicats")


class FakeLLM:
    """Returns canned answers and records the prompts it was given."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts = []

    def generate(self, prompt, *, timeout=60):
        self.prompts.append(prompt)
        if not self.answers:
            raise AssertionError("FakeLLM called more times than it has answers")
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


class SignificantWordsTests(unittest.TestCase):
    def test_drops_stopwords_short_words_and_accents(self):
        self.assertEqual(significant_words("Greve a Marseille avec les syndicats"),
                         {"greve", "marseille", "syndicats"})

    def test_folds_accents_so_sources_and_rewrites_compare(self):
        self.assertIn("reforme", significant_words("Réforme des retraites"))


class GroundingTests(unittest.TestCase):
    def test_accepts_a_faithful_shortening(self):
        self.assertIsNone(grounding_failure(LONG, "Manifestations contre la reforme des retraites"))

    def test_accepts_inflected_words(self):
        self.assertIsNone(grounding_failure(LONG, "Manifestation contre les reformes des retraites"))

    def test_rejects_an_invented_headline(self):
        self.assertIsNotNone(
            grounding_failure(LONG, "Etat d'urgence sanitaire decrete en Corse par le gouvernement"))

    def test_rejects_a_number_absent_from_the_source(self):
        reason = grounding_failure("Le prix du lait augmente en France",
                                   "Le prix du lait augmente de 15 pourcent en France")
        self.assertIsNotNone(reason)
        self.assertIn("15", reason)

    def test_keeps_a_number_present_in_the_source(self):
        self.assertIsNone(grounding_failure("Le prix du lait augmente de 15 pourcent en France",
                                            "Prix du lait: plus 15 pourcent"))

    def test_rejects_an_empty_or_wordless_candidate(self):
        self.assertIsNotNone(grounding_failure(LONG, "..."))


class RewriteHeadlineTests(unittest.TestCase):
    def test_short_titles_never_reach_the_model(self):
        llm = FakeLLM()
        out = rewrite_headline(llm, Headline(title="Greve a Marseille"), max_chars=32)
        self.assertEqual(out, "Greve a Marseille")
        self.assertEqual(llm.prompts, [])

    def test_uses_a_grounded_rewrite(self):
        llm = FakeLLM("Manifestations contre la reforme")
        out = rewrite_headline(llm, Headline(title=LONG), max_chars=32)
        self.assertEqual(out, "Manifestations contre la reforme")

    def test_falls_back_to_truncation_when_the_model_invents(self):
        llm = FakeLLM("Etat d'urgence sanitaire en Corse")
        out = rewrite_headline(llm, Headline(title=LONG), max_chars=32)
        self.assertNotIn("Corse", out)
        self.assertTrue(LONG.lower().startswith(out.rstrip(".").lower()[:20]))

    def test_falls_back_when_the_model_errors(self):
        llm = FakeLLM(RuntimeError("ollama down"))
        out = rewrite_headline(llm, Headline(title=LONG), max_chars=32)
        self.assertLessEqual(len(out), 32)
        self.assertTrue(out)

    def test_strips_quotes_and_extra_lines(self):
        llm = FakeLLM('"Manifestations contre la reforme"\nVoila le titre raccourci.')
        out = rewrite_headline(llm, Headline(title=LONG), max_chars=32)
        self.assertEqual(out, "Manifestations contre la reforme")

    def test_never_exceeds_max_chars(self):
        llm = FakeLLM("Manifestations contre la reforme des retraites en France selon les syndicats")
        self.assertLessEqual(len(rewrite_headline(llm, Headline(title=LONG), max_chars=32)), 32)


class BuildNewsLinesLlmTests(unittest.TestCase):
    def test_without_a_client_it_is_the_plain_behaviour(self):
        lines = build_news_lines_llm([Headline(title=LONG, source="Le Monde")], None,
                                     max_chars=40, limit=5)
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("Le Monde: "))
        self.assertLessEqual(len(lines[0]), 40)

    def test_prefix_is_accounted_for_in_the_width(self):
        llm = FakeLLM("Manifestations contre la reforme")
        lines = build_news_lines_llm([Headline(title=LONG, source="Le Monde")], llm,
                                     max_chars=40, limit=5)
        self.assertLessEqual(len(lines[0]), 40)

    def test_deduplicates_and_respects_the_limit(self):
        heads = [Headline(title="Greve generale a Marseille aujourd hui", source="Le Monde"),
                 Headline(title="Greve generale a Marseille aujourd hui", source="Le Monde"),
                 Headline(title="Le tourisme repart fort dans la region", source="Le Figaro")]
        lines = build_news_lines_llm(heads, None, max_chars=60, limit=1)
        self.assertEqual(len(lines), 1)


if __name__ == "__main__":
    unittest.main()


class StricterGroundingTests(unittest.TestCase):
    """Two gaps found while running the rewriter against real Le Monde titles."""

    SOURCE = "Au moins deux morts dans une attaque au missile contre l aeroport de Riyad"

    def test_keeps_a_spelled_number_present_in_the_source(self):
        self.assertIsNone(grounding_failure(self.SOURCE, "Riyad attaquee: deux morts"))

    def test_rejects_a_spelled_number_absent_from_the_source(self):
        reason = grounding_failure(self.SOURCE, "Riyad attaquee: dix morts")
        self.assertIsNotNone(reason)
        # Quantities are reported normalised, so "dix" surfaces as "10".
        self.assertIn("10", reason)

    def test_rejects_an_english_rewrite_of_a_french_title(self):
        source = "Le lyceen ampute d une main a Lens dement avoir ramasse la grenade"
        reason = grounding_failure(source, "Lycee Lens: Denies grenade")
        self.assertIsNotNone(reason)
        self.assertIn("denies", reason)

    def test_allows_an_english_word_that_was_already_in_the_source(self):
        self.assertIsNone(grounding_failure("Le president annonce un report du sommet",
                                            "Le president annonce un report"))


class FigureEquivalenceTests(unittest.TestCase):
    """"deux" and "2" are the same quantity; only a *changed* number is a lie."""

    SOURCE = "Au moins deux morts dans une attaque contre l aeroport de Riyad"

    def test_digit_rewrite_of_a_spelled_source_is_accepted(self):
        self.assertIsNone(grounding_failure(self.SOURCE, "Riyad: attaque, 2 morts"))

    def test_spelled_rewrite_of_a_digit_source_is_accepted(self):
        self.assertIsNone(grounding_failure("Hausse de 15 pourcent du prix du lait",
                                            "Prix du lait: hausse de quinze pourcent"))

    def test_a_different_quantity_is_still_rejected(self):
        self.assertIsNotNone(grounding_failure(self.SOURCE, "Riyad: attaque, 10 morts"))
