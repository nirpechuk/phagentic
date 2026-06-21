#!/usr/bin/env python3
"""ASK PHAGE — a read-only conversational assistant for the Blue Bottle reaction.

A thin backend that holds the Anthropic API key (so it never ships to the browser) and
streams Claude's replies to the web UI's "ASK PHAGE" panel. The browser sends the user's
question, the recent chat history, and a snapshot of the live reaction state (it already
computes amplitude/period/phase/etc.); this server adds the chemistry briefing + guardrails
and relays the model's text back token-by-token.

By design the assistant has NO tools and NO actuation path — it can only produce text, so it
can describe the reaction but cannot control the stirrer, pumps, or anything else. The
read-only guarantee is structural (no write tool exists), not just a prompt instruction.

Run:  ANTHROPIC_API_KEY=sk-... hub/.venv/bin/python hub/chat_server.py   (or `make chat`)
"""
import json
import os
import sys
from pathlib import Path

from flask import Flask, Response, request

try:
    import anthropic
except ImportError:
    sys.exit("anthropic SDK not installed. Run 'make setup' (or pip install anthropic).")

HTTP_PORT = int(os.environ.get("PHAGENTIC_CHAT_PORT", "8090"))
# Haiku 4.5: fastest/cheapest, ample for a live demo chat. Swap to claude-sonnet-4-6 for
# richer reasoning by setting PHAGENTIC_CHAT_MODEL.
MODEL = os.environ.get("PHAGENTIC_CHAT_MODEL", "claude-haiku-4-5")
MAX_TOKENS = 1024
HISTORY_TURNS = 8   # how many prior chat messages to send for context

app = Flask(__name__)

# ── System prompt ───────────────────────────────────────────────────────────────
# The experiment write-up is the source of truth for the chemistry; fold it in so the
# assistant's knowledge stays in sync with the actual run. Stable across requests, so it's
# prompt-cached — only the per-turn live state (sent in the user message) varies.

_EXPERIMENT = ""
_exp_path = Path(__file__).resolve().parent.parent / "experiment.md"
try:
    _EXPERIMENT = _exp_path.read_text()
except OSError:
    pass

SYSTEM_PROMPT = f"""You are PHAGE, the on-screen assistant for a live demonstration of the \
Blue Bottle oscillating reaction, controlled by the PHAGENTIC system. A person is watching \
the reaction run and can talk to you about what's happening.

Your job is to answer questions about THIS reaction — the chemistry, the live sensor \
readings, the oscillation behaviour, and the experiment setup. You are an informative \
companion to the demo.

Hard rules:
1. You are READ-ONLY. You cannot and must not control the reaction — you have no ability to \
move the stirrer, fire the pumps, change the light, or actuate anything. If someone asks you \
to change or control the reaction, briefly explain that you only provide information, and (if \
helpful) point them to the manual controls in the console. Never claim to have taken an action.
2. Stay on topic. Only answer questions related to this reaction, its chemistry, the live \
data, or the experiment. If asked about something unrelated, politely decline and steer back \
to the reaction.
3. Be brief. This is a live chat during a demo. Default to 1–2 short sentences and lead with \
the answer — no preamble, no restating the question, no "great question". Only go longer if \
the user explicitly asks you to elaborate. You may use light Markdown (bold, inline code, the \
occasional short bullet list) where it genuinely aids clarity, but keep it minimal — the chat \
panel is small, so avoid headers, deep nesting, and tables.
4. Use the live reaction state provided with each question to ground your answer in what's \
actually happening right now. If a value looks like it's at rest/zero, the run may not be \
active yet — say so rather than inventing readings.

Reference — the experiment you are observing:
{_EXPERIMENT}"""


# ── Live-state formatting ─────────────────────────────────────────────────────────

def _format_state(state: dict) -> str:
    """Render the browser's live-state snapshot into a compact, labelled block the model can
    read. Unknown/missing fields are simply skipped."""
    if not state:
        return "(no live reaction state available)"
    fields = [
        ("source", "data source"),
        ("running", "run active"),
        ("t", "elapsed (s)"),
        ("phase", "current phase"),
        ("blue", "blue intensity (0-1)"),
        ("amp", "oscillation amplitude (0-1)"),
        ("halfPeriod", "half-period (s)"),
        ("period", "period (s)"),
        ("cycles", "cycles completed"),
        ("stallRisk", "stall risk (0-1)"),
        ("stirrerPct", "stirrer (%)"),
        ("glucosePulses", "glucose pulses fired"),
        ("lux", "sensor clear/lux"),
        ("rgb", "sensor RGB 0-255"),
        ("mode", "control mode"),
    ]
    lines = []
    for key, label in fields:
        if key in state and state[key] is not None:
            lines.append(f"- {label}: {state[key]}")
    return "\n".join(lines) if lines else "(no live reaction state available)"


def _build_messages(question: str, history: list, state: dict) -> list:
    """Prior chat turns + the new question (with the live state prepended to it)."""
    messages = []
    for m in (history or [])[-HISTORY_TURNS:]:
        role = m.get("role")
        text = (m.get("text") or "").strip()
        if not text:
            continue
        # The UI labels assistant messages "sys"; map everything non-user to assistant.
        messages.append({"role": "user" if role == "user" else "assistant", "content": text})
    # The conversation must start with a user turn — drop the UI's opening assistant greeting
    # (and any other leading assistant messages).
    while messages and messages[0]["role"] == "assistant":
        messages.pop(0)
    user_turn = f"Live reaction state right now:\n{_format_state(state)}\n\nQuestion: {question}"
    messages.append({"role": "user", "content": user_turn})
    return messages


# ── CORS (the UI is usually served from a different origin, e.g. :5173) ──────────────

def _cors(resp: Response) -> Response:
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


@app.route("/chat", methods=["POST", "OPTIONS"])
def chat():
    if request.method == "OPTIONS":
        return _cors(Response(status=204))

    if not os.environ.get("ANTHROPIC_API_KEY"):
        return _cors(Response(
            json.dumps({"error": "ANTHROPIC_API_KEY is not set on the chat server."}) + "\n",
            mimetype="application/x-ndjson", status=200,
        ))

    data = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip()
    if not question:
        return _cors(Response(json.dumps({"error": "empty question"}) + "\n",
                              mimetype="application/x-ndjson"))
    messages = _build_messages(question, data.get("history"), data.get("state"))

    def generate():
        client = anthropic.Anthropic()
        try:
            # Haiku doesn't take the effort/adaptive-thinking params, so this is a plain
            # streamed completion. The system prompt is cached across turns.
            with client.messages.stream(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=[{"type": "text", "text": SYSTEM_PROMPT,
                         "cache_control": {"type": "ephemeral"}}],
                messages=messages,
            ) as stream:
                for text in stream.text_stream:
                    yield json.dumps({"delta": text}) + "\n"
            yield json.dumps({"done": True}) + "\n"
        except anthropic.APIError as e:
            yield json.dumps({"error": getattr(e, "message", str(e))}) + "\n"
        except Exception as e:  # noqa: BLE001 — surface anything else to the UI
            yield json.dumps({"error": str(e)}) + "\n"

    return _cors(Response(generate(), mimetype="application/x-ndjson"))


@app.route("/health")
def health():
    return _cors(Response(
        json.dumps({"ok": True, "model": MODEL, "has_key": bool(os.environ.get("ANTHROPIC_API_KEY"))}) + "\n",
        mimetype="application/json",
    ))


def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("⚠  ANTHROPIC_API_KEY is not set — the chat server will report an error to the UI.")
        print("   Run with:  ANTHROPIC_API_KEY=sk-... make chat\n")
    print(f"ASK PHAGE chat server → http://localhost:{HTTP_PORT}/chat   (model: {MODEL})")
    app.run(host="0.0.0.0", port=HTTP_PORT, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
