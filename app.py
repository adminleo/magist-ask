"""The interface: a question, the SQL it produced, and the rows.

    python3 app.py                 # http://127.0.0.1:7860
    MAGIST_DB=/path/to/magist.db python3 app.py

Set ANTHROPIC_API_KEY or GOOGLE_API_KEY to ask anything. Without a key the app
still runs, on five hand-written example questions, and says so.
"""
from __future__ import annotations

import argparse

import gradio as gr
import pandas as pd

from magist_ask import db, guard, llm

PARSER = argparse.ArgumentParser()
PARSER.add_argument("--db", default=None, help="path to magist.db")
ARGS, _ = PARSER.parse_known_args()

CON = db.connect(ARGS.db)
SCHEMA = db.schema(CON)
PROVIDER = llm.provider()
BANNER = {
    "anthropic": f"Queries written by **{llm.MODEL_ANTHROPIC}**.",
    "gemini": f"Queries written by **{llm.MODEL_GEMINI}**.",
    "examples": ("**No API key set** — only the five example questions below "
                 "work, and they are answered by hand-written SQL, not a model. "
                 "Set `ANTHROPIC_API_KEY` or `GOOGLE_API_KEY` for the rest."),
}[PROVIDER]


def ask(question: str):
    if not question or not question.strip():
        return "", "Ask something.", None
    try:
        sql, how = llm.to_sql(question, SCHEMA)
    except Exception as e:                      # noqa: BLE001 — shown, not swallowed
        return "", f"**Could not produce a query.** {e}", None

    try:
        safe = guard.check(sql)
    except guard.Refused as e:
        return sql, f"**Refused before running.** {e}", None

    try:
        frame = db.run(CON, safe)
    except Exception as e:                      # noqa: BLE001
        return safe, f"**The query did not run.** {e}", None

    note = f"{len(frame):,} rows · {how}"
    if len(frame) == guard.MAX_ROWS:
        note += f" · capped at {guard.MAX_ROWS}"
    return safe, note, frame


with gr.Blocks(title="Ask Magist") as demo:
    gr.Markdown(
        "# Ask 99,441 orders a question\n\n"
        "Brazilian marketplace data — orders, items, payments, reviews, "
        "customers, sellers, products. A question goes in, **the query comes "
        "out alongside the answer**, and you can check it.\n\n"
        "That is the point of the thing. A number on its own asks to be "
        "believed; a number with the query that produced it can be argued "
        "with.\n\n" + BANNER
    )
    q = gr.Textbox(label="Question", placeholder="Which states wait longest for delivery?")
    go = gr.Button("Ask", variant="primary")
    sql_out = gr.Code(label="The query it ran", language="sql")
    note = gr.Markdown()
    table = gr.Dataframe(label="Result", wrap=True)
    go.click(ask, inputs=q, outputs=[sql_out, note, table])
    q.submit(ask, inputs=q, outputs=[sql_out, note, table])
    gr.Examples([[v[0]] for v in llm.EXAMPLES.values()], inputs=q)
    gr.Markdown(
        "---\n*Only SELECT and WITH reach the database, on a read-only "
        "connection, one statement at a time, capped at "
        f"{guard.MAX_ROWS} rows. The model never gets a writable handle.*"
    )

if __name__ == "__main__":
    demo.launch()
