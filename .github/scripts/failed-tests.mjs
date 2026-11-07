// Names of the failing tests in a node:test JUnit report, one per line.
// Used by run-screens.sh to retry a failed test once. Usage: node failed-tests.mjs <report.xml>
import { readFileSync } from "node:fs";

const unescape = (s) =>
  s.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&apos;/g, "'").replace(/&amp;/g, "&");

const xml = readFileSync(process.argv[2], "utf8");
const names = new Set();
for (const m of xml.matchAll(/<testcase name="([^"]*)"[^>]*?(\/>|>([\s\S]*?)<\/testcase>)/g)) {
  if (m[3] && /<failure[\s>]/.test(m[3])) names.add(unescape(m[1]));
}
console.log([...names].join("\n"));
