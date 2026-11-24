"""Question in, SQL out — and the SQL is shown to the person who asked.

That last part is the whole design. A system that answers "the average delivery
time in Pará is 23.32 days" asks to be believed. One that shows the query
alongside it can be checked by anyone who reads SQL, and argued with by anyone
who knows the data. The query is the citation.

Two providers, chosen by whichever key is in the environment, plus a mode that
works with no key at all so the repository can be run by someone who just
cloned it. The no-key mode is not an LLM — it matches a handful of example
questions to queries written by hand, and it says so in the interface rather
than pretending.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request

MODEL_ANTHROPIC = "claude-sonnet-5-5"
MODEL_GEMINI = "gemini-2.5-flash"

PROMPT = """You translate a question about a Brazilian marketplace dataset into \
exactly one SQLite query.

Rules:
- Return only the SQL. No explanation, no markdown fence, no trailing prose.
- One statement. SELECT or WITH only.
- Use only the tables and columns in the schema below.
- Prefer explicit JOINs over subqueries where both work.
- When the question implies a ranking, ORDER BY and LIMIT it.
- Dates are stored as text in 'YYYY-MM-DD HH:MM:SS' form; use julianday() for \
differences in days.

Schema:
{schema}

Question: {question}"""

# Hand-written answers for the no-key mode. Each one also serves as a worked
# example in the interface, which is the more useful half of its job.
EXAMPLES = {
    "how many orders are there": (
        "How many orders are in the dataset?",
        "SELECT COUNT(*) AS orders FROM orders"),
    "orders per state": (
        "How many orders came from each state?",
        "SELECT s.state AS state, COUNT(*) AS orders\n"
        "FROM orders o\n"
        "JOIN customers c ON c.customer_id = o.customer_id\n"
        "JOIN geo g ON g.zip_code_prefix = c.customer_zip_code_prefix\n"
        "JOIN states s ON s.short = g.state\n"
        "GROUP BY s.state ORDER BY orders DESC"),
    "slowest delivery by state": (
        "Which states wait longest for delivery?",
        "SELECT s.state AS state,\n"
        "       ROUND(AVG(julianday(o.order_delivered_customer_date)\n"
        "                 - julianday(o.order_purchase_timestamp)), 2) AS avg_days,\n"
        "       COUNT(*) AS delivered\n"
        "FROM orders o\n"
        "JOIN customers c ON c.customer_id = o.customer_id\n"
        "JOIN geo g ON g.zip_code_prefix = c.customer_zip_code_prefix\n"
        "JOIN states s ON s.short = g.state\n"
        "WHERE o.order_delivered_customer_date IS NOT NULL\n"
        "GROUP BY s.state HAVING delivered >= 100\n"
        "ORDER BY avg_days DESC"),
    "best rated categories": (
        "Which product categories get the best reviews?",
        "SELECT t.product_category_name_english AS category,\n"
        "       ROUND(AVG(r.review_score), 3) AS avg_score, COUNT(*) AS reviews\n"
        "FROM order_reviews r\n"
        "JOIN order_items i ON i.order_id = r.order_id\n"
        "JOIN products p ON p.product_id = i.product_id\n"
        "JOIN product_category_name_translation t\n"
        "  ON t.product_category_name = p.product_category_name\n"
        "GROUP BY category HAVING reviews >= 500\n"
        "ORDER BY avg_score DESC"),
    "revenue by month": (
        "What does revenue look like month by month?",
        "SELECT substr(o.order_purchase_timestamp, 1, 7) AS month,\n"
        "       ROUND(SUM(i.price), 2) AS revenue, COUNT(DISTINCT o.order_id) AS orders\n"
        "FROM orders o JOIN order_items i ON i.order_id = o.order_id\n"
        "GROUP BY month ORDER BY month"),
}


def provider() -> str:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("GOOGLE_API_KEY"):
        return "gemini"
    return "examples"


def _clean(text: str) -> str:
    """Strip the fence a model adds however firmly it was asked not to."""
    t = text.strip()
    m = re.search(r"```(?:sql)?\s*(.+?)```", t, flags=re.S | re.I)
    if m:
        t = m.group(1)
    return t.strip()


def _post(url: str, payload: dict, headers: dict) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def _anthropic(prompt: str) -> str:
    base = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/")
    out = _post(f"{base}/v1/messages",
                {"model": MODEL_ANTHROPIC, "max_tokens": 1000,
                 "messages": [{"role": "user", "content": prompt}]},
                {"x-api-key": os.environ["ANTHROPIC_API_KEY"],
                 "anthropic-version": "2023-06-01"})
    return "".join(b.get("text", "") for b in out.get("content", []))


def _gemini(prompt: str) -> str:
    key = os.environ["GOOGLE_API_KEY"]
    out = _post(
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{MODEL_GEMINI}:generateContent?key={key}",
        {"contents": [{"parts": [{"text": prompt}]}]}, {})
    return out["candidates"][0]["content"]["parts"][0]["text"]


def _normalise(text: str) -> str:
    return " ".join(re.findall(r"[a-z]+", text.lower()))


def _example_for(question: str):
    """Exact match on the question, not a fuzzy one.

    A first attempt scored word overlap and promptly answered "how many orders
    came from each state?" with the row count, because both sentences contain
    "how many orders". In a system whose whole claim is that you can check the
    query, a matcher that quietly returns the wrong one is worse than a refusal
    — and the interface fills the box with the exact text anyway, so there is
    nothing to be fuzzy about.
    """
    want = _normalise(question)
    for q, sql in EXAMPLES.values():
        if _normalise(q) == want:
            return sql
    return None


def to_sql(question: str, schema: str) -> tuple[str, str]:
    """Return (sql, how_it_was_produced)."""
    p = provider()
    if p == "anthropic":
        return _clean(_anthropic(PROMPT.format(schema=schema, question=question))), \
            f"{MODEL_ANTHROPIC}"
    if p == "gemini":
        return _clean(_gemini(PROMPT.format(schema=schema, question=question))), \
            f"{MODEL_GEMINI}"

    sql = _example_for(question)
    if sql is None:
        raise RuntimeError(
            "No API key is set, so only the five example questions below work, "
            "word for word. Set ANTHROPIC_API_KEY or GOOGLE_API_KEY to ask "
            "anything else.")
    return sql, "no model — this is the hand-written query for that example"
