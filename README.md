# PocketRights

An offline, domain-specialized Indian legal-information model — studied across
training method, model size, and compression.

A citizen asks an everyday legal question in plain language. The model answers
from its own weights, with real Act and Section citations, practical next steps,
caveats, and an explicit *information, not legal advice* notice. It refuses
questions outside its five supported domains, and asks for the user's state when
state law materially changes the answer.

**Research question:** how does aggressive quantization degrade citation
validity, numeric fidelity, critical omissions, hallucinated authority, and
refusal behaviour — relative to surface fluency?

📄 **[PROJECT.md](PROJECT.md)** is the full specification: architecture,
training design, quantization ladder, causal-inference plan, and the 74-task
build list.

---

## Status

Tasks 0–4 of 73 complete. Nothing has been fetched, trained, or measured yet.

| Task | | |
|---|---|---|
| 0 | Repo scaffold | ✅ |
| 1 | `docs/scope.md` + `scope.yaml` | ✅ draft — **needs review** |
| 2 | `docs/response-contract.md` + schema + GBNF | ✅ draft — **needs review** |
| 3 | `docs/sources.md` + `sources.yaml` | ✅ draft — **needs review** |
| 4 | `docs/preregistration.md` | ✅ draft — **needs review** |
| 5 | Cloud GPU setup | ⬜ next |

---

## Quick start

```bash
make setup     # create the venv, install all workspace packages
make test      # run the suite
make check     # lint + test
make help      # everything else
```

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12+.

---

## Layout

```
docs/          the contracts — scope, response format, sources, pre-registration
packages/      seven workspace packages, one per pipeline stage
data/          raw sources (append-only), statute store, datasets, benchmark
models/        adapters, merged weights, GGUF ladder
runs/          one directory per experiment; every paper number traces here
web/           the public demo
```

| Package | Role |
|---|---|
| `pr_corpus` | Source acquisition, provenance, hashing, dated snapshots |
| `pr_store` | Statute store, facts table, authorities table |
| `pr_verify` | Citation, numeric, authority, and scope verification |
| `pr_datagen` | Scenarios, teacher pipeline, repair loop, CPT corpus |
| `pr_eval` | Benchmark harness, metrics, statistics |
| `pr_train` | CPT and SFT; QLoRA / LoRA / full fine-tune |
| `pr_quant` | GGUF ladder, imatrix, AWQ, GPTQ |

---

## The documents are tested

`docs/scope.yaml`, `docs/sources.yaml`, and the response schema are not prose —
they are validated on every run. The suite enforces, among other things:

- category ids are unique, namespaced, and well-formed
- every `requires` resolves to a declared clarification trigger
- state-sensitive domains ask for the state, or opt out with a written reason
- the response schema rejects a refusal that carries citations, a clarification
  that half-answers, and a reworded disclaimer
- no employment source can advance past `planned` while the labour-regime
  determination is unresolved

That last one is the automated form of the project's biggest legal-correctness
risk. A test is a better guard than a note in a document.

---

## Disclaimer

PocketRights produces **general legal information, not legal advice.** It is a
research artifact. It does not establish a lawyer–client relationship, its legal
corpus is frozen at a stated snapshot date, and it should not be relied on for
any actual legal matter.

## Licence

Apache-2.0.
