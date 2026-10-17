"""
Shopify Store Inspector: a Chrome extension (and website) that inspects any online store.
Is it Shopify? Which theme and apps? How big is the catalog, what are the prices? How good is
the page's SEO? Plus AI tips on what to improve.

Run:   python app.py
Open:  http://127.0.0.1:8004

Pages:
  /           Home: what it does, download the extension, inspect a store online
  /inspect    The report for one store (/inspect?url=kith.com)
  /guide      How to install and use the extension
  /privacy    What the extension reads and sends

The extension (folder extension/) calls the same API:
  GET  /api/inspect?url=kith.com   the report
  POST /api/tips                   {report} -> {tips: [...]}  AI suggestions
"""
import json
import os
import time
from collections import defaultdict, deque

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import gemini
import inspector

load_dotenv()
PORT = int(os.getenv("PORT", "8004"))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = FastAPI(title="Shopify Store Inspector")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["Content-Type"])
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
# The website shows reports with the extension's own renderer, so both always look the same.
app.mount("/extension", StaticFiles(directory=os.path.join(BASE_DIR, "extension")), name="extension")


# ---------------- rate limits (keep the free AI quota safe) ----------------

LIMITS = {"inspect": (40, 3600), "tips": (15, 3600)}  # (requests, per seconds) per visitor
_hits: dict = defaultdict(deque)


def check_rate_limit(request: Request, kind: str) -> None:
    max_hits, window = LIMITS[kind]
    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "?").split(",")[0].strip()
    hits = _hits[(kind, ip)]
    now = time.time()
    while hits and now - hits[0] > window:
        hits.popleft()
    if len(hits) >= max_hits:
        raise HTTPException(429, "You've reached the hourly limit of this free tool. Please try again later.")
    hits.append(now)


# ---------------- API ----------------

@app.get("/api/inspect")
def api_inspect(url: str, request: Request):
    check_rate_limit(request, "inspect")
    try:
        return inspector.inspect(url)
    except inspector.InspectError as e:
        raise HTTPException(400, str(e))


TIPS_PROMPT = """You are an expert Shopify consultant. Below is an automatic inspection report of an
online store. Give the store owner 5 specific, practical tips to get more sales and better SEO.

Rules:
- Base every tip ONLY on the report data. Quote the real numbers (e.g. "12 of 40 images have no alt text").
- Don't repeat things that already pass. Don't invent problems or data that isn't in the report.
- Plain English for a non-technical store owner. Each detail: 1-2 sentences.

Reply with ONLY JSON: {"tips": [{"title": "short title", "detail": "what and why", "impact": "high|medium|low"}]}"""


class TipsRequest(BaseModel):
    report: dict


def _summary(r: dict) -> dict:
    """Only the fields the AI needs, so the request stays small."""
    seo = r.get("seo") or {}
    return {
        "url": r.get("url"), "is_shopify": r.get("is_shopify"), "store": r.get("store"),
        "theme": r.get("theme"), "apps": [a.get("name") for a in (r.get("apps") or [])][:25],
        "catalog": r.get("catalog"),
        "seo_score": seo.get("score"),
        "seo_checks": [{k: c.get(k) for k in ("label", "status", "detail")} for c in seo.get("checks") or []][:12],
    }


@app.post("/api/tips")
def api_tips(body: TipsRequest, request: Request):
    check_rate_limit(request, "tips")
    try:
        reply = gemini.chat_json([
            {"role": "system", "content": TIPS_PROMPT},
            {"role": "user", "content": json.dumps(_summary(body.report), ensure_ascii=False)[:12000]},
        ])
    except gemini.AIError as e:
        raise HTTPException(502, str(e))
    tips = [t for t in reply.get("tips") or [] if isinstance(t, dict) and t.get("title")][:6]
    return {"tips": [{"title": str(t["title"]), "detail": str(t.get("detail", "")),
                      "impact": t.get("impact") if t.get("impact") in ("high", "medium", "low") else "medium"} for t in tips]}


# ---------------- pages ----------------

def page(name: str):
    return FileResponse(os.path.join(STATIC_DIR, name))


@app.get("/")
def home():
    return page("home.html")


@app.get("/inspect")
def inspect_page():
    return page("inspect.html")


@app.get("/guide")
def guide():
    return page("guide.html")


@app.get("/privacy")
def privacy():
    return page("privacy.html")


if __name__ == "__main__":
    print(f"Open http://127.0.0.1:{PORT}")
    uvicorn.run(app, host="127.0.0.1", port=PORT)
