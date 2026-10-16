"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const fs = require("node:fs");
const path = require("node:path");
process.env.TZ = "Europe/Paris";
const source = fs.readFileSync(path.join(__dirname, "../app/static/review.js"), "utf8");

function page() {
  const nodes = new Map();
  const element = () => ({value: "", children: [], attributes: {}, listeners: {},
    setAttribute(name, value) {this.attributes[name] = value;},
    addEventListener(name, handler) {this.listeners[name] = handler;},
    append(...children) {this.children.push(...children);},
    replaceChildren() {this.children = [];},
  });
  const $ = (selector) => {
    if (!nodes.has(selector)) nodes.set(selector, element());
    return nodes.get(selector);
  };
  let response = {total: 0, results: []};
  const requests = [];
  const context = vm.createContext({$, Date, URLSearchParams, token: "token", updateFormat() {},
    document: {querySelectorAll: () => [], createElement: element},
    api: async (url) => {requests.push(url); return response;},
  });
  vm.runInContext(source, context);
  return {context, $, requests, respond(value) {response = value;}};
}

test("Les raccourcis utilisent le calendrier local et le lundi", () => {
  const {context} = page();
  const period = (name) => JSON.parse(vm.runInContext(`JSON.stringify(reviewPeriod('${name}', new Date(2026, 9, 14)))`, context));
  assert.deepEqual(period("today"), {start: "2026-10-14", end: "2026-10-14"});
  assert.deepEqual(period("yesterday"), {start: "2026-10-13", end: "2026-10-13"});
  assert.deepEqual(period("week"), {start: "2026-10-12", end: "2026-10-14"});
  assert.deepEqual(period("seven"), {start: "2026-10-08", end: "2026-10-14"});
});

test("Les journées sont incluses malgré le changement d'heure", () => {
  const {context} = page();
  const bounds = JSON.parse(vm.runInContext('JSON.stringify(reviewBounds("2026-03-29", "2026-03-29"))', context));
  assert.deepEqual(bounds, {start: "2026-03-28T23:00:00.000Z", end: "2026-03-29T22:00:00.000Z"});
  assert.throws(() => vm.runInContext('reviewBounds("2026-02-30", "2026-03-01")', context), /valides/);
  assert.throws(() => vm.runInContext('reviewBounds("2026-03-30", "2026-03-29")', context), /postérieure/);
});

test("La vue charge sans mot recherché, pagine et affiche les noms comme du texte", async () => {
  const current = page();
  const {$, context} = current;
  $("#review-start").value = "2026-10-14";
  $("#review-end").value = "2026-10-14";
  current.respond({total: 2, results: [{id: 1, filename: "<img>.md", relative_path: "notes/<img>.md", modified_at: "2026-10-14T12:00:00Z"}]});
  await vm.runInContext('reviewActive = true; refreshReview()', context);
  assert.match(current.requests[0], /offset=0/);
  assert.equal($("#review-results").children[0].children[0].textContent, "<img>.md");
  assert.equal($("#review-more").hidden, false);
  current.respond({total: 2, results: [{id: 2, filename: "second.md", relative_path: "second.md", modified_at: "2026-10-14T11:00:00Z"}]});
  await vm.runInContext('refreshReview(true)', context);
  assert.match(current.requests[1], /offset=1/);
  assert.equal($("#review-results").children.length, 2);
  assert.equal($("#review-more").hidden, true);
  await vm.runInContext('setReviewView(false)', context);
  assert.equal($("#review-form").hidden, true);
  assert.equal($("#search-form").hidden, false);
});

test("Une réponse ancienne ne remplace pas une période plus récente", async () => {
  const current = page();
  const pending = [];
  current.context.api = () => new Promise((resolve) => pending.push(resolve));
  current.$("#review-start").value = "2026-10-13";
  current.$("#review-end").value = "2026-10-13";
  const first = vm.runInContext('reviewActive = true; refreshReview()', current.context);
  current.$("#review-start").value = "2026-10-14";
  current.$("#review-end").value = "2026-10-14";
  const second = vm.runInContext('refreshReview()', current.context);
  pending[1]({total: 0, results: []});
  await second;
  pending[0]({total: 1, results: [{id: 1, filename: "old.md"}]});
  await first;
  assert.equal(current.$("#review-results").children.length, 1);
  assert.match(current.$("#review-results").children[0].textContent, /Aucun fichier/);
});
