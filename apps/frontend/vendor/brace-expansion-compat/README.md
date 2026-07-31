# brace-expansion compatibility bridge

ESLint 9 and `eslint-config-next` still include consumers that load
`brace-expansion` through both the legacy CommonJS function API and the newer
named-export API. The local override forwards both interfaces to patched
`brace-expansion@5.0.9`, which includes the bounded-output fix for
GHSA-mh99-v99m-4gvg.

Remove this bridge when the complete ESLint/Next.js dependency tree consumes a
patched `brace-expansion` release directly. Until then, keep
`brace-expansion-upstream`, this package, and the root `overrides` entry on the
same patched version.
