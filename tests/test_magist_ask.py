"""The guard, pinned — the part that must not be wrong."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from magist_ask import guard, llm  # noqa: E402


class TestWhatReachesTheDatabase(unittest.TestCase):
    def test_a_plain_select_is_allowed(self):
        self.assertIn("SELECT", guard.check("SELECT 1"))

    def test_a_cte_is_allowed(self):
        """Half the interesting questions are natural to write as a CTE."""
        out = guard.check("WITH t AS (SELECT 1 AS a) SELECT a FROM t")
        self.assertIn("WITH", out)

    def test_writes_are_refused_by_opener(self):
        for sql in ("DELETE FROM orders", "DROP TABLE orders",
                    "UPDATE orders SET x = 1", "INSERT INTO orders VALUES (1)"):
            with self.assertRaises(guard.Refused):
                guard.check(sql)

    def test_a_write_hidden_after_a_select_is_refused(self):
        """The opener is not enough on its own."""
        with self.assertRaises(guard.Refused):
            guard.check("SELECT 1; DROP TABLE orders")
        with self.assertRaises(guard.Refused):
            guard.check("WITH x AS (SELECT 1) DELETE FROM orders")

    def test_pragma_and_attach_are_refused(self):
        """ATTACH would let a read-only connection write to a second file."""
        for sql in ("PRAGMA table_info(orders)",
                    "ATTACH DATABASE '/tmp/x.db' AS x"):
            with self.assertRaises(guard.Refused):
                guard.check(sql)

    def test_a_write_verb_inside_a_comment_does_not_trip_it(self):
        out = guard.check("SELECT 1 -- DROP TABLE orders")
        self.assertIn("SELECT", out)

    def test_a_write_verb_inside_a_string_does_not_trip_it(self):
        """A category called 'update' must not take the feature down."""
        out = guard.check("SELECT * FROM products WHERE name = 'update'")
        self.assertIn("SELECT", out)

    def test_empty_input_is_refused_with_a_reason(self):
        for sql in ("", "   ", "-- nothing here"):
            with self.assertRaises(guard.Refused):
                guard.check(sql)


class TestRowCap(unittest.TestCase):
    def test_a_limit_is_added_when_missing(self):
        """Not for safety — a Gradio table will try to render 99,441 rows."""
        self.assertIn(f"LIMIT {guard.MAX_ROWS}", guard.check("SELECT * FROM orders"))

    def test_an_existing_limit_is_left_alone(self):
        out = guard.check("SELECT * FROM orders LIMIT 5")
        self.assertEqual(out.lower().count("limit"), 1)

    def test_a_trailing_semicolon_is_dropped(self):
        self.assertNotIn(";", guard.check("SELECT 1;"))


class TestNoKeyMode(unittest.TestCase):
    def test_every_example_query_survives_the_guard(self):
        """The examples are the demo. They must not be refused by our own rule."""
        for question, sql in llm.EXAMPLES.values():
            with self.subTest(question=question):
                self.assertIn("SELECT", guard.check(sql).upper())

    def test_an_unmatched_question_says_why_rather_than_guessing(self):
        if llm.provider() != "examples":
            self.skipTest("an API key is set, so the model answers instead")
        with self.assertRaises(RuntimeError) as e:
            llm.to_sql("what is the airspeed velocity of an unladen swallow", "")
        self.assertIn("API key", str(e.exception))


class TestFenceStripping(unittest.TestCase):
    def test_a_markdown_fence_is_removed(self):
        """Models add one however firmly they were asked not to."""
        self.assertEqual(llm._clean("```sql\nSELECT 1\n```"), "SELECT 1")
        self.assertEqual(llm._clean("SELECT 1"), "SELECT 1")


if __name__ == "__main__":
    unittest.main()
