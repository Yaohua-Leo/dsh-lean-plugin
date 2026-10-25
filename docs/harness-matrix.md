# Harness integration

The public entry point of this repository is the DSH bundle in the root
`package.json`. It mounts the `lean` agent preset from `preset/cordis.patch.yml`
and the `lean_selfcheck` module from `preset/index.js`.

DSH Desktop 0.2.1-rc.2 is the observed host. The declared compatibility range is
`>=0.2.1-rc.2 <0.3.0`; other releases in that range are not individually tested.

For Desktop, use Plugin Manager and start a new session after installing.
The reserved Desktop profile is owned by Desktop and cannot be inspected using
CLI `--dump-config`. A separate CLI profile can use:

```sh
dsh plugin --profile lean-demo add github:Yaohua-Leo/dsh-lean-plugin#v1.1.0
dsh --profile lean-demo --dump-config
```

The inherited `harnesses.json` and generic installer also describe other Lean
assistant harnesses. They are retained for gate scaffolding and source
compatibility; this public release is a DSH plugin, and does not claim live
validation of those other hosts.

References: [DSH bundle and GitHub installation](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/develop/basic/publish.md),
[profile loading](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/boot/app-boot/README.md).
