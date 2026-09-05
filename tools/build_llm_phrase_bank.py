"""
Build a richer phrase bank for synthetic events (tools/build_llm_phrase_bank.py)

Uses a small local LLM (Ollama preferred) to expand canned AUDIO transcripts,
room notes, and focus-loss window titles. The bank is sampled later by
tools/generate_metrics_dataset.py --phrase-bank ...

Metrics / looking-away labels do NOT come from the LLM — only free-text flavor
for AUDIO / ROOM / Focus Lost events.

Recommended tiny models (fit Quadro RTX 5000 16GB, or CPU):
    ollama pull qwen2.5:0.5b
    ollama pull qwen2.5:1.5b
    ollama pull tinyllama

Usage:
    # Install Ollama on the server, then:
    ollama pull qwen2.5:0.5b
    python tools/build_llm_phrase_bank.py --model qwen2.5:0.5b --per-category 200

    # Offline / no LLM: just write the built-in seed lists
    python tools/build_llm_phrase_bank.py --no-llm --out data/phrase_bank.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from tools.generate_synthetic_data import AUDIO_TRANSCRIPTS, FOCUS_TITLES, ROOM_NOTES

_OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")


def _ollama_generate(model: str, prompt: str, timeout: int = 120) -> str:
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.9, "num_predict": 256},
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{_OLLAMA_URL}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return (data.get("response") or "").strip()


def _parse_lines(text: str, limit: int) -> list[str]:
    lines = []
    for raw in text.splitlines():
        s = raw.strip()
        s = re.sub(r"^\s*[-*\d.)]+\s*", "", s).strip().strip('"').strip("'")
        if len(s) < 8 or len(s) > 160:
            continue
        if s.lower() in {"none", "n/a"}:
            continue
        lines.append(s)
        if len(lines) >= limit:
            break
    return lines


def _expand(category: str, seeds: list[str], model: str, n: int, batch: int) -> list[str]:
    out = list(dict.fromkeys(seeds))  # preserve order, unique
    prompts = {
        "audio_transcripts": (
            "You write short whispered exam-cheating or study phrases a mic might catch. "
            "Return ONLY a numbered list of short spoken lines (no quotes, no commentary)."
        ),
        "room_notes": (
            "You write short room-camera proctoring notes (second person, phone on desk, "
            "lighting change). Return ONLY a numbered list of short notes."
        ),
        "focus_titles": (
            "You write plausible Windows window titles a student might alt-tab to during an exam. "
            "Return ONLY a numbered list of short window titles."
        ),
    }
    system = prompts[category]
    while len(out) < n:
        need = min(batch, n - len(out))
        examples = "; ".join(seeds[:5])
        prompt = (
            f"{system}\nExamples: {examples}\n"
            f"Write {need} new diverse items:\n"
        )
        try:
            text = _ollama_generate(model, prompt)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            print(f"[BANK] Ollama call failed ({e}); keeping {len(out)} {category}")
            break
        added = 0
        for line in _parse_lines(text, need * 2):
            if line not in out:
                out.append(line)
                added += 1
                if len(out) >= n:
                    break
        print(f"[BANK] {category}: {len(out)}/{n} (+{added})")
        if added == 0:
            break
        time.sleep(0.05)
    return out[:n]


def main():
    ap = argparse.ArgumentParser(description="Build LLM (or seed) phrase bank for synth text")
    ap.add_argument("--model", default="qwen2.5:0.5b",
                    help="Ollama model tag (default qwen2.5:0.5b)")
    ap.add_argument("--per-category", type=int, default=200,
                    help="target phrases per category")
    ap.add_argument("--batch", type=int, default=20)
    ap.add_argument("--out", default=os.path.join(_PROJECT_ROOT, "data", "phrase_bank.json"))
    ap.add_argument("--no-llm", action="store_true",
                    help="write built-in seeds only (no Ollama)")
    args = ap.parse_args()

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)

    if args.no_llm:
        bank = {
            "audio_transcripts": list(AUDIO_TRANSCRIPTS),
            "room_notes": list(ROOM_NOTES),
            "focus_titles": list(FOCUS_TITLES),
            "model": None,
            "source": "builtin_seeds",
        }
    else:
        # Probe Ollama
        try:
            urllib.request.urlopen(f"{_OLLAMA_URL}/api/tags", timeout=5).read()
        except Exception as e:
            raise SystemExit(
                f"[BANK] Ollama not reachable at {_OLLAMA_URL} ({e}).\n"
                f"  Install: curl -fsSL https://ollama.com/install.sh | sh\n"
                f"  Then:    ollama pull {args.model}\n"
                f"  Or run:  python tools/build_llm_phrase_bank.py --no-llm"
            )

        print(f"[BANK] using Ollama model={args.model} at {_OLLAMA_URL}")
        bank = {
            "audio_transcripts": _expand(
                "audio_transcripts", AUDIO_TRANSCRIPTS, args.model,
                args.per_category, args.batch),
            "room_notes": _expand(
                "room_notes", ROOM_NOTES, args.model,
                args.per_category, args.batch),
            "focus_titles": _expand(
                "focus_titles", FOCUS_TITLES, args.model,
                args.per_category, args.batch),
            "model": args.model,
            "source": "ollama",
        }

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(bank, f, indent=2, ensure_ascii=False)
    print(f"[BANK] wrote {args.out}")
    for k in ("audio_transcripts", "room_notes", "focus_titles"):
        print(f"  {k}: {len(bank[k])}")


if __name__ == "__main__":
    main()
