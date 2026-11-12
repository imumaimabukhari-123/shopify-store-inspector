"""Calls to Google Gemini (free tier): embeddings for search, and chat for answers."""
import json
import math
import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
RETRY_STATUS = (429, 500, 502, 503, 504)  # Gemini busy / overloaded - worth retrying
BASE = "https://generativelanguage.googleapis.com/v1beta"
CHAT_MODEL = "gemini-flash-lite-latest"
EMBED_MODEL = "gemini-embedding-001"
DIMENSIONS = 768


class AIError(Exception):
    pass


def _post(url: str, payload: dict, timeout: int = 45) -> dict:
    """POST to Gemini, waiting and retrying when it is busy (429) or overloaded (5xx)."""
    if not API_KEY:
        raise AIError("GEMINI_API_KEY is missing. Add it to the .env file.")
    # The OpenAI-compatible chat endpoint wants a Bearer token; the native endpoints want x-goog-api-key.
    auth = {"Authorization": f"Bearer {API_KEY}"} if "/openai/" in url else {"x-goog-api-key": API_KEY}
    # Free Gemini tiers are sometimes busy (429) or overloaded (500/502/503/504): wait and try again,
    # within a time budget that stays under the 60 s Vercel limit.
    deadline = time.monotonic() + 50
    for wait in (2, 5, 10, 0):
        try:
            resp = requests.post(url, json=payload, headers={**auth, "Content-Type": "application/json"}, timeout=max(5, min(timeout, deadline - time.monotonic())))
        except requests.RequestException:
            if wait and time.monotonic() + wait < deadline:
                time.sleep(wait)
                continue
            raise AIError("Couldn't reach the AI service. Please try again.")
        if resp.status_code in RETRY_STATUS and wait and time.monotonic() + wait < deadline:
            time.sleep(wait)
            continue
        if resp.status_code in RETRY_STATUS:
            raise AIError("The AI service is busy right now. Please wait a few seconds and try again.")
        if not resp.ok:
            raise AIError(f"The AI service returned an error ({resp.status_code}).")
        return resp.json()


def embed(texts: list[str], task: str) -> list[list[float]]:
    """Embeddings, normalised to length 1 so a dot product is the cosine similarity."""
    task_type = "RETRIEVAL_QUERY" if task == "query" else "RETRIEVAL_DOCUMENT"
    data = _post(f"{BASE}/models/{EMBED_MODEL}:batchEmbedContents", {"requests": [
        {"model": f"models/{EMBED_MODEL}", "content": {"parts": [{"text": t[:4000]}]},
         "taskType": task_type, "outputDimensionality": DIMENSIONS}
        for t in texts
    ]})
    vectors = []
    for e in data["embeddings"]:
        v = e["values"]
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        vectors.append([x / norm for x in v])
    return vectors


def chat_json(messages: list[dict]) -> dict:
    """Ask the chat model for a JSON object."""
    data = _post(f"{BASE}/openai/chat/completions", {
        "model": CHAT_MODEL, "messages": messages, "temperature": 0.3,
        "response_format": {"type": "json_object"},
    })
    text = (data["choices"][0]["message"]["content"] or "").strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(text)
    except ValueError:
        return {"answer": text, "products": []}
