const out = globalThis.__OUT;
const test = (..._a) => {};
test.each = (cases) => (..._a) => { out.push({cases}); };
export { test };
export const describe = (name, fn, opts) => { const start = out.length; fn(); for (const o of out.slice(start)) { o.suite = name; o.opts = opts; } };
export const logOutput=()=>{}, logAnnotation=()=>{}, evaluate=async()=>{};
