// Check the actual public package boundary and resource resolution.
import assert from 'node:assert/strict';
import {readFileSync,existsSync} from 'node:fs';
import {createRequire} from 'node:module';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {dirname,join,resolve} from 'node:path';
const root=process.argv[2] ? resolve(process.argv[2]) : resolve(dirname(fileURLToPath(import.meta.url)),'..');
const pkg=JSON.parse(readFileSync(join(root,'package.json'),'utf8'));
const nested=JSON.parse(readFileSync(join(root,'preset/package.json'),'utf8'));
assert.equal(pkg.name,'@local/dsh-lean-preset');
assert.equal(pkg.version,nested.version);
assert.equal(pkg.dsh.bundle.patch,'./preset/cordis.patch.yml');
assert.equal(pkg.exports['.'],'./preset/index.js');
assert(pkg.engines.dsh);
const sourcePolicy=JSON.parse(readFileSync(join(root,'harnesses.json'),'utf8'));
assert(readFileSync(join(root,'NOTICE'),'utf8').includes(sourcePolicy.skills.beam.commit));
for(const hook of ['prepare','preinstall','install','postinstall'])assert(!pkg.scripts?.[hook]);
const patch=readFileSync(join(root,'preset/cordis.patch.yml'),'utf8');
const expression=patch.match(/customSkillDirs:\s*\n\s*- !!js "([^\n]+)"/)?.[1];
assert(expression,'skill directory expression missing');
for(const anchor of ['package.json','preset/package.json']){
  const url=pathToFileURL(join(root,anchor)).href;
  const req=createRequire(url);
  const main=req.resolve(pkg.name);
  assert.equal(main,join(root,'preset/index.js'));
  const skillRoot=new Function('baseUrl',`return ${expression}`)(url);
  assert.equal(skillRoot,join(root,'preset/skills'));
  assert(existsSync(join(skillRoot,'lean-formalization/SKILL.md')));
  const policy=JSON.parse(readFileSync(join(dirname(main),'runtime-policy.json'),'utf8'));
  assert.equal(policy.mode,'lsp-fallback');
  assert(!existsSync(join(skillRoot,'lean-beam')));
  const module=await import(pathToFileURL(main));
  assert.equal(typeof module.apply,'function');
}
console.log('PASS public package: root/nested resolution, isolated skills, ESM entry, no install hooks');
