# Ask Magist — a question in, the query out, the answer beside it

A Gradio interface over 99,441 Brazilian marketplace orders. You ask in
English, a language model writes the SQL, and **the SQL is shown next to the
result**.

That last part is the design, not a debugging aid. A system that answers
*"Amazonas waits 26.43 days for delivery"* is asking to be believed. One that
shows

```sql
SELECT s.state, ROUND(AVG(julianday(o.order_delivered_customer_date)
                        - julianday(o.order_purchase_timestamp)), 2) AS avg_days,
       COUNT(*) AS delivered
FROM orders o
JOIN customers c ON c.customer_id = o.customer_id
JOIN geo g ON g.zip_code_prefix = c.customer_zip_code_prefix
JOIN states s ON s.short = g.state
WHERE o.order_delivered_customer_date IS NOT NULL
GROUP BY s.state HAVING delivered >= 100
ORDER BY avg_days DESC
```

can be checked by anyone who reads SQL and argued with by anyone who knows the
data — starting with that `HAVING delivered >= 100`, which is a judgement call
somebody made and which changes the answer.

**The query is the citation.**

---

## Letting a model write SQL against your database

It is an injection surface with better manners. The question is not whether the
model *intends* to drop a table — it is that the text between the model and the
database is reachable by whoever can type in the box.

So the rule is not "ask the model nicely". Four things must hold before a
statement runs:

| | |
|---|---|
| **Allowlist, not denylist** | Only `SELECT` and `WITH` may open a statement. Denylists lose: new keywords appear and a denylist cannot know about them |
| **Write verbs anywhere are refused** | The opener is not enough — `WITH x AS (SELECT 1) DELETE FROM orders` opens with `WITH` |
| **One statement** | `sqlite3` already refuses two, but the check is here so the error says why |
| **Read-only connection underneath** | `file:…?mode=ro`. If the guard has a hole, the driver still says no |

Two details that took a second pass. Write verbs **inside strings and comments**
do not count — a product category named `update` must not take the feature
down. And `ATTACH` is refused explicitly, because it would let a read-only
connection write to a *different* file.

A `LIMIT 200` is appended when the model did not write one. That is not safety,
it is the browser: "list the orders" returns 99,441 rows and the table will try
to render all of them.

## Running it

```bash
pip install -r requirements.txt
export MAGIST_DB=/path/to/magist.db      # built by eniac-magist-analysis
export ANTHROPIC_API_KEY=...             # or GOOGLE_API_KEY, or neither
python3 app.py                           # http://127.0.0.1:7860
```

**Without a key it still runs**, on five example questions answered by
hand-written SQL, and the interface says so rather than implying a model is
involved. The five are enough to show what the thing does.

The database is the 115 MB SQLite file built by
[eniac-magist-analysis](https://github.com/adminleo/eniac-magist-analysis) and
is not redistributed here.

```
magist_ask/  guard.py  what may reach the database, and why
             db.py     read-only connection, and the schema the model sees
             llm.py    question → SQL, two providers and a no-key mode
app.py       the interface
tests/       the guard, pinned — 14 tests, no key needed
```

## Two things worth saying about the prompt

**The schema includes row counts.** Without them a model will cheerfully
propose a join returning eleven million rows, because nothing told it that
`order_items` has 112,650 and `products` has 32,951.

**The no-key matcher is exact, not fuzzy.** The first version scored word
overlap and promptly answered *"how many orders came from each state?"* with
the total row count, because both sentences contain "how many orders". In a
system whose entire claim is that you can check the query, a matcher that
quietly returns the wrong one is worse than a refusal.

## What it does not do

It does not check whether the answer is *right* — only that the query is
visible. A model can write SQL that runs, returns rows, and answers a different
question than the one asked; the join above could have used
`order_estimated_delivery_date` and nothing here would object.

Testing that is a [separate problem](https://github.com/adminleo/grounded-ai-evals),
and a harder one.
