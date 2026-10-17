// Draws an inspection report. Shared by the extension popup and the website.
// Usage: SSI.render(container, report, { api: "https://…", wide: false })
(function () {
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const num = (n) => (n == null ? "–" : Number(n).toLocaleString());

  function money(n, currency) {
    if (n == null) return "–";
    try {
      return currency ? new Intl.NumberFormat(undefined, { style: "currency", currency, maximumFractionDigits: n >= 100 ? 0 : 2 }).format(n) : n.toFixed(2);
    } catch { return n.toFixed(2); }
  }

  function header(r) {
    const name = r.store?.name || r.domain;
    return `<div class="card"><div class="head">
      <div class="logo">${r.is_shopify ? "🛍️" : "🌐"}</div>
      <div><h2>${esc(name)}</h2><a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.url)}</a><br>
        <span class="badge ${r.is_shopify ? "yes" : "no"}">${r.is_shopify ? "✓ Shopify store" : "Not a Shopify store"}</span></div>
    </div>
    ${r.signals.length ? `<ul class="signals">${r.signals.map((s) => `<li>${esc(s)}</li>`).join("")}</ul>` : ""}
    ${r.store?.description ? `<p class="muted" style="margin:8px 0 0;font-size:12.5px">${esc(r.store.description)}</p>` : ""}
    </div>`;
  }

  function stats(r) {
    const s = r.store || {}, c = r.catalog || {};
    const cur = s.currency;
    const items = [
      [num(s.products_count), "Products"],
      [num(s.collections_count), "Collections"],
      [c.min_price != null ? `${money(c.min_price, cur)} – ${money(c.max_price, cur)}` : "–", "Price range"],
      [money(c.avg_price, cur), "Average price"],
      [c.sampled ? `${c.on_sale_pct}%` : "–", "Products on sale"],
      [c.sampled ? `${c.sold_out_pct}%` : "–", "Sold out"],
      [s.currency || "–", "Currency"],
      [s.ships_to ? `${s.ships_to} ${s.ships_to === 1 ? "country" : "countries"}` : "–", "Ships to"],
    ];
    return `<div class="card"><h3>📊 Store at a glance</h3><div class="stats">
      ${items.map(([v, l]) => `<div class="stat"><b>${esc(v)}</b><span>${esc(l)}</span></div>`).join("")}
    </div>${c.sampled ? `<p class="muted" style="margin:8px 0 0;font-size:12px">Prices and sales are based on the first ${c.sampled} products.</p>` : ""}</div>`;
  }

  function theme(r) {
    const t = r.theme;
    if (!t) return `<div class="card"><h3>🎨 Theme</h3><p class="muted" style="margin:0">The theme name isn't visible on this page.</p></div>`;
    const kind = t.theme_store_id ? `Theme Store theme (#${esc(t.theme_store_id)})` : "Custom or third-party theme";
    return `<div class="card"><h3>🎨 Theme</h3>
      <div class="stats">
        <div class="stat"><b>${esc(t.schema_name || "–")}</b><span>Theme${t.version ? " · v" + esc(t.version) : ""}</span></div>
        <div class="stat"><b>${esc(kind)}</b><span>Type</span></div>
      </div>
      ${t.name ? `<p class="muted" style="margin:8px 0 0;font-size:12.5px">Store's name for it: “${esc(t.name)}”</p>` : ""}
    </div>`;
  }

  function apps(r) {
    if (!r.apps.length) return `<div class="card"><h3>🧩 Apps &amp; tools</h3><p class="muted" style="margin:0">No known apps detected on this page.</p></div>`;
    return `<div class="card"><h3>🧩 Apps &amp; tools (${r.apps.length})</h3><div class="chips">
      ${r.apps.map((a) => `<span class="chip">${esc(a.name)} <small>· ${esc(a.category)}</small></span>`).join("")}
    </div></div>`;
  }

  function catalog(r) {
    const c = r.catalog;
    if (!c || !c.sampled) return "";
    const max = Math.max(...c.top_types.map((t) => t[1]), 1);
    return `<div class="card"><h3>🏷️ Catalog</h3>
      ${c.top_types.length ? `<div class="muted" style="font-size:12.5px;margin-bottom:6px">Top product types</div><div class="bars">
        ${c.top_types.map(([t, n]) => `<div class="bar"><span class="label">${esc(t)}</span><span class="n">${n}</span><div class="track"><div class="fill" style="width:${Math.round((100 * n) / max)}%"></div></div></div>`).join("")}
      </div>` : ""}
      ${c.newest.length ? `<div class="muted" style="font-size:12.5px;margin:12px 0 2px">Newest products</div><ul class="plain">
        ${c.newest.map((p) => `<li>${esc(p.title)} <span class="muted">· ${esc(p.date)}</span></li>`).join("")}</ul>` : ""}
      <div class="muted" style="font-size:12.5px;margin:12px 0 2px">Product page health (first ${c.sampled})</div>
      <ul class="plain">
        <li>${c.missing_images ? "⚠️" : "✅"} ${c.missing_images} products without images</li>
        <li>${c.short_descriptions ? "⚠️" : "✅"} ${c.short_descriptions} products with very short descriptions</li>
      </ul>
    </div>`;
  }

  function seo(r) {
    const s = r.seo, color = s.score >= 80 ? "var(--s-green)" : s.score >= 55 ? "var(--s-amber)" : "var(--s-red)";
    const icon = { pass: "✓", warn: "!", fail: "✕" };
    return `<div class="card"><h3>🔍 SEO check of this page</h3>
      <div class="score"><div class="ring" style="--p:${s.score};--c:${color}"><b>${s.score}</b></div>
        <div class="muted" style="font-size:13px">Score out of 100 from ${s.checks.length} on-page checks.
        ${s.score >= 80 ? "Looking good!" : s.score >= 55 ? "A few things to fix." : "Needs work."}</div></div>
      ${s.checks.map((c) => `<div class="check ${c.status}"><span class="i">${icon[c.status]}</span><div><b>${esc(c.label)}</b><div>${esc(c.detail)}</div></div></div>`).join("")}
    </div>`;
  }

  function tipsCard() {
    return `<div class="card" data-tips><h3>✨ AI tips to improve this store</h3>
      <p class="muted" style="margin:0 0 10px;font-size:13px">Google Gemini reads this report and suggests what to fix first.</p>
      <button class="btn" data-get-tips type="button">Get AI tips</button><div data-tips-out></div></div>`;
  }

  function plainText(r) {
    const lines = [`Store inspection: ${r.store?.name || r.domain} (${r.url})`, `Shopify: ${r.is_shopify ? "yes" : "no"}`];
    if (r.store) lines.push(`Products: ${r.store.products_count ?? "?"} · Collections: ${r.store.collections_count ?? "?"} · Currency: ${r.store.currency}`);
    if (r.theme) lines.push(`Theme: ${r.theme.schema_name} ${r.theme.version}`);
    if (r.apps.length) lines.push(`Apps: ${r.apps.map((a) => a.name).join(", ")}`);
    lines.push(`SEO score: ${r.seo.score}/100`);
    r.seo.checks.forEach((c) => lines.push(`  [${c.status.toUpperCase()}] ${c.label}: ${c.detail}`));
    lines.push(`Inspected ${r.inspected_at} with Shopify Store Inspector`);
    return lines.join("\n");
  }

  function render(el, r, opts = {}) {
    el.classList.add("ssi");
    el.classList.toggle("wide", !!opts.wide);
    const note = r.password_protected ? `<div class="note">🔒 This store is password-protected, so only limited data is visible.</div>` : "";
    const left = header(r) + (r.is_shopify ? stats(r) + theme(r) + apps(r) : apps(r));
    const right = (r.is_shopify ? catalog(r) : "") + seo(r) + tipsCard();
    el.innerHTML = note + (opts.wide ? `<div class="cols"><div>${left}</div><div>${right}</div></div>` : left + right) +
      `<div class="foot"><span>Inspected ${esc(r.inspected_at)} · public store data only</span>
       <button class="btn ghost" data-copy type="button">Copy report</button></div>`;

    el.querySelector("[data-copy]").addEventListener("click", async (e) => {
      try { await navigator.clipboard.writeText(plainText(r)); e.target.textContent = "Copied ✓"; }
      catch { e.target.textContent = "Couldn't copy"; }
      setTimeout(() => (e.target.textContent = "Copy report"), 1500);
    });

    const btn = el.querySelector("[data-get-tips]"), out = el.querySelector("[data-tips-out]");
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      btn.textContent = "Thinking…";
      try {
        const resp = await fetch(opts.api + "/api/tips", {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ report: r }),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Couldn't get tips. Please try again.");
        btn.remove();
        out.innerHTML = data.tips.map((t) => `<div class="tip"><b>${esc(t.title)}</b><span class="impact ${t.impact}">${t.impact}</span><p>${esc(t.detail)}</p></div>`).join("")
          || `<p class="muted">No tips this time. Please try again.</p>`;
      } catch (e) {
        btn.disabled = false;
        btn.textContent = "Try again";
        out.innerHTML = `<div class="error" style="margin-top:10px">${esc(e.message)}</div>`;
      }
    });
  }

  function loading(el, text) {
    el.classList.add("ssi");
    el.innerHTML = `<div class="loading"><div class="spinner"></div>${esc(text || "Inspecting the store…")}</div>`;
  }

  function error(el, text) {
    el.classList.add("ssi");
    el.innerHTML = `<div class="error">${esc(text)}</div>`;
  }

  window.SSI = { render, loading, error };
})();
