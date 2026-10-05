"use strict";
// Vérifie les choix entre deux chargements de page sans dépendance JavaScript.
const test = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const fs = require("node:fs");
const path = require("node:path");
const source = fs.readFileSync(path.join(__dirname, "../app/static/app.js"), "utf8");
const key = "md-search.preferences.v1";

function page(storage) {
  const element = (value = "") => ({
    value, checked: value === "all", disabled: false, dataset: {}, textContent: "", content: "token", children: [],
    addEventListener() {},
    append(...children) {children.forEach((child) => {child.parent = this; this.children.push(child);});},
    replaceChildren(...children) {this.children = []; this.append(...children);},
    insertBefore(child, reference) {child.parent = this; this.children.splice(this.children.indexOf(reference), 0, child);},
    querySelector(selector) {return this.children.find((child) => child.className === selector.slice(1));},
    remove() {this.parent.children = this.parent.children.filter((child) => child !== this);},
  });
  const formats = ["all", "markdown", "images", "pdf", "documents", "other"].map((value) => ({...element(value), dataset: {label: value, heading: `Recherche ${value}`, placeholder: value, hint: `Aide ${value}`}}));
  const types = ["all", "content", "files", "directories"].map(element);
  const nodes = new Map();
  for (const selector of ['meta[name="local-token"]', "#query", "#exact", "#literal", "#search-title", "#format-hint", "#active-format", ".empty h3", ".empty p", ".preference-note", "#search-form", "#load-more", "#reindex", "#index-count", "#last-index", "#root", "#message", "#index-progress", "#scan-count", "#scan-path", "#results", "#result-count", "#search-button"]) nodes.set(selector, element());
  function findById(node, id) {
    if (node.id === id) return node;
    for (const child of node.children) {
      const found = findById(child, id);
      if (found) return found;
    }
  }
  const document = {
    querySelector(selector) {
      if (selector === 'input[name="format"]:checked') return formats.find((input) => input.checked);
      if (selector === 'input[name="type"]:checked') return types.find((input) => input.checked);
      return nodes.get(selector) || findById(nodes.get("#results"), selector.slice(1));
    },
    querySelectorAll(selector) {
      if (selector === 'input[name="format"]') return formats;
      if (selector === 'input[name="type"]') return types;
      return [...formats, ...types, nodes.get("#exact"), nodes.get("#literal")];
    },
    createElement: () => element(),
  };
  const context = vm.createContext({document, localStorage: storage, URLSearchParams, setTimeout: () => 1, clearTimeout() {}, fetch: async () => ({ok: true, json: async () => ({indexed_files: 0, indexed_markdown: 0, indexed_directories: 0})})});
  vm.runInContext(source, context);
  return {context, nodes, formats, types, document};
}

function storage(initial = null) {
  const values = new Map(initial ? [[key, initial]] : []);
  return {getItem: (name) => values.get(name) ?? null, setItem: (name, value) => values.set(name, value)};
}

test("Le format et les options restent appliqués après rechargement", () => {
  const saved = storage();
  const first = page(saved);
  first.formats.forEach((input) => { input.checked = input.value === "pdf"; });
  first.types.forEach((input) => { input.checked = input.value === "files"; });
  first.nodes.get("#exact").checked = true;
  vm.runInContext("updateFormat(); savePreferences();", first.context);
  const second = page(saved);
  assert.equal(second.formats.find((input) => input.checked).value, "pdf");
  assert.equal(second.types.find((input) => input.checked).value, "files");
  assert.equal(second.nodes.get("#exact").checked, true);
  assert.equal(second.nodes.get("#search-title").textContent, "Recherche pdf");
  assert.equal(second.nodes.get("#active-format").textContent, "pdf");
});

test("Le contenu est désactivé pour les images et restauré pour Markdown", () => {
  const current = page(storage(JSON.stringify({format: "images", type: "content"})));
  assert.equal(current.types.find((input) => input.value === "content").disabled, true);
  assert.equal(current.types.find((input) => input.value === "directories").disabled, true);
  assert.equal(current.types.find((input) => input.checked).value, "all");
  current.formats.forEach((input) => { input.checked = input.value === "markdown"; });
  vm.runInContext("updateFormat();", current.context);
  assert.equal(current.types.find((input) => input.value === "content").disabled, false);
});

test("Les préférences corrompues ou inconnues conservent les valeurs par défaut", () => {
  for (const initial of ["{broken", JSON.stringify({format: "invalid", type: "invalid"})]) {
    const current = page(storage(initial));
    assert.equal(current.formats.find((input) => input.checked).value, "all");
    assert.equal(current.types.find((input) => input.checked).value, "all");
  }
});

test("Un stockage navigateur interdit ne bloque pas la recherche", () => {
  const current = page({getItem() {throw new Error("blocked");}, setItem() {throw new Error("blocked");}});
  assert.equal(current.formats.find((input) => input.checked).value, "all");
  assert.match(current.nodes.get(".preference-note").textContent, /ne permet pas de le mémoriser/);
});

test("Fichiers affiche les titres dans une seule liste, sans extrait, avec pagination", async () => {
  const current = page(storage(JSON.stringify({format: "markdown", type: "files"})));
  current.nodes.get("#query").value = "bootloader";
  const result = (id, type, name) => ({id, type, filename_highlight: name, path_highlight: name, full_path: name, snippet: type === "content" ? "Le <mark>bootloader</mark>" : "", extension: ".md"});
  let request = 0;
  current.context.fetch = async (url) => {
    assert.match(url, /type=files/);
    assert.match(url, /format=markdown/);
    const results = request++ === 0 ? [result(1, "file", "bootloader.md"), result(2, "content", "stm32.md")] : [result(3, "file", "bootloader-guide.md")];
    return {ok: true, json: async () => ({total: 3, results})};
  };
  await vm.runInContext("runSearch()", current.context);
  const list = current.nodes.get("#results");
  assert.equal(list.children.length, 2);
  assert.equal(list.children[0].children[0].innerHTML, "bootloader.md");
  assert.equal(list.children[1].children[0].innerHTML, "stm32.md");
  for (const card of list.children) {
    assert.equal(card.className, "result result-compact");
    assert.equal(card.children.length, 2); // Titre et boutons d'ouverture.
    assert.equal(card.children[1].className, "actions");
    assert.equal(card.querySelector(".snippet"), undefined);
    assert.equal(card.querySelector(".path"), undefined);
  }
  assert.equal(current.nodes.get("#load-more").hidden, false);
  await vm.runInContext("runSearch(true)", current.context);
  assert.equal(list.children.length, 3);
  assert.equal(list.children[2].children[0].innerHTML, "bootloader-guide.md");
  assert.equal(current.nodes.get("#load-more").hidden, true);
});

test("Le statut affiche le scan en cours et interdit un second lancement", async () => {
  const current = page(storage());
  current.context.fetch = async () => ({ok: true, json: async () => ({indexing: true, progress: {processed_files: 42, processed_directories: 3, current_path: "STM32/note.md"}})});
  await vm.runInContext("refreshStatus()", current.context);
  assert.equal(current.nodes.get("#index-progress").hidden, false);
  assert.equal(current.nodes.get("#reindex").disabled, true);
  assert.match(current.nodes.get("#scan-count").textContent, /42 fichiers/);
  assert.equal(current.nodes.get("#scan-path").textContent, "STM32/note.md");
});

test("Expression exacte est mémorisée et transmise dans la recherche", async () => {
  const saved = storage();
  const first = page(saved);
  first.nodes.get("#literal").checked = true;
  vm.runInContext("updateFormat(); savePreferences();", first.context);
  const second = page(saved);
  assert.equal(second.nodes.get("#literal").checked, true);
  assert.equal(second.nodes.get("#exact").disabled, true);
  assert.match(second.nodes.get("#format-hint").textContent, /Expression exacte/);
  second.nodes.get("#query").value = "github-perso";
  second.context.fetch = async (url) => {
    assert.match(url, /q=github-perso/);
    assert.match(url, /literal=true/);
    return {ok: true, json: async () => ({total: 0, results: []})};
  };
  await vm.runInContext("runSearch()", second.context);
  second.nodes.get("#literal").checked = false;
  vm.runInContext("updateFormat();", second.context);
  assert.equal(second.nodes.get("#exact").disabled, false);
});
