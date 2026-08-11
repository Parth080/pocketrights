# PocketRights — Pre-Registration

**Status: DRAFT — must be frozen before task 42 (the first baseline evaluation).**

Once frozen, this document does not change. If analysis decisions change afterwards, they are reported as **exploratory**, in a clearly separated section of the paper.

| | |
|---|---|
| Version | 1.0 |
| Frozen at | *(not yet)* |
| Frozen by | *(not yet)* |
| Git SHA at freeze | *(not yet)* |

---

## 1. Why this exists

Every factor in this study is an intervention we **assign** — model size, training method, precision, which data slice is removed. Nothing is observed. That means causal effects are identified *by the design itself*, with no confounding to adjust for.

But that only holds if the analysis is specified before the data is seen. A hypothesis edited after looking at results is not a finding, and a "breakpoint" chosen by eye is not a measurement. This document is what makes the causal language in the paper legitimate.

---

## 2. Hypotheses

| ID | Hypothesis | Direction | Primary test |
|---|---|---|---|
| **H1** | Aggressive quantization degrades legal reliability *before* it degrades surface fluency | Reliability metrics decline at higher bits/weight than fluency does | Compare breakpoints: reliability composite vs fluency |
| **H2** | Numeric fidelity is more sensitive to compression than broad response quality | Steeper slope for numeric fidelity than for overall quality | `bits × metric` interaction in the GLMM |
| **H3** | Citation validity decreases at sufficiently aggressive quantization | Negative main effect of low bits on citation validity | Main effect of `bits`, primary endpoint |
| **H4** | Full fine-tuning beats LoRA/QLoRA on knowledge metrics by a **larger margin** than on behaviour metrics | Method effect is larger for citations/numbers than for refusal/format | `method × metric-class` interaction |
| **H5** | CPT→SFT beats SFT alone on knowledge metrics, but **costs** instruction-following | Positive on knowledge, negative on capability retention | Contrast `M-CPTSFT` vs `M-FULL`, both metric classes |
| **H6** | Larger models retain legal reliability further down the compression ladder | Breakpoint shifts to lower bits/weight as size increases | `size × bits` interaction |

**Every one of these can be disconfirmed, and a disconfirmed hypothesis will be reported as such.** H4 and H5 in particular are genuine predictions that could fail.

---

## 3. Endpoints

### Primary (2)

1. **Citation validity rate** — proportion of cited Act/Section pairs that exist in the statute store. Deterministic.
2. **Numeric fidelity rate** — proportion of `key_numbers` entries matching the verified facts table. Deterministic.

Both are deterministic on purpose. The primary endpoints must not depend on a judge model.

**Family-wise error control on primaries:** Holm–Bonferroni across the two, per hypothesis.

### Secondary (5)

3. Citation relevance *(judge)*
4. Critical-omission rate *(rubric + judge)*
5. Hallucinated-authority rate
6. Refusal calibration — out-of-scope recall and in-scope over-refusal, **reported separately, never averaged**
7. General capability retention — MMLU / IFEval slices

**Secondary family:** Benjamini–Hochberg FDR at q = 0.05.

### Control variable

**Fluency** — not an endpoint. It is the comparator for H1. If fluency degrades in step with reliability, H1 is disconfirmed.

---

## 4. Design

### Factors

| Factor | Levels | Type |
|---|---|---|
| `size` | 1.7B, **4B**, 8B, 14B | assigned |
| `method` | none, QLoRA, LoRA, full, CPT→SFT | assigned |
| `bits` | measured bits/weight of each rung | assigned, continuous |
| `quant_family` | K-quant, I-quant, AWQ, GPTQ | assigned, categorical |
| `grammar` | constrained, free | assigned |

Reference cell: **4B, QLoRA, bf16, constrained.**

### Units and repeated measures

The same 500 benchmark items appear in every cell. Items are the unit of analysis; cells are conditions. This is a fully crossed repeated-measures design.

### Randomisation and control

Nothing is randomised because nothing needs to be — all assignments are deliberate. What matters is that **only the named factor moves**:

| Threat | Control |
|---|---|
| Rank ablation changes effective LR (scaling is α/r) | Hold **α = 2r** |
| Removing a data slice also shrinks the dataset | **Resample to constant N** |
| Quant methods using different calibration data | **One shared calibration set** across imatrix, AWQ, GPTQ |
| Decoding variance | Greedy, temperature 0, fixed seed, fixed max tokens |
| Runtime variance | **One pinned llama.cpp commit** for every GGUF cell |
| Prompt drift | Byte-identical prompt template in every cell |
| Contract drift | Response contract version recorded per run; cross-version comparison forbidden |

### Noise floor

Three seeds at the reference cell (`M-QLORA`, `S-2`, `S-3`). **The observed seed spread is reported alongside every ablation delta.** Any effect smaller than the seed spread is reported as null regardless of its p-value.

---

## 5. Statistical model

Primary specification — generalised linear mixed model with item-level random intercepts:

```
outcome_ij ~ size + method + bits + size:bits + method:bits + (1 | item)
```

- **Binary outcomes** (citation valid, number correct, refusal correct): logistic GLMM
- **Continuous/graded outcomes**: linear GLMM
- `(1 | item)` absorbs item difficulty, which is what makes cross-cell comparison powerful

`bits` enters as **measured bits per weight** (file size ÷ parameter count), not as a rung label. Rung labels are used only for plotting.

### Pre-specified contrasts

| Contrast | Question |
|---|---|
| `method = none` vs `QLoRA` | Does training help at all? |
| `QLoRA` vs `LoRA` | Cost of the 4-bit frozen base |
| `LoRA` vs `full` | Cost of the low-rank constraint (**H4**) |
| `full` vs `CPT→SFT` | Value of raw-corpus pretraining (**H5**) |
| `bf16` vs `Q4_K_M` vs `IQ2_M` | The compression spine |
| `AWQ` vs `GPTQ` at matched bits | Do INT4 methods differ at equal bitwidth? |
| `constrained` vs `free` | Does structured decoding rescue low-bit models? |

### Dose–response

Segmented (piecewise) regression of each primary endpoint on measured bits/weight. **The reported quantity is the breakpoint with a bootstrap 95% CI**, not a visually chosen elbow.

Pre-specified: one breakpoint. If a two-breakpoint model fits materially better, that is reported as **exploratory**.

### Mediation

Total effect of compression on overall answer quality, decomposed through three pre-specified mediators:

1. numeric fidelity
2. citation validity
3. format/parse degradation *(free-decoding condition only — under grammar constraints it is structurally zero)*

This is the direct test of "what breaks first" (H1, H2).

### Heterogeneous effects

Pre-specified subgroups. Each is an interaction with `bits`, not a separate analysis:

- expected behaviour: `answer` / `clarify` / `refuse`
- domain: the five verticals
- question type: numeric-bearing vs purely explanatory
- input style: plain English / colloquial / romanized Hinglish
- difficulty tag

### Uncertainty

Bootstrap 95% CIs, 10,000 resamples, **resampled at the item level** to respect the repeated-measures structure. Paired comparisons across cells use the paired bootstrap.

---

## 6. Judge validity

Two secondary endpoints depend on a judge model, so the judge is treated as an instrument with measured error:

- Judge family **must differ** from the teacher family
- ~150 gold items human-labelled by the project author
- Report **Cohen's κ** and raw agreement, per endpoint
- **κ < 0.6 on an endpoint disqualifies that endpoint** from confirmatory claims; it moves to exploratory
- Judge model version and digest pinned and recorded; a mid-study change invalidates affected cells

---

## 7. Stopping and exclusion rules

Specified in advance so they cannot be chosen to suit the results.

**Cell exclusion.** A cell is excluded only if:
- the model fails to load or produce output for >5% of items, or
- a configuration error is discovered that makes it not the intended condition

Exclusions are listed in the paper with reasons. **A cell is never excluded for producing an unexpected result.**

**Item exclusion.** Items are excluded only if a post-hoc review finds the gold label itself wrong. Such items are removed from **every** cell simultaneously, and the count is reported.

**No optional stopping.** The full grid runs. We do not stop early because a pattern has emerged.

**No metric shopping.** The seven metrics in §3 are the complete list. Anything added later is exploratory and labelled as such.

---

## 8. Deviations

Any departure from this document after freeze gets logged here with date, reason, and whether it was made before or after seeing the affected results.

| Date | Deviation | Reason | Data seen first? |
|---|---|---|---|
| — | — | — | — |

---

## 9. What would falsify the project's central claim

Stated plainly, so it can happen:

The central claim is that **legal reliability degrades under compression before fluency does** (H1). It is falsified if the reliability composite and the fluency measure share a breakpoint whose confidence intervals overlap.

That outcome is publishable. It would mean that for this task, at this scale, surface fluency is an adequate proxy for legal reliability — which is directly contrary to the project's founding assumption, and worth knowing.
