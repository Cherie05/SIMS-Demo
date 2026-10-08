// Performance budget for the production bundle (run after `npm run build`; CI fails on a regression).
// Sizes are gzip-compressed, which is what browsers download.
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { gzipSync } from 'node:zlib';

const BUDGET_KB = {
  entry: 80, // index-*.js: what every first visit downloads before the sign-in page renders
  largestChunk: 160,
  totalJs: 520,
  totalCss: 20,
};

const dir = join(process.cwd(), 'dist', 'assets');
const files = readdirSync(dir).map((name) => {
  const gz = gzipSync(readFileSync(join(dir, name))).length;
  return { name, kb: gz / 1024 };
});
const js = files.filter((f) => f.name.endsWith('.js'));
const css = files.filter((f) => f.name.endsWith('.css'));
const entry = js.filter((f) => f.name.startsWith('index-'));

const measured = {
  entry: Math.max(0, ...entry.map((f) => f.kb)),
  largestChunk: Math.max(0, ...js.map((f) => f.kb)),
  totalJs: js.reduce((sum, f) => sum + f.kb, 0),
  totalCss: css.reduce((sum, f) => sum + f.kb, 0),
};

let failed = false;
for (const [key, limit] of Object.entries(BUDGET_KB)) {
  const value = measured[key];
  const ok = value <= limit;
  failed ||= !ok;
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${key.padEnd(13)} ${value.toFixed(1).padStart(7)} KB gz  (budget ${limit} KB)`);
}
console.log('\nLargest chunks:');
for (const f of [...js].sort((a, b) => b.kb - a.kb).slice(0, 6))
  console.log(`  ${f.kb.toFixed(1).padStart(6)} KB  ${f.name}`);
process.exit(failed ? 1 : 0);
