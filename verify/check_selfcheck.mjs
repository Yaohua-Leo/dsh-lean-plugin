// Real module execution against a mocked DSH service boundary, in both modes.
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, writeFileSync, cpSync, rmSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { join, dirname } from 'node:path';
const root = dirname(dirname(fileURLToPath(import.meta.url)));
const temp = mkdtempSync(join(root, '.lf-selfcheck-'));
let count = 0;
try {
  for (const mode of ['lsp-fallback', 'beam']) {
    const dir = join(temp, mode);
    cpSync(join(root, 'preset'), dir, { recursive: true });
    const policy = JSON.parse(readFileSync(join(dir, 'runtime-policy.json'), 'utf8'));
    policy.mode = mode;
    writeFileSync(join(dir, 'runtime-policy.json'), JSON.stringify(policy));
    const {apply} = await import(pathToFileURL(join(dir, 'index.js')));
    const names = Object.entries(policy.profiles[mode].requiredTools).flatMap(([server, tools]) => tools.map(n => `mcp__${server}__${n}`));
    async function run({tools=names, config={mode, library:'Example', targets:['Example.test']}, lock={targets:{'Example.test':{}}}, fsMissing=false}={}) {
      let registered;
      const ctx = {
        tools: {schemas: () => tools.map(name => ({name})), register: value => {registered=value;}},
        get: name => name === 'workingDirectory' ? {ensure: async () => '/project'} : fsMissing ? undefined : {
          resolve: async path => path, stat: async () => lock === undefined ? undefined : {},
          readText: async path => path === 'lean-formalization.json'
            ? (typeof config === 'string' ? config : JSON.stringify(config)) : JSON.stringify(lock),
        },
      };
      apply(ctx);
      const value = await registered.execute({}, {agent:{}});
      const schema = registered.output.schema;
      assert.deepEqual(Object.keys(value).sort(), Object.keys(schema.properties).sort());
      for (const [key, spec] of Object.entries(schema.properties)) {
        assert(spec.type === 'array' ? Array.isArray(value[key]) : spec.type === 'integer'
          ? Number.isInteger(value[key]) : typeof value[key] === spec.type, `${key} type`);
      }
      count++;
      return value;
    }
    let v = await run(); assert.equal(v.mcpReady, true); assert.equal(v.gateStatus, 'ready');
    assert(v.verdict.includes('does not itself'));
    v = await run({tools:names.slice(1)}); assert.equal(v.mcpStatus, 'missing-required');
    v = await run({tools:[...names, 'mcp__lean-lsp__lean_build']}); assert.equal(v.mcpStatus, 'forbidden-present');
    v = await run({config:{mode:mode==='beam'?'lsp-fallback':'beam',library:'X',targets:['X']}}); assert.equal(v.mcpStatus, 'mode-mismatch');
    for (const config of [null, [], 1, {}, '{broken']) {v=await run({config}); assert.equal(v.mcpReady, false); assert.notEqual(v.gateStatus,'ready');}
    v=await run({fsMissing:true}); assert.equal(v.gateStatus,'io-error');
    v=await run({lock:null}); assert.equal(v.gateStatus,'invalid-lock');
    if(mode==='lsp-fallback') {v=await run({tools:[...names,'mcp__lean-beam__lean_sync']}); assert.equal(v.mcpStatus,'forbidden-present');}
    else {v=await run({tools:[...names,'mcp__lean-lsp__lean_multi_attempt']}); assert.equal(v.mcpStatus,'forbidden-present');}
  }
  console.log(`PASS selfcheck: ${count} module executions, both modes, output schema and fail-closed errors`);
} finally { rmSync(temp, {recursive:true, force:true}); }
