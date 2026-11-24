"""What a language model is allowed to run against the database.

A model that writes SQL is an injection surface with better manners. The
question is not whether it *intends* to drop a table — it is that the text
between the model and the database is attacker-reachable the moment anyone else
can type into the box.

So the rule here is not "ask the model nicely to only SELECT". It is a list of
things that must be true before a statement is executed at all, and a read-only
connection underneath in case this file is wrong.

Three decisions worth naming:

**One statement.** `sqlite3.execute` already refuses two, but the check is here
so the failure says why instead of surfacing an opaque driver error.

**An allowlist of openers, not a denylist of verbs.** Denylists lose. New SQL
keywords appear, and a denylist cannot know about them; an allowlist of SELECT
and WITH does not care.

**A LIMIT is added if the model did not write one.** Not for safety — for the
browser. A question like "list the orders" returns 99,441 rows, and a Gradio
table will try to render all of them.
"""
from __future__ import annotations

import re

MAX_ROWS = 200

# Opening keywords that read and cannot write. WITH is included because a CTE
# is the natural way to write half of these questions; WITH ... DELETE exists
# in other dialects, so the statement is checked for write verbs as well.
ALLOWED_OPENERS = ("select", "with")

FORBIDDEN = (
    "insert", "update", "delete", "drop", "alter", "create", "replace",
    "truncate", "attach", "detach", "pragma", "vacuum", "reindex", "grant",
)


class Refused(ValueError):
    """The statement will not be run, and the message says which rule it hit."""


def _strip_comments(sql: str) -> str:
    sql = re.sub(r"--[^\n]*", " ", sql)
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    return sql


def _unquoted(sql: str) -> str:
    """Blank out string and identifier literals.

    Without this, a product category called "update" or a WHERE clause matching
    'delete' would be refused — a false positive that looks like a bug to
    everyone who hits it.
    """
    out, i, n = [], 0, len(sql)
    while i < n:
        c = sql[i]
        if c in "'\"`":
            j = i + 1
            while j < n and sql[j] != c:
                j += 1
            out.append(" " * (j - i + 1))
            i = j + 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def check(sql: str) -> str:
    """Return the statement to run, or raise Refused.

    The returned string may differ from the input: a trailing semicolon is
    dropped and a LIMIT may be appended.
    """
    if not sql or not sql.strip():
        raise Refused("empty statement")

    body = _unquoted(_strip_comments(sql)).strip().rstrip(";").strip()
    if not body:
        raise Refused("nothing left after removing comments")

    if ";" in body:
        raise Refused("one statement at a time")

    first = re.split(r"\s+", body.lower(), maxsplit=1)[0]
    if first not in ALLOWED_OPENERS:
        raise Refused(f"only SELECT and WITH are allowed, not {first.upper()}")

    words = set(re.findall(r"[a-z_]+", body.lower()))
    hit = sorted(words & set(FORBIDDEN))
    if hit:
        raise Refused(f"refused: {', '.join(w.upper() for w in hit)}")

    clean = sql.strip().rstrip(";").strip()
    if not re.search(r"\blimit\b", body.lower()):
        clean = f"{clean}\nLIMIT {MAX_ROWS}"
    return clean
