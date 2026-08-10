# PocketRights — Project Specification & Build Plan

**Status:** v1.0 · Scope locked · Nothing built yet
**Source:** derived from `PocketRights.pdf` (Complete Project Specification, 17pp), then revised through design discussion
**Supersedes:** `ROADMAP.md` (stale — that version assumed a RAG architecture and an Android target, both since dropped)

---

## Table of contents

1. [What this project is](#1-what-this-project-is)
2. [Research question and hypotheses](#2-research-question-and-hypotheses)
3. [Scope](#3-scope)
4. [Architecture — closed-book](#4-architecture--closed-book)
5. [Training — every type, explained](#5-training--every-type-explained)
6. [Quantization — every type, explained](#6-quantization--every-type-explained)
7. [The experimental grid](#7-the-experimental-grid)
8. [Evaluation metrics](#8-evaluation-metrics)
9. [Causal inference and statistics](#9-causal-inference-and-statistics)
10. [Tech stack](#10-tech-stack)
11. [Repository structure](#11-repository-structure)
12. [Hardware and cost](#12-hardware-and-cost)
13. [The task list (0–73)](#13-the-task-list-073)
14. [Risks](#14-risks)
15. [Open decisions](#15-open-decisions)
16. [Definition of done](#16-definition-of-done)

---

## 1. What this project is

**PocketRights is a domain-specialized Indian legal-information model, studied across three axes: training method, model size, and compression.**

A citizen asks an everyday legal question in plain language. The model answers from its own weights — no retrieval, no internet — with real Act and Section citations, practical next steps, caveats, and an explicit "information, not legal advice" notice. It refuses questions outside its five supported domains, and asks for the user's state when state law materially changes the answer.

The project has two halves:

**The engineering half** — build a legal corpus with provenance, a section-level statute store, a verified table of critical numbers, a synthetic training dataset that passes mechanical verification, a specialized model, a full quantization ladder, and a public website where anyone can try it.

**The research half** — measure what happens to *legal reliability* as that model is compressed, and attribute the changes causally to specific interventions through a controlled factorial design.

### The three things being built

| | What | Why it exists |
|---|---|---|
| **The knowledge layer** | Indian statutory text stored section-by-section with dates and provenance, plus a table of every critical number | Grading infrastructure. Lets us mechanically check whether a citation exists and whether a number is right. |
| **The model** | A small instruct model taught to answer legal questions from its own weights | The object of study |
| **The measurement instrument** | A fixed 500-question benchmark and a scoring harness that measures legal reliability separately from fluency | Makes the research claims falsifiable |

### The core principle

> A language model can produce a legally plausible answer while being wrong about a section number, a monetary threshold, a deadline, a fine, an authority, or the current legal regime. **Surface fluency cannot be the success criterion.**

Everything in this design follows from that. The model generates language; the statute store provides ground truth; a deterministic verifier checks claims. The model is never the judge of its own facts.

---

## 2. Research question and hypotheses

### Primary research question

> How does aggressive quantization degrade citation validity, citation relevance, numeric fidelity, critical omissions, hallucinated legal authority, and refusal behaviour — relative to surface-level fluency?

### Secondary questions

- **Method:** Does full fine-tuning inject legal knowledge better than low-rank adaptation?
- **Knowledge injection:** Does continued pretraining on raw statute text beat learning through question-answer pairs alone?
- **Scale:** How much legal knowledge does model size actually buy?
- **Interaction:** Does compression damage large models differently from small ones?

### Pre-registered hypotheses

| ID | Hypothesis |
|---|---|
| **H1** | Aggressive quantization degrades legal reliability *before* obvious surface-fluency degradation |
| **H2** | Numeric fidelity is more sensitive to aggressive compression than broad response quality |
| **H3** | Citation reliability decreases at sufficiently aggressive quantization levels |
| **H4** | Full fine-tuning outperforms LoRA/QLoRA on knowledge-heavy metrics (citations, numbers) by a larger margin than on behaviour metrics (refusal, format) |
| **H5** | Continued pretraining followed by SFT beats SFT alone on knowledge metrics, but costs instruction-following ability |
| **H6** | Larger models retain legal reliability further down the compression ladder than smaller ones |

These are hypotheses to test, not conclusions to force. A disconfirmed hypothesis is a valuable result if the experiment is controlled and reproducible. **They are written down before the sweep runs** — see `docs/preregistration.md` (task 4).

---

## 3. Scope

### Supported domains — frozen

| Domain | Covers |
|---|---|
| **Consumer / e-commerce** | Everyday disputes involving products, refunds, deficiencies, unfair trade practices |
| **Tenancy** | Basic landlord/tenant questions, with explicit state-law caveats |
| **Traffic** | Everyday fines and rules under the central framework and applicable notifications |
| **Salary / PF / gratuity** | Everyday employment-payment and benefits questions, subject to the regime in force |
| **Insurance** | Policyholder protection and grievance/escalation questions |

### Out of scope — trained and evaluated as refusals

Criminal matters · family law · property-title disputes · immigration · complex litigation strategy · anything requiring individualized representation by a qualified lawyer.

**A correct refusal is preferable to a confident hallucination.** Out-of-scope behaviour is 15% of the training data and has its own metric.

### Scope drift

The product must not gradually become a general legal adviser through prompt interpretation alone. Expanding scope is a deliberate new project version with new sources and a new benchmark — not an incremental change.

---

## 4. Architecture — closed-book

**The model answers from its own weights. There is no retrieval at inference time.**

```
user question
     │
     ▼
  the model                    ← all legal knowledge lives here, in the weights
     │
     ▼
 structured JSON answer
     │
     ▼
  verifier                     ← checks the answer against the statute store
     │
     ▼
  final answer
```

### What the statute store is for

The statute database still exists and is still essential — but it never enters a prompt. Its three jobs:

1. **Grounding the teacher** when generating training data
2. **Grading** — checking whether cited sections exist and whether numbers are right
3. **Source display** on the website — clicking a citation shows the real section text

### Why closed-book

This was a deliberate choice over the RAG design in the original spec. With retrieval in the loop, the corpus props the model up and you cannot tell whether the weights or the prompt are carrying the answer. Closed-book measures **pure parametric legal knowledge** against the compression axis. Cleaner experiment, sharper result.

### The response contract

Every answer is a strict JSON object, enforced at decode time by a GBNF grammar:

```json
{
  "in_scope": true,
  "needs_clarification": false,
  "clarifying_question": null,
  "answer_summary": "...",
  "what_the_law_says": "...",
  "citations": [{"act": "Consumer Protection Act, 2019", "section": "69", "supports": "..."}],
  "key_numbers": [{"claim": "...", "value": 2, "unit": "years"}],
  "next_steps": ["..."],
  "caveats": ["..."],
  "escalation": {"authority": "...", "route": "..."},
  "disclaimer": "Information, not legal advice."
}
```

**Why strict JSON rather than prose:**

- The verifier reads citations and numbers **structurally**, not by regex-scraping prose. This removes an entire class of measurement error from the headline metrics.
- GBNF grammar constrains the sampler at every token to only those that keep the output valid. Malformed output is not unlikely — it is **impossible**. This matters most at IQ2, where an unconstrained model starts producing broken structure. Format collapse can never masquerade as reliability collapse.
- **Caveat:** grammar constraints could *mask* degradation. So every rung is evaluated **both** constrained and unconstrained, and "does structured decoding rescue low-bit models?" becomes an additional finding.

---

## 5. Training — every type, explained

### The two independent questions

Every training decision is two separate questions. Confusing them is the main source of muddle.

**Question 1 — what does it learn from?** → CPT, SFT, DPO
**Question 2 — how much of the model do you update?** → Full, LoRA, QLoRA

These are independent axes. Any combination is valid.

```
                    │ Full FT │  LoRA  │ QLoRA
────────────────────┼─────────┼────────┼───────
CPT (raw text)      │    ✓    │   ✓    │   ✓
SFT (Q→A pairs)     │    ✓    │   ✓    │   ✓
DPO (preferences)   │    ✓    │   ✓    │   ✓     ← excluded from this project
```

---

### 5.1 Question 1 — what it learns from

#### Pretraining

Feed the model the internet, predict the next token. This is how the base model was made — millions of dollars, trillions of tokens. **We do not do this.** We start from a finished base model.

#### CPT — Continued Pretraining

**The same objective as pretraining, but starting from a finished model and using only domain text.**

Raw statute text with no questions attached:

> *"69. Limitation period.—(1) The District Commission, the State Commission or the National Commission shall not admit a complaint unless it is filed within two years from the date on which the cause of action has arisen."*

The model learns to predict each next token. No format, no instructions, no answers. **It is reading the law book cover to cover.**

- **Teaches:** knowledge — facts, phrasing, section numbers, statutory language
- **Does not teach:** how to answer a question. After CPT alone, asking "what's the limitation period?" will likely produce more statute-sounding text rather than an answer.
- **Risk:** catastrophic forgetting — the model gets worse at general instruction-following. Mitigations: mix general text into the CPT corpus, low learning rate, 1–2 epochs only.

#### SFT — Supervised Fine-Tuning

Train on **(question, answer) pairs**.

- **Teaches:** behaviour — answer format, citation style, when to refuse, when to ask for state, how to be concise
- **Teaches less well:** deep knowledge. It learns specific Q→A mappings more readily than the underlying material.

#### The one mechanical difference between CPT and SFT

**The loss mask.**

- CPT: loss on **every token**
- SFT: loss on **the response tokens only** — the model is never rewarded for predicting the question

Same objective function. Different mask. That is genuinely the whole difference.

#### DPO / RLHF — preference optimization

Train on (prompt, better answer, worse answer) triplets. Teaches taste and alignment.

**Excluded from this project.** Reserved for the separate RLHF project. Including it would confound the compression study with an alignment study.

---

### 5.2 Question 2 — how much you update

| Method | What happens | Memory (4B) | Speed | Knowledge absorption |
|---|---|---|---|---|
| **Full fine-tune** | All 4 billion weights change | ~30 GB | Slowest | **Best** |
| **LoRA** | Base frozen at 16-bit. Train small low-rank matrices bolted onto each layer — ~30M params instead of 4B | ~12 GB | Fast | Good for style, **weaker for facts** |
| **QLoRA** | Same as LoRA, but the frozen base is compressed to 4-bit (NF4) to save memory | ~7 GB | Fast | As LoRA, plus a small quality cost from the 4-bit base |

Other parameter-efficient methods exist — DoRA, IA³, prefix tuning — all variations on "train a small piece." Not worth separate arms.

**Why this axis matters so much here.** LoRA is very good at teaching *behaviour* and noticeably weaker at *injecting new facts* — a low-rank update has less room to store new information. Since this project is closed-book, **facts are the whole game.** The full-FT-vs-LoRA comparison is therefore a central result, not a footnote. That is hypothesis H4.

---

### 5.3 The five method arms

Each arm changes exactly one thing from the arm above it.

| # | Arm | What it is | The comparison it enables |
|---|---|---|---|
| 1 | **Base, zero-shot** | No training at all | The control — does any of this help? |
| 2 | **QLoRA SFT** | Adapters, 4-bit frozen base | *vs 1:* does training help? |
| 3 | **LoRA SFT** | Adapters, 16-bit frozen base | *vs 2:* what does the 4-bit base cost? |
| 4 | **Full FT SFT** | All weights updated | *vs 3:* what does the low-rank constraint cost? **(H4)** |
| 5 | **CPT → SFT** | Read the raw corpus, then learn to answer | *vs 4:* does reading the law book beat practice problems? **(H5)** |

---

### 5.4 The 18 training runs

Not a full cross product — a pruned design where each block isolates one factor.

| Block | Runs | IDs | Purpose |
|---|---|---|---|
| **Method comparison** at 4B | 4 | `M-QLORA` `M-LORA` `M-FULL` `M-CPTSFT` | The five arms (base is free — no training) |
| **Seed replicates** at the reference cell | 2 | `S-2` `S-3` | **The noise floor.** Nothing else is interpretable without it. |
| **Scaling axis** (QLoRA) | 3 | `Z-1.7B` `Z-8B` `Z-14B` | Does legal knowledge need size? (H6) |
| **Data ablations** at 4B QLoRA | 5 | `D-NOREFUSE` `D-NOCLARIFY` `D-NOCITE` `D-25PCT` `D-50PCT` | Which data slices cause which behaviours |
| **Rank ablation** at 4B QLoRA | 2 | `R-8` `R-32` | How much adaptation capacity is needed |
| **Production retrain** | 1 | `RF` | The shipped model — train + dev, frozen winning recipe |
| **Total** | **18** | | |

#### Baseline recipe (the reference cell, `M-QLORA`)

| Setting | Value |
|---|---|
| Base model | Qwen3-4B-Instruct-2507 |
| Quantization during training | NF4, double quant, bf16 compute |
| LoRA rank / alpha / dropout | 16 / 32 / 0.05 |
| Target modules | All attention + MLP projections |
| Sequence length | To be set from measured pilot token distributions |
| Effective batch | ~32 via gradient accumulation |
| Learning rate | 1e-4 – 2e-4, cosine, ~3% warmup |
| Epochs | 2–3 |
| Loss | Cross-entropy, **masked to response tokens only** |
| Gradient checkpointing | On |
| Packing | Off initially |

#### Reproducibility rules for the grid

- Same seed, same data order, same eval protocol. Only the ablated factor moves.
- **Hold α = 2r across the rank sweep.** LoRA scaling is α/r, so a fixed α turns a rank ablation into a secret learning-rate ablation.
- **When removing a data slice, resample to hold total example count constant.** Otherwise the ablation is confounded with dataset size.
- Log every run's full config, git SHA, and dataset hash into `runs/<run_id>/config.json`.
- Report the seed spread alongside every ablation delta.

---

### 5.5 Where the training data comes from — the teacher

To fine-tune with SFT you need (question, answer) pairs — tens of thousands of them. Writing 100,000 answers by hand is roughly 16,000 hours of work, and no dataset of everyday Indian legal questions in our JSON format exists. So a larger model writes them. Big model teaches small model — hence "teacher".

**One teacher call:**

```
INSTRUCTIONS:  You are writing training data. Answer in this exact JSON format...
SCENARIO:      "flipkart sent me a cracked phone and won't refund, ordered 3 weeks ago"
RELEVANT LAW:  Consumer Protection Act, 2019 — s.2(11): "deficiency means any fault..."
               s.35: [full text] · s.69: [full text]
               E-Commerce Rules, 2020 — r.6: [full text]
       ↓
{"answer_summary": "...", "citations": [...], "next_steps": [...], ...}
```

That is one training example. Repeat ~50,000 times.

Three properties that matter:

1. **The teacher is never trained.** Rented through an API, used, discarded. It is a writing tool, not part of the system. Note this is *data generation*, **not distillation** — we never touch the teacher's logits or probability distributions.
2. **The teacher is grounded.** We paste real statute text into its prompt. It is not answering from memory, even though the model we train will have to.
3. **The teacher is not trusted.** Every output passes through the verifier. Failures are repaired or discarded.

> **The analogy:** you hire a senior lawyer to write 50,000 practice answers. A fact-checker verifies each one against the actual law books. The survivors become the textbook your junior studies from.

#### Not every example needs a teacher

This is the single largest cost lever in the project.

| Type | Example | Cost |
|---|---|---|
| **Programmatic** — SQL + template | *"What does Section 69 of the Consumer Protection Act, 2019 say?"* → text straight from the database. Also cloze, reverse recall, numeric recall. | **free** |
| **Teacher-generated** | *"flipkart sent me a cracked phone and won't refund"* → requires legal reasoning, plain-English translation, practical next steps | ~$0.0016 each |

The knowledge-injection types from task 27 are almost entirely programmatic — and they are the ones that actually push law into the weights. At 60% programmatic you pay for 40k teacher calls; at 20% you pay for 80k. **That ratio is a 2× swing on the largest line in the budget.**

### 5.6 Teacher and judge are not equally important

**Teacher errors get caught. Judge errors do not.**

Every teacher output runs through the verifier — citations checked against the statute store, numbers against the facts table. A mediocre teacher raises the rejection rate: more retries, slightly more cost, but the surviving data is still verified. Quality degrades gracefully.

The judge **is** the measurement. Nothing downstream checks it except human calibration on ~150 items (task 41). A bad judge silently corrupts two of the seven metrics.

> **Optimise the teacher for cost. Buy the judge for quality.**

**One caveat.** The verifier catches wrong citations and wrong numbers. It does **not** catch wrong legal *reasoning* — a teacher can cite s.69 correctly, state "two years" correctly, and still explain the law badly. So use a solid open model; just don't pay premium rates for it.

**A cheaper judge pattern.** Two-tier: a cheap judge on everything, escalating borderline or low-confidence cases to the expensive one. Typically cuts judge cost 60–70% with little loss in agreement. Evaluate it once κ numbers exist to compare against.

**Pin the judge's model version.** If a hosted model updates mid-study, the measurements shift underneath the results.

### 5.7 What else is not trained

| Model | Role | Note |
|---|---|---|
| **Frontier reference** | An honest ceiling for the baseline table | Clearly labelled as not part of the offline system |

One tiny model **is** trained: a scope/category classifier (logistic regression over sentence embeddings). CPU, seconds. Used by the verifier's scope check.

---

## 6. Quantization — every type, explained

### Quantization is not training

**No learning happens.** We take a finished model and make smaller copies of it, like exporting a WAV to MP3 at different bitrates. Same model, fewer bits per weight, progressively worse fidelity.

### 6.1 The GGUF ladder (llama.cpp)

GGUF is llama.cpp's model format. Its quantization types come in two families.

**K-quants** (`Q*_K_*`) — block-wise quantization with per-block scales and different bit allocations per tensor type. The `_M` suffix means the "medium" variant, which spends extra bits on the tensors that matter most.

**I-quants** (`IQ*`) — use an **importance matrix** plus lattice codebooks. Substantially better than K-quants below about 3 bits, but require a calibration pass.

| Rung | Approx. bits/weight | 4B size | Character |
|---|---|---|---|
| `bf16` | 16.0 | ~8.0 GB | The reference. No compression. |
| `Q8_0` | ~8.5 | ~4.3 GB | Effectively lossless |
| `Q6_K` | ~6.6 | ~3.3 GB | Very close to reference |
| `Q5_K_M` | ~5.7 | ~2.9 GB | Small measurable loss |
| `Q4_K_M` | ~4.85 | ~2.5 GB | The usual production sweet spot |
| `Q3_K_M` | ~3.9 | ~2.0 GB | Noticeable degradation begins |
| `IQ2_M` | ~2.7 | ~1.5 GB | Extreme. Requires imatrix. |

Bits-per-weight figures are approximate — actual values are computed from measured file size ÷ parameter count, and **that measured number becomes the continuous dose variable** for the dose-response analysis in §9.

### 6.2 The importance matrix (imatrix)

Run calibration text through the model, measure activation magnitudes per weight, and produce a matrix saying which weights matter most. The quantizer then spends more bits on those.

Required for IQ2, and it measurably helps Q3 too.

**The calibration set is itself a design choice, and we test both:**

| Calibration set | Question it answers |
|---|---|
| Generic text (wikitext) | The standard approach |
| Domain text (a slice of PocketRights training data) | Does domain-calibrated quantization preserve *legal* reliability better? |

Costs one extra afternoon, yields a real finding.

### 6.3 The INT4 comparison methods

Both produce 4-bit models, but by fundamentally different mechanisms — which is exactly why comparing them is interesting.

| Method | How it works | Failure mode |
|---|---|---|
| **AWQ** (Activation-aware Weight Quantization) | Identifies the ~1% of weight channels that matter most (by activation magnitude), scales them up before quantizing so they survive rounding | Depends on calibration data being representative |
| **GPTQ** | Quantizes layer by layer, using second-order (Hessian) information to compensate each rounding error in the remaining weights | Error accumulation across layers |

Both run at INT4 group-wise. **Same calibration set for both**, or the comparison is confounded.

### 6.4 Optional extra axis

**KV-cache quantization** (q8_0 / q4_0). Separate from weight quantization; dominates memory at long context. Worth one extra sweep on the website deployment if serving cost matters.

### 6.5 What gets quantized

| Models | Rungs | Cells |
|---|---|---|
| 4 sizes × base zero-shot | all 9 | 36 |
| 4 sizes × QLoRA (scaling axis) | all 9 | 36 |
| 4 method arms at 4B (LoRA, full, CPT→SFT + reference) | all 9 | ~27 new |
| 7 ablation models | 3 (`bf16`, `Q4_K_M`, `IQ2_M`) | 21 |
| **Total** | | **~130 evaluation cells** |

At 500 questions each: **~65,000 generations.**

---

## 7. The experimental grid

### Three factors

| Factor | Levels |
|---|---|
| **Model size** | 1.7B · **4B (reference)** · 8B · 14B |
| **Training method** | none · QLoRA · LoRA · full FT · CPT→SFT |
| **Precision** | bf16 · Q8_0 · Q6_K · Q5_K_M · Q4_K_M · Q3_K_M · IQ2_M · AWQ-INT4 · GPTQ-INT4 |

**Model family: Qwen3.** Sizes 0.6B / 1.7B / 4B / 8B / 14B / 32B, same tokenizer, same architecture family, Apache-2.0 throughout. Only size varies — a clean scaling axis for free, and a licence that permits public release of both weights and the website.

*(The exact base model must be re-confirmed at task 43 against current availability, licensing, tokenizer behaviour, and inference support — the original spec requires this.)*

### Ablation factors (held at 4B + QLoRA)

Refusal data on/off · clarification data on/off · citation-structure on/off · data scale 25/50/100% · LoRA rank 8/16/32 · imatrix calibration generic/domain.

---

## 8. Evaluation metrics

| # | Metric | How scored | Deterministic? |
|---|---|---|---|
| 1 | **Citation validity** | Does the cited Act + Section exist in the statute store? | ✅ SQL lookup |
| 2 | **Citation relevance** | Does the cited provision actually support the claim? | ❌ Judge model, calibrated |
| 3 | **Numeric fidelity** | Do stated numbers match the verified facts table? | ✅ Table lookup |
| 4 | **Critical-omission rate** | Does the answer omit something essential — a state caveat, an eligibility condition, a required escalation route? | ❌ Rubric + judge |
| 5 | **Hallucinated-authority rate** | Invented Acts, Sections, regulations, authorities, helplines | ✅ + judge for invented regulations |
| 6 | **Refusal calibration** | Out-of-scope recall **and** in-scope over-refusal, reported **separately** | ✅ |
| 7 | **General capability retention** | Small MMLU / IFEval slices — did specialization break general ability? | ✅ |

Plus **fluency** as a control variable — the whole point of H1 is that reliability degrades while fluency holds.

### Judge calibration

The judge must come from a **different model family than the teacher**, or it will rubber-stamp its own family's style. Human-label ~150 gold items, report **Cohen's κ and raw agreement**, and state the judge's error rate as a limitation. The judge is an evaluation instrument, not an oracle.

---

## 9. Causal inference and statistics

This is what turns a benchmark table into a study.

### Identification comes from the design

Every factor is an intervention we **assign**, not something we observe. There is no confounding to adjust for — *provided nothing else moves.* Five things would break that:

| Threat | Fix |
|---|---|
| Rank ablation secretly changes effective LR (scaling is α/r) | Hold **α = 2r** |
| Removing a data slice also shrinks the dataset | **Resample to constant N** |
| Quant methods using different calibration data | **One shared calibration set** across imatrix / AWQ / GPTQ |
| Decoding variance | Greedy, fixed seed, fixed max tokens, **one pinned llama.cpp commit** |
| Prompt drift between cells | Byte-identical prompt template everywhere |

### The statistical model

The same 500 items appear in every cell — repeated measures. Per-cell averages throw away information and understate precision. Use a **generalised linear mixed model** with item-level random intercepts:

```
outcome_ij ~ size + method + bits + size:bits + method:bits + (1 | item)
```

Logistic GLMM for binary outcomes (citation valid, number correct, refusal correct); linear for graded scores. The `(1 | item)` term accounts for some questions simply being harder, which is what makes cross-rung comparisons powerful.

### Four analyses on top

**1. Dose–response.** Treat measured bits-per-weight as a continuous dose. Fit a segmented regression and report **the breakpoint with a confidence interval** — *"reliability degrades below 3.4 bits/weight [3.1–3.8]"* — rather than eyeballing a curve.

**2. Mediation.** Compression hurts overall quality, but *through what*? Decompose the effect through numeric fidelity, citation validity, and format degradation as mediators. This is a direct test of H1 and H2: what breaks first.

**3. Heterogeneous effects.** Interact `bits × question type`. Does compression hurt numeric questions more than explanatory ones? Refusals more than answers? Subgroup by vertical, difficulty, and expected behaviour.

**4. Multiple comparisons.** ~130 cells × 7 metrics is a lot of tests. **Primary endpoints: citation validity and numeric fidelity.** Everything else is secondary, with Benjamini–Hochberg FDR control applied to the secondary family.

### Pre-registration

Hypotheses and this entire analysis plan are written to `docs/preregistration.md` **before the sweep runs** (task 4). Otherwise the causal claims are decoration.

---

## 10. Tech stack

| Layer | Choice | Why |
|---|---|---|
| Language / env | Python 3.12, `uv` | Fast, lockfile-based, workspace support |
| Storage | **SQLite** (+ FTS5) | Corpus is small (~3k sections). One file, ships to the website unchanged, zero infrastructure. |
| Corpus fetching | `httpx` + `tenacity`, `trafilatura` / `selectolax`, `pymupdf` | HTML and PDF sources |
| Data models | `pydantic` | Provenance records, response contract validation |
| Embeddings | `multilingual-e5-small` | Scope classifier + dedup + contamination checks. Handles romanized Hinglish. |
| Base models | **Qwen3** family (1.7B / 4B / 8B / 14B) | Apache-2.0, one tokenizer across the size axis, first-class llama.cpp support |
| Fine-tuning | `transformers` + `peft` + `trl` + `bitsandbytes` + `accelerate` | Standard QLoRA / LoRA / full-FT paths |
| Multi-GPU (14B full FT) | FSDP via `accelerate` | Only needed for the largest full-FT arm |
| Teacher | Hosted open-weights model via an **OpenAI-compatible API** — Ollama Cloud is a strong candidate (flat subscription) | Spec requires an *open* teacher. Hosted API ≠ closed model. See §10.1. |
| Judge | **Different family** from the teacher; quality prioritised over cost | Prevents same-family rubber-stamping. See §5.6. |
| Quantization | `llama.cpp` (GGUF + imatrix), `llm-compressor` / `autoawq`, `gptqmodel` | The ladder plus the two INT4 comparison methods |
| Eval inference | `llama-server` (OpenAI-compatible) for GGUF; `vLLM` for AWQ/GPTQ | Swap rungs by restarting a server; identical client code |
| Statistics | `pandas`, `statsmodels`, `pymer4`/`lme4`-equivalent, `scipy` | GLMM, segmented regression, mediation, FDR |
| Plots | `matplotlib` | Paper figures |
| Website backend | `FastAPI` + `llama-server` | Serves the model, the verifier, and the statute store |
| Website frontend | Minimal React or HTMX | Ask a question, see the structured answer, expand citations |
| Deployment | Modal web endpoint with GPU | Same platform as training |

### 10.1 Provider abstraction — a hard requirement

`pr_datagen` and `pr_eval` must talk to an **OpenAI-compatible `/v1` interface**, never a vendor SDK. Ollama exposes one; so does essentially every per-token provider. Teacher and judge then become configuration, not code:

```yaml
teacher:
  base_url: https://ollama.com/v1
  model: <pinned-tag>
  digest: <recorded at run time>
  temperature: 0.25
  num_ctx: 8192            # MUST be set explicitly — see §10.2
judge:
  base_url: <different provider>
  model: <different family>
  temperature: 0
```

Switching providers is then a config change. This matters because the provider decision **cannot be made responsibly until the pilot (task 30) reveals real rate limits.**

**Three tiers:**

| Stage | Where | Cost |
|---|---|---|
| Prompt iteration (hundreds of calls) | Local Ollama on the M4 Pro — 48 GB runs a 20–30B model at Q4 | free |
| Pilot, 500 examples + retries (task 30) | Ollama Cloud — and measure where the limits bite | subscription |
| Full scale, 40–80k (task 34) | Ollama Cloud if limits allow, else swap `base_url` | subscription, or ~$80–250 |

**Before committing to any provider, verify:**

1. **Rate limits and fair-use caps** — we need ~125M input tokens for 50k teacher calls
2. **Concurrency** — at ~20 s per generation, 50k calls run serially is 280 hours
3. **Terms of service on training from outputs** — the model *licence* usually permits it, but the *service* ToS is separate, and this work gets published
4. **Model version pinning** — record tag + digest per call, or "teacher = model-X" is not a reproducible statement in six months
5. **Structured-output reliability** — test JSON-schema mode on 50 examples before trusting it on 50,000

### 10.2 The generation client — requirements for task 28

Fifty thousand API calls is a piece of infrastructure, not a `for` loop. The client must have:

| Requirement | Why |
|---|---|
| **Resumability** | A 50k-call job *will* be interrupted — crash, rate limit, laptop sleep, cap. Every example gets a stable ID; results append incrementally to JSONL/SQLite; restart skips completed IDs. Without this you lose a day and $30 to a dropped connection. |
| **Bounded concurrency** | A semaphore over N parallel workers, tuned to the provider's limits |
| **Backoff** | Exponential with jitter on 429/503, respecting `Retry-After`; token bucket if there is a documented tokens-per-minute cap |
| **Response caching** | Content-hash the request, cache locally. Prompt iteration re-runs the same scenarios constantly — caching makes that free. |
| **Validation** | Validate every response against the pydantic model even in schema mode. Malformed → retry, then quarantine. |
| **Full logging** | Request, response, model tag, model digest, token counts, cost — all to disk. This is what lets the dataset be defended later. |
| **Cost tracking** | A running total, so a runaway job is visible immediately |

#### ⚠ The failure mode that would silently poison the dataset

**Ollama defaults `num_ctx` to a small value and silently truncates longer prompts.**

Our teacher prompt is ~2,500 tokens. If `num_ctx` sits at the default, the statute text is cut off — and the teacher writes a confident answer from half a section. No error, no warning, nothing in the logs. You would not discover it until the pilot audit, and even then only by wondering why citations kept being subtly wrong.

**Both mitigations are required:**
- Set `num_ctx` explicitly on every call
- Measure the prompt with the tokenizer *before* sending, and fail loudly if it exceeds the configured window

**Related — enforce a context budget.** Some sections are enormous (MV Act penalty schedules). Trim long sections around the relevant passage, cap the number of sections included, and always keep section headings intact so citations stay accurate.

#### Sampling settings

| | Temperature | Rationale |
|---|---|---|
| **Teacher** | 0.2–0.3 | Consistent format and grounding. Variety comes from the scenarios, not the sampler. |
| **Judge** | 0 | A measuring instrument should give the same verdict twice. |

Fixed seed on both, recorded per call.

---

## 11. Repository structure

```
pocketrights/
├── pyproject.toml                    # uv workspace root
├── PROJECT.md                        # this file
├── docs/
│   ├── scope.md                      # THE FROZEN SCOPE — the contract everything obeys
│   ├── response-contract.md          # JSON schema + GBNF grammar + disclaimer text
│   ├── sources.md                    # source registry: what, from where, licence, snapshot
│   ├── preregistration.md            # hypotheses + statistical analysis plan
│   ├── model-card.md
│   └── paper/
├── packages/
│   ├── pr_corpus/                    # acquisition, provenance, hashing, snapshots
│   ├── pr_store/                     # statute store + facts table + authorities (SQLite)
│   ├── pr_verify/                    # the verification engine
│   ├── pr_datagen/                   # scenarios, teacher, repair loop, CPT corpus
│   ├── pr_eval/                      # benchmark harness + metrics + statistics
│   ├── pr_train/                     # CPT, SFT; QLoRA / LoRA / full FT
│   └── pr_quant/                     # GGUF ladder, imatrix, AWQ, GPTQ
├── data/
│   ├── raw/<source_id>/<snapshot>/   # IMMUTABLE. Never edited. Hashed.
│   ├── store/pocketrights.db
│   ├── datasets/{train,dev}.jsonl
│   ├── cpt/                          # raw + augmented statute text for continued pretraining
│   └── bench/pocketrights_bench.jsonl   # NEVER touched by training
├── models/                           # adapters, merged, gguf/, awq/, gptq/
├── runs/                             # one dir per run: config.json + results.parquet
├── web/                              # FastAPI backend + frontend
└── scripts/
```

**Two hard rules that pay for themselves later:**

- `data/raw/` is **append-only**. A re-crawl creates a new dated snapshot; it never overwrites.
- `runs/` never gets cleaned. Every number in the paper traces to a run directory.

---

## 12. Hardware and cost

| Environment | Role |
|---|---|
| **M4 Pro, 48 GB (Metal)** | Everyday driver — corpus, store, facts, verifier, dataset orchestration, teacher/judge API calls, the entire GGUF ladder, **all benchmark evaluation**, imatrix, statistics, plots. 48 GB holds every model in the study at Q4, and most at bf16. |
| **Modal (ephemeral CUDA)** | Every training run, AWQ + GPTQ quantization, vLLM evaluation of INT4 variants, website hosting |

### Training cost per run (rough)

| Size | QLoRA | LoRA | Full FT |
|---|---|---|---|
| 1.7B | ~$3 | ~$4 | ~$4 |
| **4B** | **~$5** | ~$8 | ~$8 |
| 8B | ~$8 | ~$12 | ~$16 |
| 14B | ~$14 | ~$22 | ~$50 *(2×H100)* |

### Total budget

| Item | Estimate | Basis |
|---|---|---|
| Teacher generation | **$80–250** | Arithmetic below |
| Judge (calibration + evaluation) | **$50–100** | ~65k sweep judgments + ~30k during dataset verification |
| Training (18 runs) | **$150–250** | Theoretical GPU time is only ~$100. The rest is re-runs, crashed jobs, container builds and idle GPU during model/dataset loading — all guaranteed, not hypothetical. |
| Quantization + INT4 evaluation | **$30–50** | GGUF conversion, imatrix and the whole ladder run **free on the Mac**. This line is only AWQ/GPTQ builds (~$10) and vLLM evaluation of those 16 cells (~$10–20). |
| Website hosting | **$5–30/mo** | See below |
| **One-time total** | **≈$310–650** | |

#### Teacher arithmetic

Per call: ~1,000 tokens of system prompt and few-shot, ~100 for the scenario, ~1,400 of statute text = **~2,500 input**; **~650 output**.

For 100k examples at a 50/50 programmatic/teacher split:

```
50,000 teacher calls
  input:   50,000 × 2,500 = 125M tokens × ~$0.35/M  = $44
  output:  50,000 ×   650 =  32M tokens × ~$0.45/M  = $15
  repair loop (~30% fail, one retry)                 +$18
  pilot iterations (500 × ~4 rounds)                  +$3
                                                     ─────
                                                      $80
```

| Scenario | Cost |
|---|---|
| 60k examples, heavy programmatic, cheap teacher | $40–60 |
| 100k examples, 50/50 split, mid-tier teacher | $80–120 |
| 150k examples, teacher-heavy, large MoE teacher, two full regenerations after audit | $250–400 |

A flat-rate provider could collapse this line to two or three months' subscription — see §10.1.

#### Judge arithmetic

```
65,000 sweep generations
  input:   65,000 × 2,000 = 130M tokens × ~$0.35/M  = $46
  output:  65,000 ×   200 =  13M tokens × ~$0.45/M  =  $6
  dataset verification (~30k borderline cases)       +$24
                                                     ─────
                                                      $76
```

Only **2 of the 7 metrics** need a judge. The other five are deterministic lookups and cost nothing.

> ⚠ **Per-token rates above are approximate and move frequently.** ~$0.35/M input and ~$0.45/M output is roughly mid-range for hosted open-weights 70B-class models. Verify current rates before relying on these totals — a 3× spread between providers is normal.

#### Website hosting — two options

| Option | Cost | Trade-off |
|---|---|---|
| **CPU, always-on** — 4B at Q4 via llama.cpp, ~5–10 tok/s | $5–15/mo | Slow but consistent, no cold start. **Preferred for a comparison demo.** |
| GPU, scale-to-zero | per-request | Fast when warm, but a 30–60 s cold start. Never leave a GPU warm — that is ~$1,000/mo. |

Nothing before task 28 costs anything.

### Timeline

Part-time at 15–20 h/week: **~6 months.** Full-time: **~12 weeks.** The three genuinely hard human-time tasks are **17** (verify every fact), **31** (audit the pilot), and **37** (author the benchmark).

---

## 13. The task list (0–73)

> 74 tasks, zero-indexed. Training tasks are **bold with ▶**. Quantization tasks are **bold with ◆**.

### Foundations

| # | Task |
|---|---|
| 0 | Set up the repo — uv workspace, package folders, `data/ runs/ docs/ web/` |
| 1 | Write `docs/scope.md` — five verticals, ~50 question categories, out-of-scope list, clarification triggers, critical-omission catalogue |
| 2 | Write `docs/response-contract.md` — strict JSON answer schema, disclaimer wording, GBNF grammar |
| 3 | Write `docs/sources.md` — every Act/Rule/Regulation, portal, licence, snapshot plan |
| 4 | Write `docs/preregistration.md` — hypotheses, primary vs secondary endpoints, full statistical plan |
| 5 | Set up the cloud GPU account — CLI, container image, persistent volume, secrets, hello-GPU test |

### Corpus

| # | Task |
|---|---|
| 6 | Build the corpus fetcher — immutable raw bytes, SHA-256, provenance record per source |
| 7 | Determine the in-force employment regime from the Gazette and record the decision |
| 8 | Acquire consumer / e-commerce sources |
| 9 | Acquire tenancy sources — central law plus 3–4 state rent acts |
| 10 | Acquire traffic sources — MV Act, CMVR, state compounding notifications |
| 11 | Acquire employment sources per task 7 |
| 12 | Acquire insurance sources — Insurance Act, IRDAI regulations and circulars, Ombudsman Rules |

### Knowledge layer

| # | Task |
|---|---|
| 13 | Write per-Act parsers — HTML/PDF into one record per section |
| 14 | Build the statute store — SQLite `sections`, FTS5, `act_aliases` *(grading + website only, never in a prompt)* |
| 15 | Spot-check the store — section counts, text fidelity, numbering edge cases like `2(7)` and `69(1)` |
| 16 | Extract candidate numeric facts from the corpus |
| 17 | **Human-verify every fact row against its source quote** |
| 18 | Build the authorities table — commissions, RTO, EPFO, Ombudsman, helplines, filing portals |

### Verifier

| # | Task |
|---|---|
| 19 | Build the citation-existence check |
| 20 | Build the numeric check against the facts table |
| 21 | Build the authority check |
| 22 | Build the scope check — rules plus a small embedding classifier |
| 23 | Build the citation-relevance check — judge model, offline grading only |
| 24 | Write 30 deliberately-broken answers and tune the verifier until it scores them as you would |

### Dataset

| # | Task |
|---|---|
| 25 | Build the scenario generator — categories × personas × ambiguity × 15% romanized Hinglish |
| 26 | Add coverage assertions and deduplication |
| 27 | **Design the knowledge-injection data types** — statute recall, reverse recall, numeric recall, cloze, paraphrase, applied-to-scenario |
| 28 | Build the teacher pipeline — grounded in the statute store, producing closed-book training targets. **The client must meet the requirements in §10.2** — resumability, bounded concurrency, backoff, caching, validation, and an explicit `num_ctx` |
| 29 | Build the verify → repair → re-verify loop with rejection-reason logging |
| 30 | Generate the 500-example pilot |
| 31 | **Human-audit ~100 stratified samples** |
| 32 | Fix the pipeline, regenerate, repeat until under 5% material defects |
| 33 | Measure token distributions; fix sequence length |
| 34 | Scale to 60k–150k examples plus dev set |
| 35 | Audit dataset distribution and per-fact view coverage |
| 36 | Build the CPT corpus — raw statute text plus augmented rephrasings |

### Benchmark and measurement

| # | Task |
|---|---|
| 37 | **Author PocketRights-Bench — 500 gold items with rubrics** |
| 38 | Contamination check — embedding and n-gram dedup, wired as a CI gate |
| 39 | Build the evaluation harness — seven metrics, per-item parquet output, run artifacts |
| 40 | Build the statistics layer — GLMM, bootstrap, segmented regression, mediation, FDR control |
| 41 | Human-label ~150 bench items and calibrate the judge; report Cohen's κ |
| 42 | Run zero-shot baselines at all four sizes |

### Training

| # | Task |
|---|---|
| 43 | Build the training pipeline — CPT and SFT paths; QLoRA / LoRA / full FT; completion-only loss masking; launcher |
| 44 | Run the local shape test — chat template renders, loss mask covers response tokens only |
| 45 | Run the smoke training job |
| 46 | ▶ **Train** the 4B QLoRA reference (`M-QLORA`) |
| 47 | ▶ **Train** two seed replicates (`S-2`, `S-3`) |
| 48 | ▶ **Train** 4B LoRA, 16-bit base (`M-LORA`) |
| 49 | ▶ **Train** 4B full fine-tune (`M-FULL`) |
| 50 | ▶ **Train** 4B CPT → SFT (`M-CPTSFT`) |
| 51 | ▶ **Train** QLoRA at 1.7B, 8B, 14B (`Z-*`) |
| 52 | ▶ **Train** data ablations (`D-NOREFUSE`, `D-NOCLARIFY`, `D-NOCITE`, `D-25PCT`, `D-50PCT`) |
| 53 | ▶ **Train** rank ablations (`R-8`, `R-32`) |
| 54 | Evaluate every checkpoint at bf16 and select the reference model |
| 55 | Merge adapters into their base weights |

### Quantization

| # | Task |
|---|---|
| 56 | ◆ **Convert** every selected checkpoint to F16 GGUF |
| 57 | ◆ **Compute** two importance matrices — generic and domain-calibrated |
| 58 | ◆ **Quantize** the full ladder — Q8_0, Q6_K, Q5_K_M, Q4_K_M, Q3_K_M, IQ2_M |
| 59 | ◆ **Build** AWQ-INT4 and GPTQ-INT4 variants |

### The study

| # | Task |
|---|---|
| 60 | Run the full sweep — 500 questions × ~130 cells |
| 61 | Fit the GLMM; estimate main effects and interactions |
| 62 | Fit the dose–response curve and locate the compression breakpoint with a CI |
| 63 | Run the mediation analysis — what breaks first |
| 64 | Run heterogeneous-effect analysis by question type, vertical, and difficulty |
| 65 | Apply FDR control; separate primary from secondary findings |
| 66 | Adjudicate the pre-registered hypotheses |
| 67 | ▶ **Train** the production retrain on train + dev with the frozen winning recipe (`RF`) |

### Website and release

| # | Task |
|---|---|
| 68 | Build the website backend — model server, statute store, verification endpoint |
| 69 | Build the website frontend — ask a question, structured answer, citations that expand to real section text |
| 70 | Add the model switcher — let visitors compare rungs live, Q4 against IQ2, side by side |
| 71 | Deploy |
| 72 | Write the model card — limitations, corpus snapshot date, version pinning |
| 73 | Write the final analysis and the paper |

---

## 14. Risks

| # | Risk | Mitigation |
|---|---|---|
| **R1** | **A 4B cannot reliably memorise exact numbers** (₹20 lakh, 2 years, 12%). This is the single biggest technical risk of going closed-book. | Multi-view knowledge-injection data (task 27), CPT arm (task 50), and the size axis. If it fails, *that is the headline finding* — H2 confirmed. |
| **R2** | **The reversal curse.** Training on *"Section 69 provides a two-year limitation period"* does not reliably let the model answer *"which section sets the limitation period?"* | Teach every fact from multiple directions — forward, backward, cloze, paraphrase, applied-to-scenario (task 27) |
| **R3** | **The gold set eats the schedule.** 500 hand-verified items is 100–200 hours. | Decide the tiering strategy before task 37 — see Open Decisions |
| **R4** | **Labour-code temporal ambiguity.** Old Acts vs. the four new Codes. Blending regimes produces confidently wrong answers. | Task 7 establishes the in-force regime from the Gazette *before* any employment data is written. If it is messy, build employment last or scope it to gratuity + EPF. |
| **R5** | **CPT causes catastrophic forgetting** — the model gets worse at instruction-following | Mix general text into the CPT corpus, low LR, 1–2 epochs. And measure it: general capability retention is metric #7. |
| **R6** | **Teacher produces subtly wrong legal *reasoning*.** The verifier catches citations and numbers, not reasoning. | Human audit (task 31) + relevance judge + an honest limitations section |
| **R7** | **Benchmark contamination** between train and gold | Automated dedup as a CI gate (task 38), not a one-time script |
| **R8** | **The judge is wrong and you cannot tell** | Cohen's κ against human labels (task 41), reported as a limitation |
| **R9** | **Multiple comparisons.** ~130 cells × 7 metrics invites false positives. | Pre-registered primary endpoints + FDR control (tasks 4, 65) |
| **R10** | **Legal drift.** Closed-book means the law is frozen in the weights. | Every release states its corpus snapshot date and never implies it is current (task 72) |
| **R11** | **Scope creep** into general legal advice | `docs/scope.md` is version-controlled; expanding scope is a new project version |
| **R12** | **Source portal changes / link rot** | `data/raw/` is immutable and hashed; every claim traces to a stored snapshot |

---

## 15. Open decisions

| # | Decision | Recommendation | Blocks |
|---|---|---|---|
| **D1** | Reference model size | **4B** — cheapest place to run the five-arm method comparison; the scaling axis extends from it | Task 43 |
| **D2** | Is **14B** in or out? | In for QLoRA (~$14). Full FT at 14B needs 2×H100 (~$50) — optional. | Task 51 |
| **D3** | Gold-set strategy | **Tiered:** 150 fully human-authored core + 350 human-verified, split reported honestly. ~40–70 h instead of 100–200 h. | Task 37 |
| **D4** | Total budget ceiling | $400–800 covers the full plan | Task 34 |
| **D5** | Hours per week | Drives the timeline and D3 | — |
| **D6** | Public weight release? | Qwen3 is Apache-2.0, so yes is available | Task 72 |
| **D7** | Keep RAG as one comparison column? | The statute store exists anyway, so it is nearly free and answers "was retrieval even needed?" | Task 60 |
| **D8** | Git — initialise version control? | Strongly recommended for reproducibility. **Requires explicit authorization.** | Task 0 |
| **D9** | Teacher and judge providers | Teacher: flat-rate open model (Ollama Cloud is the leading candidate). Judge: different family, quality over cost. **Decide from pilot measurements, not now** — §10.1 | Task 30 |

---

## 16. Definition of done

- [ ] Supported domains and boundaries are documented
- [ ] The legal corpus has provenance and a dated snapshot
- [ ] Sections are independently retrievable and citation-checkable
- [ ] Critical numeric facts are structured and verified against source quotes
- [ ] Synthetic training examples pass automated verification
- [ ] Training and gold test data are separated and dedup-checked
- [ ] PocketRights-Bench is human-verified
- [ ] Zero-shot baselines are measured at every size
- [ ] All five training arms are trained and documented
- [ ] Seed variance is reported alongside every ablation delta
- [ ] Meaningful data and capacity ablations have been performed
- [ ] Multiple quantization levels and methods are evaluated on the same benchmark
- [ ] Reliability is measured separately from surface fluency
- [ ] The compression breakpoint is estimated with a confidence interval
- [ ] Mediation analysis identifies what degrades first
- [ ] Pre-registered hypotheses are adjudicated, including disconfirmed ones
- [ ] Judge–human agreement is reported
- [ ] The website runs and lets visitors compare quantization rungs live
- [ ] Legal-version limitations are documented
- [ ] The final analysis explains the accuracy–efficiency–reliability trade-off

---

*PocketRights — from authoritative law to a measured model.*
