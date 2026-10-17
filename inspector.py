"""
Inspects a web page and, when it's a Shopify store, the store behind it.

Everything comes from public data any visitor can see:
  - the page's HTML and headers  -> is it Shopify? theme, apps, SEO checks
  - /meta.json                   -> store name, currency, product and collection counts
  - /products.json               -> prices, sales, stock, product types (first 250 products)
"""
import html
import ipaddress
import json
import re
from collections import Counter
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ShopifyStoreInspector/1.0)"}
MAX_PRODUCTS = 250


class InspectError(Exception):
    pass


# ---------------- safe fetching ----------------

def normalize_url(value: str) -> str:
    """'Kith.com/collections/x' -> 'https://kith.com/collections/x'. Only public https sites."""
    value = (value or "").strip()
    if not value:
        raise InspectError("Please enter a website address, like kith.com.")
    url = value if "://" in value else "https://" + value
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or not re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+", host) \
            or host.endswith((".local", ".internal", "localhost")):
        raise InspectError("Please enter a website address, like kith.com.")
    try:
        ipaddress.ip_address(host)
        raise InspectError("Please enter the website's address, not an IP address.")
    except ValueError:
        pass
    return "https://" + host + (parsed.path or "/") + (("?" + parsed.query) if parsed.query else "")


def fetch(url: str, max_bytes: int = 4_000_000) -> requests.Response | None:
    """GET a public page. Follows up to 4 redirects, only to other public https sites."""
    for _ in range(5):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=False, stream=True)
        except requests.RequestException:
            return None
        if resp.is_redirect:
            url = normalize_url(urljoin(url, resp.headers.get("location", "")))
            continue
        body = resp.raw.read(max_bytes + 1, decode_content=True)
        if len(body) > max_bytes:
            body = body[:max_bytes]
        resp._content = body
        resp.final_url = url
        return resp
    return None


def fetch_json(url: str):
    resp = fetch(url, 8_000_000)
    if resp is None or not resp.ok:
        return None
    try:
        return resp.json()
    except ValueError:
        return None


# ---------------- page parsing ----------------

class PageParser(HTMLParser):
    """Collects what the SEO checks need from the HTML."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title, self.in_title, self.in_h1, self.in_ldjson = "", False, False, False
        self.meta, self.links, self.h1s, self.images, self.ldjson = {}, [], [], [], []
        self.lang = ""
        self._h1_text, self._ld = "", ""
        self.svg_depth, self.title_done = 0, False  # icons have their own <title>; only the page's counts

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "html":
            self.lang = a.get("lang", "")
        elif tag == "svg":
            self.svg_depth += 1
        elif tag == "title" and not self.svg_depth and not self.title_done:
            self.in_title = True
        elif tag == "meta":
            key = (a.get("name") or a.get("property") or "").lower()
            if key and key not in self.meta:
                self.meta[key] = a.get("content", "")
        elif tag == "link":
            self.links.append(a)
        elif tag == "h1":
            self.in_h1, self._h1_text = True, ""
        elif tag == "img":
            self.images.append(a)
        elif tag == "script" and a.get("type", "").lower() == "application/ld+json":
            self.in_ldjson, self._ld = True, ""

    def handle_endtag(self, tag):
        if tag == "svg" and self.svg_depth:
            self.svg_depth -= 1
        elif tag == "title" and self.in_title:
            self.in_title, self.title_done = False, True
        elif tag == "h1" and self.in_h1:
            self.in_h1 = False
            self.h1s.append(" ".join(self._h1_text.split()))
        elif tag == "script" and self.in_ldjson:
            self.in_ldjson = False
            self.ldjson.append(self._ld)

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        if self.in_h1:
            self._h1_text += data
        if self.in_ldjson:
            self._ld += data


def _ld_types(blocks: list[str]) -> list[str]:
    types = []

    def walk(node):
        if isinstance(node, dict):
            t = node.get("@type")
            if isinstance(t, str):
                types.append(t)
            elif isinstance(t, list):
                types.extend(x for x in t if isinstance(x, str))
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    for b in blocks:
        try:
            walk(json.loads(b))
        except ValueError:
            continue
    return sorted(set(types))


def seo_checks(p: PageParser) -> dict:
    """Quick on-page SEO checks. Each check: pass (full points), warn (half) or fail (none)."""
    checks = []

    def add(label, status, detail, weight=10):
        checks.append({"label": label, "status": status, "detail": detail, "weight": weight})

    title = " ".join(html.unescape(p.title).split())
    if not title:
        add("Page title", "fail", "The page has no <title>.", 15)
    elif 10 <= len(title) <= 60:
        add("Page title", "pass", f"{len(title)} characters: “{title}”", 15)
    else:
        add("Page title", "warn", f"{len(title)} characters (best: 10–60): “{title[:90]}”", 15)

    desc = p.meta.get("description", "").strip()
    if not desc:
        add("Meta description", "fail", "Missing. Google will pick random text from the page.", 15)
    elif 50 <= len(desc) <= 160:
        add("Meta description", "pass", f"{len(desc)} characters.", 15)
    else:
        add("Meta description", "warn", f"{len(desc)} characters (best: 50–160).", 15)

    h1s = [h for h in p.h1s if h]
    if len(h1s) == 1:
        add("Main heading (H1)", "pass", f"One H1: “{h1s[0][:80]}”")
    elif not h1s:
        add("Main heading (H1)", "fail", "No H1 heading on the page.")
    else:
        add("Main heading (H1)", "warn", f"{len(h1s)} H1 headings (best: exactly one).")

    imgs = [i for i in p.images if i.get("src") or i.get("data-src") or i.get("srcset")]
    no_alt = [i for i in imgs if not i.get("alt", "").strip()]
    if not imgs:
        add("Image alt text", "pass", "No images in the page HTML.")
    elif not no_alt:
        add("Image alt text", "pass", f"All {len(imgs)} images have alt text.")
    else:
        pct = round(100 * len(no_alt) / len(imgs))
        add("Image alt text", "warn" if pct <= 25 else "fail", f"{len(no_alt)} of {len(imgs)} images ({pct}%) have no alt text.")

    canonical = next((l.get("href") for l in p.links if "canonical" in l.get("rel", "").lower()), "")
    add("Canonical link", "pass" if canonical else "warn",
        "Set." if canonical else "Missing. It tells Google which URL is the main one.", 5)

    og = [k for k in ("og:title", "og:description", "og:image") if p.meta.get(k)]
    add("Social sharing tags", "pass" if len(og) == 3 else ("warn" if og else "fail"),
        "og:title, og:description and og:image are set." if len(og) == 3 else
        f"Missing: {', '.join(k for k in ('og:title', 'og:description', 'og:image') if k not in og)}.", 10)

    types = _ld_types(p.ldjson)
    add("Structured data", "pass" if types else "warn",
        f"Found: {', '.join(types[:6])}." if types else "No JSON-LD found. Rich results (stars, prices) need it.", 10)

    add("Mobile viewport", "pass" if p.meta.get("viewport") else "fail",
        "Set." if p.meta.get("viewport") else "Missing. The page may look tiny on phones.", 10)
    add("Page language", "pass" if p.lang else "warn", f"lang=“{p.lang}”." if p.lang else "No lang attribute on <html>.", 5)

    total = sum(c["weight"] for c in checks)
    got = sum(c["weight"] * {"pass": 1, "warn": 0.5, "fail": 0}[c["status"]] for c in checks)
    return {"score": round(100 * got / total), "checks": checks}


# ---------------- Shopify details ----------------

APPS = [  # (signature in the HTML, app name, category)
    ("klaviyo", "Klaviyo", "Email & SMS"), ("omnisend", "Omnisend", "Email & SMS"),
    ("attentive", "Attentive", "Email & SMS"), ("postscript", "Postscript", "Email & SMS"),
    ("privy", "Privy", "Pop-ups"), ("mailchimp", "Mailchimp", "Email & SMS"),
    ("judge.me", "Judge.me", "Reviews"), ("yotpo", "Yotpo", "Reviews"), ("loox", "Loox", "Reviews"),
    ("okendo", "Okendo", "Reviews"), ("stamped.io", "Stamped", "Reviews"), ("trustpilot", "Trustpilot", "Reviews"),
    ("reviews.io", "REVIEWS.io", "Reviews"), ("bazaarvoice", "Bazaarvoice", "Reviews"),
    ("gorgias", "Gorgias", "Customer support"), ("zendesk", "Zendesk", "Customer support"),
    ("intercom", "Intercom", "Customer support"), ("tidio", "Tidio", "Customer support"),
    ("afterpay", "Afterpay", "Buy now, pay later"), ("klarna", "Klarna", "Buy now, pay later"),
    ("affirm", "Affirm", "Buy now, pay later"), ("sezzle", "Sezzle", "Buy now, pay later"),
    ("recharge", "Recharge", "Subscriptions"), ("global-e", "Global-e", "International selling"),
    ("rebuy", "Rebuy", "Upsells"), ("nosto", "Nosto", "Personalisation"),
    ("searchanise", "Searchanise", "Search"), ("boost-commerce", "Boost Commerce", "Search"),
    ("smile.io", "Smile.io", "Loyalty"), ("loyaltylion", "LoyaltyLion", "Loyalty"),
    ("pagefly", "PageFly", "Page builder"), ("gempages", "GemPages", "Page builder"), ("shogun", "Shogun", "Page builder"),
    ("googletagmanager", "Google Tag Manager", "Analytics"), ("google-analytics", "Google Analytics", "Analytics"),
    ("hotjar", "Hotjar", "Analytics"), ("fbevents", "Meta Pixel", "Ads tracking"),
    ("connect.facebook.net", "Meta Pixel", "Ads tracking"), ("analytics.tiktok", "TikTok Pixel", "Ads tracking"),
    ("pinimg.com/ct", "Pinterest Tag", "Ads tracking"), ("snapchat", "Snap Pixel", "Ads tracking"),
]


def detect_apps(page_html: str) -> list[dict]:
    low = page_html.lower()
    found = {}
    for sig, name, cat in APPS:
        if sig in low and name not in found:
            found[name] = {"name": name, "category": cat}
    # Theme app embeds load from cdn.shopify.com/extensions/<id>/<app-handle>-<version>/
    for handle in sorted(set(re.findall(r"cdn\.shopify\.com/extensions/[^/\"']+/([a-z0-9][a-z0-9_-]*?)-\d", low))):
        label = handle.replace("-", " ").replace("_", " ").strip().title()
        if not any(label.lower().startswith(n.lower()) or n.lower() in label.lower() for n in found):
            found[label] = {"name": label, "category": "App embed"}
    return list(found.values())


def theme_info(page_html: str) -> dict | None:
    m = re.search(r"Shopify\.theme\s*=\s*(\{.*?\});", page_html)
    if not m:
        return None
    try:
        t = json.loads(m.group(1))
    except ValueError:
        return None
    return {
        "name": t.get("name") or "",
        "schema_name": t.get("schema_name") or "",
        "version": t.get("schema_version") or "",
        "theme_store_id": t.get("theme_store_id"),
    }


def _shorten(text: str, limit: int) -> str:
    """Cut long text at a word boundary and add an ellipsis."""
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def _text(h: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", h or "")).split())


def catalog_stats(products: list[dict]) -> dict:
    prices, on_sale, sold_out, no_image, short_desc = [], 0, 0, 0, 0
    types, vendors, dated = Counter(), Counter(), []
    for p in products:
        variants = p.get("variants") or []
        vp = [float(v["price"]) for v in variants if v.get("price") not in (None, "")]
        if vp:
            prices.append(min(vp))
        if any(v.get("compare_at_price") and float(v["compare_at_price"]) > float(v.get("price") or 0) for v in variants):
            on_sale += 1
        if variants and not any(v.get("available") for v in variants):
            sold_out += 1
        if not p.get("images"):
            no_image += 1
        if len(_text(p.get("body_html"))) < 100:
            short_desc += 1
        if p.get("product_type"):
            types[p["product_type"]] += 1
        if p.get("vendor"):
            vendors[p["vendor"]] += 1
        if p.get("published_at"):
            dated.append((p["published_at"], p["title"]))
    n = len(products) or 1
    newest = sorted(dated, reverse=True)[:3]
    return {
        "sampled": len(products),
        "min_price": min(prices) if prices else None,
        "max_price": max(prices) if prices else None,
        "avg_price": round(sum(prices) / len(prices), 2) if prices else None,
        "on_sale_pct": round(100 * on_sale / n),
        "sold_out_pct": round(100 * sold_out / n),
        "missing_images": no_image,
        "short_descriptions": short_desc,
        "top_types": types.most_common(5),
        "top_vendors": vendors.most_common(3),
        "newest": [{"title": t, "date": d[:10]} for d, t in newest],
    }


# ---------------- main ----------------

def inspect(url: str) -> dict:
    url = normalize_url(url)
    page = fetch(url)
    if page is None:
        raise InspectError("Couldn't open that website. Check the address and try again.")
    final_url = page.final_url
    origin = "https://" + urlparse(final_url).hostname
    text = page.text

    signals = []
    if page.headers.get("powered-by", "").lower() == "shopify":
        signals.append("“Powered-By: Shopify” header")
    if page.headers.get("x-shopid") or page.headers.get("x-shopify-stage"):
        signals.append("Shopify server headers")
    if "Shopify.theme" in text:
        signals.append("Shopify theme code in the page")
    if "cdn.shopify.com" in text:
        signals.append("Files loaded from cdn.shopify.com")
    is_shopify = len(signals) >= 1 and ("cdn.shopify.com" in text or "Shopify.theme" in text or signals[0].startswith("“Powered"))

    parser = PageParser()
    try:
        parser.feed(text)
    except Exception:  # broken HTML shouldn't stop the report
        pass

    report = {
        "url": final_url,
        "domain": urlparse(final_url).hostname,
        "status": page.status_code,
        "is_shopify": is_shopify,
        "signals": signals,
        "password_protected": "/password" in final_url,
        "seo": seo_checks(parser),
        "apps": detect_apps(text),
        "theme": None, "store": None, "catalog": None,
        "inspected_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    }
    if not is_shopify:
        return report

    report["theme"] = theme_info(text)
    meta = fetch_json(origin + "/meta.json") or {}
    report["store"] = {
        "name": meta.get("name") or report["domain"],
        "description": _shorten(meta.get("description") or "", 200),
        "myshopify_domain": meta.get("myshopify_domain") or "",
        "currency": meta.get("currency") or "",
        "country": meta.get("country") or "",
        "products_count": meta.get("published_products_count"),
        "collections_count": meta.get("published_collections_count"),
        "ships_to": len(meta.get("ships_to_countries") or []),
        "shop_pay_installments": bool(meta.get("offers_shop_pay_installments")),
    }
    data = fetch_json(origin + f"/products.json?limit={MAX_PRODUCTS}")
    if isinstance(data, dict) and isinstance(data.get("products"), list):
        report["catalog"] = catalog_stats(data["products"])
    return report
