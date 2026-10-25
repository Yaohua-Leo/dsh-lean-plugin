/** Pure mode checks; runtime-policy.json is generated from harnesses.json. */
export function checkCapabilities(policy, names, projectMode) {
    const mode = policy.mode;
    const profile = policy.profiles[mode];
    if (!profile) throw new Error(`Unknown preset mode: ${mode}`);
    const present = new Set(names);
    const observed = {};
    const required = {};
    const missing = {};
    const forbidden = {};
    for (const server of ['lean-lsp', 'lean-beam']) {
        const prefix = `mcp__${server}__`;
        observed[server] = names.filter(n => n.startsWith(prefix)).sort();
        required[server] = profile.requiredTools[server].map(n => prefix + n);
        missing[server] = required[server].filter(n => !present.has(n));
        forbidden[server] = profile.activeServers.includes(server)
            ? profile.forbiddenTools[server].map(n => prefix + n).filter(n => present.has(n))
            : observed[server];
    }
    const modeMatches = projectMode === mode;
    let status = 'ready';
    if (Object.values(missing).some(v => v.length)) status = 'missing-required';
    else if (Object.values(forbidden).some(v => v.length)) status = 'forbidden-present';
    else if (!modeMatches) status = projectMode ? 'mode-mismatch' : 'project-mode-unknown';
    return {mode, modeMatches, status, ready: status === 'ready', observed, required, missing, forbidden};
}
