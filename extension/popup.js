// Popup: inspects the website in the current tab (or any address typed in the box).
const API = window.SSI_API;
const out = document.getElementById("out");
document.getElementById("site").href = API + "/guide";

async function inspect(url) {
  SSI.loading(out, "Inspecting " + url.replace(/^https?:\/\//, "").replace(/\/$/, "") + "…");
  try {
    const resp = await fetch(API + "/api/inspect?url=" + encodeURIComponent(url));
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Couldn't inspect this page. Please try again.");
    SSI.render(out, data, { api: API });
  } catch (e) {
    SSI.error(out, e.message === "Failed to fetch" ? "Couldn't reach the inspector. Check your internet connection." : e.message);
  }
}

document.getElementById("form").addEventListener("submit", (e) => {
  e.preventDefault();
  const v = document.getElementById("url").value.trim();
  if (v) inspect(v);
});

// For testing: popup.html?url=kith.com inspects that address instead of the current tab.
const forced = new URLSearchParams(location.search).get("url");
if (forced) {
  inspect(forced);
} else {
  chrome.tabs.query({ active: true, currentWindow: true }, ([tab]) => {
    const url = tab && tab.url;
    if (url && /^https?:\/\//.test(url) && !/^https?:\/\/(localhost|127\.0\.0\.1)/.test(url)) {
      inspect(url);
    } else {
      out.innerHTML = `<div class="card"><h3>👋 Open a store first</h3><p class="muted" style="margin:0">
        Go to any online store, like <b>kith.com</b> or <b>allbirds.com</b>, and click the extension again.
        Or type a store's address in the box above.</p></div>`;
    }
  });
}
