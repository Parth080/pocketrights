# contracts/

**Everything in this folder is read by code and is version-controlled.**

`docs/` — the human-readable narrative that explains these files — is deliberately
kept out of git. This folder holds only what the pipeline and the test suite
actually load, plus the one document whose scientific value *is* its commit
history.

| File | Read by | Role |
|---|---|---|
| `scope.yaml` | scenario generator, verifier, benchmark stratification, `tests/test_scope.py` | **The source of truth for what PocketRights answers.** 47 categories, clarification triggers, out-of-scope classes, behaviour mix. |
| `sources.yaml` | `pr_corpus` acquisition, `tests/test_sources.py` | The legal source registry, acquisition policy, and the labour-regime blocking gate. |
| `schemas/response.schema.json` | verifier, teacher pipeline, eval harness | The response contract. The authority on answer shape. |
| `schemas/response.gbnf` | llama.cpp at decode time | The same contract as a decoding grammar. |
| `schemas/examples/*.json` | `tests/test_response_contract.py` | One worked example per behaviour. |
| `preregistration.md` | humans, and the paper | Hypotheses and the analysis plan. **Must be committed before task 42.** |

## Why `preregistration.md` lives here and not in `docs/`

Its entire function is to prove that the hypotheses and the statistical plan were
fixed *before* any results were seen. That proof is the commit timestamp. An
uncommitted pre-registration is not a pre-registration.

## Change discipline

- **Category ids in `scope.yaml` are permanent.** Add and deprecate; never rename.
  Everything downstream keys off them.
- **`scope.yaml` must reach `status: frozen` before task 25.**
- **`preregistration.md` must be frozen before task 42.** After that, deviations
  get logged in its own deviations table rather than edited in place.
- **The response schema is versioned by `$id`.** Bump to a new version file
  rather than changing an existing one — old runs must stay interpretable.

## Validation

```bash
make docs-check     # validates all three contracts
make test           # the full suite
```
