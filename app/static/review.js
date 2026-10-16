"use strict";
let reviewActive = false;
let reviewState = null;
let reviewGeneration = 0;

function reviewDate(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function reviewPeriod(period, today = new Date()) {
  const end = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const start = new Date(end);
  if (period === "yesterday") {
    start.setDate(start.getDate() - 1);
    end.setDate(end.getDate() - 1);
  } else if (period === "week") {
    start.setDate(start.getDate() - (start.getDay() + 6) % 7);
  } else if (period === "seven") {
    start.setDate(start.getDate() - 6);
  }
  return {start: reviewDate(start), end: reviewDate(end)};
}

function reviewBounds(startValue, endValue) {
  const localDate = (value) => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) throw new Error("Choisissez deux dates valides.");
    const [year, month, day] = value.split("-").map(Number);
    const date = new Date(year, month - 1, day);
    if (reviewDate(date) !== value) throw new Error("Choisissez deux dates valides.");
    return date;
  };
  const start = localDate(startValue);
  const end = localDate(endValue);
  if (start > end) throw new Error("La date de fin doit être égale ou postérieure à la date de début.");
  // Le jour suivant est calculé au calendrier local : même lors d'un changement d'heure.
  end.setDate(end.getDate() + 1);
  return {start: start.toISOString(), end: end.toISOString()};
}

function reviewMessage(text, error = false) {
  const node = $("#review-message");
  node.textContent = text;
  node.className = error ? "error" : "";
  node.hidden = !text;
}

function renderReview(item) {
  const card = document.createElement("article");
  card.className = "result";
  const title = document.createElement("h3");
  title.textContent = item.filename;
  const path = document.createElement("p");
  path.className = "path";
  path.textContent = item.relative_path;
  const date = document.createElement("p");
  date.className = "muted";
  const time = document.createElement("time");
  time.dateTime = item.modified_at;
  time.textContent = new Date(item.modified_at).toLocaleString("fr-FR");
  date.append("Dernière modification : ", time);
  const actions = document.createElement("div");
  actions.className = "actions";
  for (const [target, label] of [["file", "Ouvrir"], ["directory", "Ouvrir le dossier"]]) {
    const button = document.createElement("button");
    button.className = "secondary";
    button.textContent = label;
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        await api(`/api/open/${item.id}`, {method: "POST", headers: {"Content-Type": "application/json", "X-Local-Token": token}, body: JSON.stringify({target})});
        reviewMessage("Ouverture dans l’application Windows associée.");
      } catch (error) { reviewMessage(error.message, true); }
      finally { button.disabled = false; }
    });
    actions.append(button);
  }
  card.append(title, path, date, actions);
  return card;
}

async function refreshReview(append = false) {
  if (!reviewActive) return;
  const current = ++reviewGeneration;
  try {
    if (!append) {
      reviewState = {...reviewBounds($("#review-start").value, $("#review-end").value), offset: 0};
      $("#review-results").replaceChildren();
      $("#review-count").textContent = "";
      $("#review-more").hidden = true;
    }
    $("#review-submit").disabled = true;
    $("#review-more").disabled = true;
    reviewMessage("Chargement…");
    const data = await api(`/api/review?${new URLSearchParams(reviewState)}`);
    if (current !== reviewGeneration || !reviewActive) return;
    reviewMessage("");
    $("#review-count").textContent = `${data.total} fichier${data.total > 1 ? "s" : ""} · du ${$("#review-start").value.split("-").reverse().join("/")} au ${$("#review-end").value.split("-").reverse().join("/")}`;
    for (const item of data.results) $("#review-results").append(renderReview(item));
    if (!data.total) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = "Aucun fichier Markdown dont la dernière modification tombe dans cette période. Essayez une autre période ou réindexez le dossier.";
      $("#review-results").append(empty);
    }
    reviewState.offset += data.results.length;
    $("#review-more").hidden = reviewState.offset >= data.total;
  } catch (error) {
    if (current === reviewGeneration) {
      reviewMessage(error.message, true);
      $("#review-more").hidden = true;
    }
  } finally {
    if (current === reviewGeneration) {
      $("#review-submit").disabled = false;
      $("#review-more").disabled = false;
    }
  }
}

function setReviewView(active) {
  reviewActive = active;
  reviewGeneration++;
  $("#review-submit").disabled = false;
  $("#review-more").disabled = false;
  $("#review-form").hidden = !active;
  $("#review-results-section").hidden = !active;
  $("#search-form").hidden = active;
  $("#search-results").hidden = active;
  $("#review-view").setAttribute("aria-pressed", String(active));
  $("#search-view").setAttribute("aria-pressed", String(!active));
  $("#review-view").className = active ? "" : "secondary";
  $("#search-view").className = active ? "secondary" : "";
  if (active) {
    $("#search-title").textContent = "Tutoriels à revoir";
    refreshReview();
  } else updateFormat();
}

function setReviewPeriod(period) {
  const dates = reviewPeriod(period);
  $("#review-start").value = dates.start;
  $("#review-end").value = dates.end;
  document.querySelectorAll("[data-period]").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.period === period));
  });
}

$("#search-view").addEventListener("click", () => setReviewView(false));
$("#review-view").addEventListener("click", () => setReviewView(true));
$("#review-form").addEventListener("submit", (event) => { event.preventDefault(); refreshReview(); });
$("#review-more").addEventListener("click", () => refreshReview(true));
document.querySelectorAll("[data-period]").forEach((button) => button.addEventListener("click", () => {
  setReviewPeriod(button.dataset.period);
  refreshReview();
}));
for (const selector of ["#review-start", "#review-end"]) {
  $(selector).addEventListener("change", () => {
    document.querySelectorAll("[data-period]").forEach((button) => button.setAttribute("aria-pressed", "false"));
    refreshReview();
  });
}
setReviewPeriod("seven");
