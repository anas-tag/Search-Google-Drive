"use strict";
const $ = (selector) => document.querySelector(selector);
const token = $('meta[name="local-token"]').content;
const preferenceKey = "md-search.preferences.v1";
let searchState = null;
let generation = 0;
let statusTimer = null;
let wasIndexing = false;
let manualIndexing = false;

function selectedFormat() {
  return $('input[name="format"]:checked');
}

function restorePreferences() {
  try {
    const preferences = JSON.parse(localStorage.getItem(preferenceKey));
    if (!preferences || typeof preferences !== "object") return;
    for (const name of ["format", "type"]) {
      const inputs = [...document.querySelectorAll(`input[name="${name}"]`)];
      if (inputs.some((input) => input.value === preferences[name])) {
        inputs.forEach((input) => { input.checked = input.value === preferences[name]; });
      }
    }
    $("#exact").checked = preferences.exact === true;
    $("#literal").checked = preferences.literal === true;
  } catch {
    // La recherche fonctionne également si le navigateur interdit le stockage.
  }
}

function savePreferences() {
  try {
    localStorage.setItem(preferenceKey, JSON.stringify({
      format: selectedFormat().value,
      type: $('input[name="type"]:checked').value,
      exact: $("#exact").checked,
      literal: $("#literal").checked,
    }));
  } catch {
    $(".preference-note").textContent = "Votre choix reste appliqué sur cette page. Le navigateur ne permet pas de le mémoriser pour la prochaine visite.";
  }
}

function updateFormat() {
  const option = selectedFormat();
  $("#exact").disabled = $("#literal").checked;
  const inputs = [...document.querySelectorAll('input[name="type"]')];
  for (const input of inputs) {
    input.disabled = (input.value === "content" && !["all", "markdown"].includes(option.value))
      || (input.value === "directories" && option.value !== "all");
  }
  if (inputs.some((input) => input.checked && input.disabled)) {
    inputs.forEach((input) => { input.checked = input.value === "all"; });
  }
  $("#search-title").textContent = option.dataset.heading;
  $("#query").placeholder = option.dataset.placeholder;
  $("#format-hint").textContent = option.dataset.hint + ($("#literal").checked ? " Expression exacte : les espaces, tirets et signes saisis sont conservés." : "");
  $("#active-format").textContent = option.dataset.label;
  const emptyTitle = $(".empty h3");
  const emptyHint = $(".empty p");
  if (emptyTitle) emptyTitle.textContent = option.value === "all" ? "Vos tutoriels, à portée de recherche" : `Explorez vos ${option.dataset.label.toLocaleLowerCase("fr-FR")}`;
  if (emptyHint) emptyHint.textContent = option.dataset.hint;
}

function message(text, error = false) {
  const node = $("#message");
  node.textContent = text;
  node.className = error ? "error" : "";
  node.hidden = !text;
}

async function api(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Paramètres de recherche invalides.");
  return data;
}

async function refreshStatus() {
  if (statusTimer !== null) { clearTimeout(statusTimer); statusTimer = null; }
  try {
    const status = await api("/api/status");
    $("#index-count").textContent = `${status.indexed_files} fichiers indexés · ${status.indexed_markdown} Markdown · ${status.indexed_directories} dossiers`;
    $("#last-index").textContent = status.last_indexation ? `Dernière indexation : ${new Date(status.last_indexation).toLocaleString("fr-FR")}` : "Aucune indexation effectuée";
    $("#root").textContent = status.root;
    $("#index-progress").hidden = !status.indexing;
    $("#reindex").disabled = Boolean(status.indexing || manualIndexing);
    $("#reindex").textContent = status.indexing || manualIndexing ? "Indexation…" : "↻ Réindexer";
    if (status.indexing) {
      const progress = status.progress || {};
      $("#scan-count").textContent = `· ${progress.processed_files || 0} fichiers parcourus · ${progress.processed_directories || 0} dossiers`;
      $("#scan-path").textContent = progress.current_path || "Préparation du scan…";
      statusTimer = setTimeout(refreshStatus, 1500);
    } else if (wasIndexing && searchState) {
      await runSearch();
    }
    wasIndexing = Boolean(status.indexing);
    if (status.error) message(status.error, true);
  } catch (error) {
    message(error.message, true);
    if (wasIndexing || manualIndexing) statusTimer = setTimeout(refreshStatus, 2500);
  }
}

function renderResult(item) {
  const compact = searchState?.type === "files";
  const card = document.createElement("article");
  card.className = compact ? "result result-compact" : "result";
  const badge = document.createElement("span");
  badge.className = "badge";
  badge.textContent = {content: "CONTENU", file: "FICHIER", directory: "DOSSIER"}[item.type];
  const title = document.createElement("h3");
  // Ces trois champs sont échappés côté serveur, puis balisés exclusivement avec <mark>.
  title.innerHTML = item.filename_highlight;
  title.title = item.full_path;
  const path = document.createElement("p");
  path.className = "path";
  path.innerHTML = item.path_highlight;
  path.title = item.full_path;
  if (compact) card.append(title);
  else card.append(badge, title, path);
  if (item.extension && !compact) {
    const extension = document.createElement("span");
    extension.className = "extension";
    extension.textContent = item.extension.slice(1).toUpperCase();
    card.insertBefore(extension, title);
  }
  if (item.snippet && !compact) {
    const excerpt = document.createElement("p");
    excerpt.className = "snippet";
    excerpt.innerHTML = item.snippet;
    card.append(excerpt);
  }
  const actions = document.createElement("div");
  actions.className = "actions";
  const targets = item.type === "directory" ? [["directory", "Ouvrir le dossier"]] : [["file", "Ouvrir"], ["directory", "Ouvrir le dossier"]];
  for (const [target, label] of targets) {
    const button = document.createElement("button");
    button.className = "secondary";
    button.textContent = label;
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        await api(`/api/open/${item.id}`, {method: "POST", headers: {"Content-Type": "application/json", "X-Local-Token": token}, body: JSON.stringify({target})});
        message("Ouverture dans l’application Windows associée.");
      } catch (error) { message(error.message, true); }
      finally { button.disabled = false; }
    });
    actions.append(button);
  }
  card.append(actions);
  return card;
}

async function runSearch(append = false) {
  const query = $("#query").value.trim();
  if (!query) return;
  const current = ++generation;
  if (!append) searchState = {q: query, type: $('input[name="type"]:checked').value, format: selectedFormat().value, exact: $("#exact").checked, literal: $("#literal").checked, offset: 0};
  if (!searchState) return;
  $("#search-button").disabled = true;
  $("#load-more").disabled = true;
  message("");
  try {
    const data = await api(`/api/search?${new URLSearchParams(searchState)}`);
    if (current !== generation) return;
    if (!append) $("#results").replaceChildren();
    $("#result-count").textContent = `${data.total} résultat${data.total > 1 ? "s" : ""}`;
    for (const result of data.results) $("#results").append(renderResult(result));
    if (!data.total) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = "Aucun résultat. Essayez un autre mot ou un autre filtre.";
      $("#results").append(empty);
    }
    searchState.offset += data.results.length;
    $("#load-more").hidden = searchState.offset >= data.total;
  } catch (error) {
    if (current === generation) { message(error.message, true); $("#load-more").hidden = true; }
  } finally {
    if (current === generation) { $("#search-button").disabled = false; $("#load-more").disabled = false; }
  }
}

$("#search-form").addEventListener("submit", (event) => { event.preventDefault(); savePreferences(); runSearch(); });
document.querySelectorAll('input[name="format"], input[name="type"], #exact, #literal').forEach((input) => input.addEventListener("change", () => {
  updateFormat();
  savePreferences();
  runSearch();
}));
$("#load-more").addEventListener("click", () => runSearch(true));
$("#reindex").addEventListener("click", async () => {
  const button = $("#reindex");
  button.disabled = true;
  manualIndexing = true;
  button.textContent = "Indexation…";
  statusTimer = setTimeout(refreshStatus, 500);
  message("Mise à jour de l’index en cours…");
  try {
    const report = await api("/api/reindex", {method: "POST", headers: {"X-Local-Token": token}});
    if (searchState) await runSearch();
    message(`${report.added} ajouts · ${report.updated} modifications · ${report.deleted} suppressions · ${report.unchanged} inchangés${report.skipped ? ` · ${report.skipped} éléments ignorés (voir les logs)` : ""}`, !report.success);
    await refreshStatus();
  } catch (error) { message(error.message, true); }
  finally { manualIndexing = false; await refreshStatus(); }
});
restorePreferences();
updateFormat();
savePreferences();
refreshStatus();
