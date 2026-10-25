/**
 * lean_selfcheck — assert this session's Lean capability instead of assuming it.
 *
 * The check is intentionally fail-closed: a partial or silently missing MCP
 * composition is not a Lean session, and a missing/corrupt project gate is not
 * proof acceptance.
 */

import { readFileSync } from 'node:fs';
import { checkCapabilities } from './capabilities.js';

const policy = JSON.parse(readFileSync(new URL('./runtime-policy.json', import.meta.url), 'utf8'));
const name = 'lean-selfcheck';
const inject = ['tools'];

function errorText(error) {
    const text = error instanceof Error ? error.message : String(error);
    return text.slice(0, 500);
}

function apply(ctx) {
    ctx.tools.register({
        name: 'lean_selfcheck',
        description:
            'Fail-closed check of the Lean preset: exact required/forbidden MCP tools, ' +
            'and the current workspace gate state. Call at the start of Lean work and ' +
            'whenever a Lean tool is missing; never claim proof acceptance from a partial result.',
        parameters: {},
        output: {
            schema: {
                type: 'object',
                additionalProperties: false,
                properties: {
                    cwd: { type: 'string' },
                    presetMode: { type: 'string' },
                    modeMatches: { type: 'boolean' },
                    beamSourceCommit: { type: 'string' },
                    mcpStatus: { type: 'string' },
                    mcpReady: { type: 'boolean' },
                    leanLspTools: { type: 'integer' },
                    leanBeamTools: { type: 'integer' },
                    leanLspNames: { type: 'array', items: { type: 'string' } },
                    leanBeamNames: { type: 'array', items: { type: 'string' } },
                    requiredLspTools: { type: 'array', items: { type: 'string' } },
                    missingLspTools: { type: 'array', items: { type: 'string' } },
                    forbiddenLspTools: { type: 'array', items: { type: 'string' } },
                    requiredBeamTools: { type: 'array', items: { type: 'string' } },
                    missingBeamTools: { type: 'array', items: { type: 'string' } },
                    forbiddenBeamTools: { type: 'array', items: { type: 'string' } },
                    gatePresent: { type: 'boolean' },
                    gateStatus: { type: 'string' },
                    gateErrorCode: { type: 'string' },
                    gateError: { type: 'string' },
                    gateLibrary: { type: 'string' },
                    gateMode: { type: 'string' },
                    gateTargets: { type: 'integer' },
                    gateLockFile: { type: 'string' },
                    lockPresent: { type: 'boolean' },
                    verdict: { type: 'string' },
                },
                required: [
                    'cwd', 'presetMode', 'modeMatches', 'beamSourceCommit',
                    'mcpStatus', 'mcpReady', 'leanLspTools', 'leanBeamTools',
                    'leanLspNames', 'leanBeamNames', 'requiredLspTools', 'missingLspTools',
                    'forbiddenLspTools', 'gatePresent', 'gateStatus', 'gateErrorCode',
                    'requiredBeamTools', 'missingBeamTools', 'forbiddenBeamTools',
                    'gateError', 'gateLibrary', 'gateMode', 'gateTargets', 'gateLockFile',
                    'lockPresent', 'verdict',
                ],
            },
            render: (_args, value) => [{ type: 'text', text: JSON.stringify(value, null, 2) }],
        },
        async execute(_args, exec) {
            const schemas = ctx.tools.schemas(exec.agent);
            const names = schemas.map((tool) => tool.name).sort();

            let cwd = '';
            try {
                const workingDirectory = ctx.get('workingDirectory');
                if (workingDirectory) cwd = (await workingDirectory.ensure(exec.agent, exec.signal)) ?? '';
            } catch {
                cwd = '';
            }

            let gatePresent = false;
            let gateStatus = 'missing';
            let gateErrorCode = '';
            let gateError = '';
            let gateLibrary = '';
            let gateMode = '';
            let gateTargets = 0;
            let gateLockFile = 'locked-targets.json';
            let lockPresent = false;
            const fs = ctx.get('fs');

            const failGate = (status, code, error = '') => {
                gateStatus = status;
                gateErrorCode = code;
                gateError = errorText(error);
            };

            if (!cwd) {
                failGate('cwd-error', 'working-directory-unavailable');
            } else if (!fs) {
                failGate('io-error', 'filesystem-service-unavailable');
            } else {
                let configTarget;
                try {
                    configTarget = await fs.resolve('lean-formalization.json', { cwd, signal: exec.signal });
                } catch (error) {
                    failGate('io-error', 'config-resolve-failed', error);
                }
                if (configTarget && gateStatus === 'missing') {
                    let raw;
                    try {
                        raw = await fs.readText(configTarget, exec.signal);
                    } catch (error) {
                        failGate('missing', 'config-missing', error);
                    }
                    if (raw !== undefined && gateStatus === 'missing') {
                        let cfg;
                        try {
                            cfg = JSON.parse(raw);
                        } catch (error) {
                            failGate('invalid-json', 'config-invalid-json', error);
                        }
                        if (cfg !== undefined && gateStatus === 'missing') {
                            gatePresent = true;
                            gateLibrary = typeof cfg?.library === 'string' ? cfg.library : '';
                            gateMode = typeof cfg?.mode === 'string' ? cfg.mode : '';
                            gateTargets = Array.isArray(cfg?.targets) ? cfg.targets.length : 0;
                            gateLockFile = typeof cfg?.lockFile === 'string' && cfg.lockFile
                                ? cfg.lockFile : 'locked-targets.json';
                            if (!cfg || typeof cfg !== 'object' || Array.isArray(cfg) ||
                                !gateLibrary || !Array.isArray(cfg.targets)) {
                                failGate('invalid-schema', 'config-invalid-schema');
                            } else if (gateTargets === 0) {
                                failGate('empty-targets', 'config-empty-targets');
                            } else {
                                let lockTarget;
                                try {
                                    lockTarget = await fs.resolve(gateLockFile, { cwd, signal: exec.signal });
                                    const lockStat = await fs.stat(lockTarget, exec.signal);
                                    lockPresent = lockStat !== undefined && lockStat !== null;
                                } catch (error) {
                                    failGate('io-error', 'lock-stat-failed', error);
                                }
                                if (gateStatus === 'missing' && !lockPresent) {
                                    failGate('lock-missing', 'lock-file-missing');
                                } else if (gateStatus === 'missing') {
                                    try {
                                        const lockRaw = await fs.readText(lockTarget, exec.signal);
                                        const lock = JSON.parse(lockRaw);
                                        if (!lock || typeof lock !== 'object' || !lock.targets ||
                                            typeof lock.targets !== 'object') {
                                            failGate('invalid-lock', 'lock-invalid-schema');
                                        } else {
                                            gateStatus = 'ready';
                                        }
                                    } catch (error) {
                                        failGate('invalid-lock', 'lock-invalid-json', error);
                                    }
                                }
                            }
                        }
                    }
                }
            }

            const surface = checkCapabilities(policy, names, gateMode);
            const {mode: presetMode, modeMatches, status: mcpStatus, ready: mcpReady} = surface;
            const leanLspNames = surface.observed['lean-lsp'];
            const leanBeamNames = surface.observed['lean-beam'];
            const missingLspTools = surface.missing['lean-lsp'];
            const forbiddenLspTools = surface.forbidden['lean-lsp'];
            const requiredBeamTools = surface.required['lean-beam'];
            const missingBeamTools = surface.missing['lean-beam'];
            const forbiddenBeamTools = surface.forbidden['lean-beam'];
            let verdict;
            if (!mcpReady) {
                verdict =
                    `LEAN MCP IS NOT READY (${mcpStatus}); preset=${presetMode}, project=${gateMode || '(unknown)'}. ` +
                    `Missing=${[...missingLspTools, ...missingBeamTools].join(', ') || '(none)'}; ` +
                    `forbidden-present=${[...forbiddenLspTools, ...forbiddenBeamTools].join(', ') || '(none)'}. Stop and report the ` +
                    'missing capability; do not emulate proof state, diagnostics or build results.';
            } else if (gateStatus !== 'ready') {
                verdict =
                    `Lean MCP is ready (lean-lsp=${leanLspNames.length}, lean-beam=${leanBeamNames.length}), ` +
                    `but acceptance gate status is ${gateStatus} (${gateErrorCode || 'none'}). ` +
                    'Acceptance is unknown/blocked until the project gate passes.';
            } else {
                verdict =
                    `Lean MCP is ready (lean-lsp=${leanLspNames.length}, lean-beam=${leanBeamNames.length}); ` +
                    `gate library=${gateLibrary}, mode=${gateMode || '(unset)'}, targets=${gateTargets}, ` +
                    `lock=${gateLockFile}. Run the deterministic leancheck and independent semantic review; ` +
                    'this catalog check does not itself establish project sync compatibility or certify a proof.';
            }

            return {
                cwd, presetMode, modeMatches, beamSourceCommit: policy.beamSourceCommit, mcpStatus, mcpReady,
                leanLspTools: leanLspNames.length,
                leanBeamTools: leanBeamNames.length,
                leanLspNames, leanBeamNames,
                requiredLspTools: surface.required['lean-lsp'],
                missingLspTools, forbiddenLspTools,
                requiredBeamTools, missingBeamTools, forbiddenBeamTools,
                gatePresent, gateStatus, gateErrorCode, gateError,
                gateLibrary, gateMode, gateTargets, gateLockFile, lockPresent,
                verdict,
            };
        },
    });
}

export { apply, inject, name };
