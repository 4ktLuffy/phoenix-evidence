// Loads Phoenix's benchmark suites (js/benchmarks/evals-benchmarks/src/*.eval.ts) against stub
// modules, so no model is called, and records each suite's cases, labels and acceptance criteria.
//   PHOENIX=/path/to/phoenix node extract.mjs   (run via `npx tsx`; see README in this folder)
import fs from 'node:fs';
import path from 'node:path';
import { execSync } from 'node:child_process';
import { fileURLToPath, pathToFileURL } from 'node:url';
const here = path.dirname(fileURLToPath(import.meta.url));
const phoenix = process.env.PHOENIX;
if (!phoenix) throw new Error('set PHOENIX to a Phoenix checkout');
const work = path.join(here, '.work');
fs.rmSync(work, { recursive: true, force: true });
fs.mkdirSync(work);
fs.cpSync(path.join(phoenix, 'js/benchmarks/evals-benchmarks/src'), path.join(work, 'src'), { recursive: true });
fs.cpSync(path.join(here, 'stubs'), path.join(work, 'node_modules'), { recursive: true });
const commit = execSync('git rev-parse HEAD', { cwd: phoenix }).toString().trim();
globalThis.__OUT = [];
const files = fs.readdirSync(path.join(work, 'src')).filter((f) => f.endsWith('.eval.ts')).sort();
const suites = {};
for (const f of files) {
  const start = globalThis.__OUT.length;
  await import(pathToFileURL(path.join(work, 'src', f)).href);
  globalThis.__INPUTS ??= {};
  for (const b of globalThis.__OUT.slice(start)) {
    globalThis.__INPUTS[f] = b.cases.map((c) => c.input);
    suites[f] = {
      suite: b.suite,
      truth: b.cases.map((c) => c.expected?.label),
      categories: b.cases.map((c) => c.metadata?.category ?? null),
      criteria: b.opts?.acceptanceCriteria ?? [],
    };
  }
}
fs.writeFileSync(path.join(here, 'suites.json'), JSON.stringify({ phoenix_commit: commit, suites }, null, 1));
// Case inputs are Phoenix's own benchmark text: kept out of the repository (gitignored) and
// regenerated from a Phoenix checkout by this script.
const inputs = {};
for (const f of files) inputs[f] = (globalThis.__INPUTS[f] ?? []);
fs.writeFileSync(path.join(here, 'suites.inputs.json'), JSON.stringify({ phoenix_commit: commit, inputs }, null, 1));
for (const [f, s] of Object.entries(suites)) console.log(f, s.truth.length, JSON.stringify(s.criteria.map((c) => `${c.annotationName}>=${c.threshold}`)));
fs.rmSync(work, { recursive: true, force: true });
