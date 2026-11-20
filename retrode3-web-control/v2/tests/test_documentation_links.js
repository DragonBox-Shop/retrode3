/* Keep Help links on the released branch and user/developer CLI docs in sync. */
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const base = path.join(__dirname, "..");
const js = fs.readFileSync(path.join(base, "web", "assets", "app.js"), "utf8");
const php = fs.readFileSync(path.join(base, "web", "index.php"), "utf8");

assert(js.includes("blob/master/retrode3-web-control/v2/docs/"));
assert(!js.includes("blob/feature/web-control-v2/"));
assert(php.includes('id="help-online-link"'));
assert(php.includes('id="help-developer-link"'));
assert(php.includes("blob/master/retrode3-web-control/v2/docs/user-guide.en.md"));
assert(php.includes("blob/master/retrode3-web-control/v2/docs/developer-guide.en.md"));

for (const lang of ["de", "en"]) {
  const locales = JSON.parse(fs.readFileSync(
    path.join(base, "web", "locales", lang + ".json"), "utf8"));
  assert(locales.help_open_developer, lang + ": missing developer link translation");

  const guide = fs.readFileSync(
    path.join(base, "docs", "user-guide." + lang + ".md"), "utf8");
  const dev = fs.readFileSync(
    path.join(base, "docs", "developer-guide." + lang + ".md"), "utf8");
  assert(guide.includes("(developer-guide." + lang + ".md)"));
  assert(guide.includes("/usr/bin/retrode3-cli"));
  assert(dev.includes("--list-cores --protocol ndjson-v1"));
  assert(dev.includes("--action probe"));
  assert(dev.includes("--action read-rom"));
  assert(dev.includes("--interactive"));
  assert(!guide.includes("still being developed"), lang + ": stale Web v2 status");
  assert(!guide.includes("läuft noch"), lang + ": stale Web v2 status");
}
console.log("Web v2 user/developer documentation links passed");
