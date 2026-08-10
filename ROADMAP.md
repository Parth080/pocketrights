# PocketRights — Build Roadmap

> Living document. Derived from `PocketRights.pdf` (Complete Project Specification, 17pp).
> The PDF freezes **what** and **why**. This file fills in **how**: tech stack, repo shape, sequencing, and the decisions the spec deliberately left open (§42).
>
> Status: DRAFT v0.1 — nothing built yet. Reviewed by: —

---

## 0. The one-paragraph mental model

You are building **three things that happen to share a repo**:

1. **A knowledge system** — Indian legal text, stored section-by-section with provenance and dates, plus a table of every critical number, so any claim can be mechanically checked against a source.
2. **A specialized small model** — a ~4B instruct model taught *behaviour* (cite, clarify, refuse, caveat) rather than taught *law*, then squeezed down a quantization ladder.
3. **A measurement instrument** — a fixed 500-question benchmark and a scoring harness that measures *legal reliability* (citations, numbers, omissions, refusals) separately from *fluency*, run identically at every compression level.

The product (an offline Android app) is the proof that #1 + #2 work together on a cheap phone.
The paper (the reliability-vs-compression curves) is the proof that you measured, not guessed.

**The single most important design principle in the spec:** the model generates language, the corpus provides evidence, and a *deterministic verifier* checks claims. Never let the LLM be the judge of its own facts. Everything below is downstream of that.

---

## 1. Decisions I need from you before we lock the stack

| # | Question | Status |
|---|---|---|
| D1 | Hardware | ✅ **ANSWERED** — RTX 4060 laptop (8 GB), M4 Pro Mac (48 GB unified), Modal available. See §1A. |
| D2 | Cloud budget, roughly? ($0 / ~$150 / ~$500) | Open — decides teacher tier and ablation grid width |
| D3 | Primary goal: paper/thesis, portfolio piece, or shipped app? | Open — paper → ablation rigour; portfolio → the airplane-mode demo |
| D4 | Hours per week you can put in? | Open — drives the gold-set strategy (§Block 3f), the real bottleneck |
| D5 | Will you release model weights publicly? | Open — decides base-model licence: Apache-2.0 (Qwen) vs Gemma Terms vs Llama Community |
| D6 | Ablation grid tier: core (6 runs) / recommended (11) / deep (14)? | Open — see §1C |
| D7 | Android test phone — do you have one? | Open — decides whether Block 6 is real measurement or simulation |

---

## 1A. Hardware plan

Three machines, three distinct jobs. None of them is redundant.

| Machine | Role | What runs here |
|---|---|---|
| **M4 Pro, 48 GB** | **Everyday driver — 80% of your hours** | Corpus work, statute store, facts table, verifier, dataset orchestration, the *entire* GGUF quantization ladder + all benchmark evaluation (Metal llama.cpp is excellent, and 48 GB holds the bf16 reference *and* every rung), imatrix computation, judge orchestration, stats + plots, Android Studio |
| **Modal (ephemeral H100/A100)** | **The training rig** | Every SFT run, AWQ + GPTQ quantization (CUDA-only), vLLM eval of the INT4 variants, optionally a self-hosted open teacher |
| **RTX 4060 laptop, 8 GB** | **CUDA sanity box + reference environment** | Free smoke runs to debug the training script before spending Modal credits; small vLLM/AWQ tests; **and it is one of the spec's named reference environments (§32)**, so it earns a row in the device-benchmark table |

Note: the spec §32 explicitly lists "a Mac M4 Pro" and "an RTX 4060 system" as reference hardware. You happen to own exactly those, so both machines have a *research* role in the benchmarking chapter, not just a dev role.

**Why not train on the 4060.** 8 GB fits a 4B QLoRA job at seq 2048 (≈2.5 GB NF4 weights + LoRA/optimizer + checkpointed activations ≈ 6.5–7 GB), so it *works* — it's just slow: roughly **25–30 h per run**, on a thermally-limited laptop you can't use meanwhile. And if retrieved legal sections push us to seq 3072/4096 (likely), it gets tighter and roughly doubles again.

**Why not train on the M4 Pro.** 48 GB unified is plenty of memory, but: (a) `bitsandbytes` NF4 is CUDA-only, so you'd be on MLX-LM LoRA instead — a *different* algorithm from the QLoRA the spec specifies (§19), which weakens reproducibility for a paper; (b) throughput is still ~35–40 h/run. Memory isn't the constraint here, compute is.

**Why Modal.** Python-native, per-second billing, zero idle cost, and you can fan out several ablation runs in parallel. A run that takes 27 h on the laptop takes ~1–3 h on an H100/A100. The whole grid becomes an afternoon and a rounding error in the budget (see §1C).

> Practical macOS tip for the eval phase: the default GPU wired-memory limit is ~75% of RAM. If a large GGUF won't load, raise it with `sudo sysctl iogpu.wired_limit_mb=40960`.

---

## 1B. What "training" means here — exactly one paradigm

This matters because the word "training" gets used loosely. In PocketRights there is **one** training paradigm and nothing else:

> **Supervised fine-tuning (SFT), parameter-efficient, via LoRA adapters on a frozen 4-bit (NF4) base model — i.e. QLoRA.**
> Objective: next-token cross-entropy, **masked to the assistant response tokens only.**

Everything else is explicitly *not* happening:

| Not doing | Why |
|---|---|
| Pretraining from scratch | Absurd at this scale; nothing in the spec asks for it |
| **Continued pretraining on the legal corpus** | Deliberate. The corpus is the *knowledge layer* (§28) and must be updatable **without retraining**. Baking statutes into weights is the exact opposite of the project's architecture. |
| DPO / RLHF / RLAIF / GRPO | Explicitly excluded by spec §21 — reserved for your separate RLHF project |
| Reward-model training | Follows from the above |
| Fine-tuning the embedding/retriever model | Off-the-shelf `multilingual-e5-small` is adequate. Revisit only if retrieval recall measures badly. |

Two small non-LLM training jobs do exist, and they're trivial:

- **Scope/category classifier** for verifier check §11.5 — logistic regression or a small head over sentence embeddings. CPU, seconds to minutes. May not even be needed if embedding-kNN + rules suffice.
- Nothing else.

And three **calibration** passes, which are GPU work but are *not* training (no gradient updates to the LLM):

- `llama-imatrix` importance matrix for the IQ2/Q3 rungs — Metal, runs on the Mac
- AWQ scale search — CUDA, Modal
- GPTQ solve — CUDA, Modal

---

## 1C. The complete list of training runs

One paradigm, N runs of it. Every ablation changes **exactly one factor** from the V1 baseline recipe (one-factor-at-a-time, not a cross product).

### Tier 1 — Core (required; 6 runs)

| ID | Run | What changes vs V1 | Answers |
|---|---|---|---|
| R0 | **Smoke** | 1k examples, 1 epoch | Does the pipeline work end-to-end: chat template, loss masking, checkpointing, merge, GGUF convert, eval hookup. **Never reported.** Run on the 4060, free. |
| R1 | **V1 baseline** | — (r=16, α=32, full data, all behaviours) | The candidate reference model |
| R2 | **No refusal data** | Remove the 15% refusal/redirect slice, **resample in-scope to keep N constant** | §21: does refusal training help, and does it cause over-refusal? |
| R3 | **No structured-citation supervision** | Citations as free prose instead of the structured field | §21: does citation-structure training improve citation validity? |
| R4 | **r=8** (α=16) | LoRA rank down | §21: how much adaptation capacity is actually needed? |
| R5 | **r=32** (α=64) | LoRA rank up | ″ |

> Keep **α = 2r** across the rank sweep. LoRA scaling is α/r, so holding α=2r keeps effective scaling constant and isolates *capacity* from *effective learning rate*. Otherwise the "rank ablation" is secretly a learning-rate ablation.

### Tier 2 — Recommended (+5 runs → 11 total)

| ID | Run | Answers |
|---|---|---|
| R6, R7 | **V1 seed replicates** (2 more seeds) | **The most important addition.** Establishes run-to-run variance. Without it you cannot say whether an ablation delta of 2 points is real or noise — and that undercuts every claim in §21. |
| R8 | **No clarification data** | Is clarification behaviour emergent or does it need supervision? Arguably as interesting as the refusal ablation. |
| R9, R10 | **Data-scale curve: 25% and 50% of the dataset** | "How much *verified* synthetic data do you actually need?" This is a genuinely publishable curve and it pairs beautifully with the compression curve — two different axes of *how cheap can this get before it breaks*. |

### Tier 3 — Optional (+3 runs → 14 total)

| ID | Run | Answers |
|---|---|---|
| R11 | 2 epochs vs 3 | Overfitting check on a 20k synthetic set |
| R12 | Attention-only LoRA targets vs attention+MLP | Where does adaptation need to live? |
| R13 | Seq 2048 vs 4096 | Does more retrieved context in training help or dilute? |

### Plus one post-study run

| ID | Run | Purpose |
|---|---|---|
| RF | **Production retrain** on train+dev merged, using the frozen winning recipe | The shipped model. The *study* is reported on the train-only models so dev stays clean. |

### Cost and time

Assumptions: ~20k examples, avg ~1,600 tokens → ~32 M tokens/epoch → ~96 M tokens for 3 epochs.

| Where | Throughput (est.) | Per run | 11-run grid | Cost |
|---|---|---|---|---|
| RTX 4060 laptop (QLoRA NF4) | ~1,000 tok/s | ~27 h | **~300 h ≈ 12 days non-stop** | $0, but the laptop is unusable |
| M4 Pro (MLX LoRA bf16) | ~700 tok/s | ~38 h | ~420 h ≈ 17 days | $0, same problem |
| Modal A100-80 | ~10,000 tok/s | ~2.7 h | ~30 h (parallelisable) | **~$7/run, ~$75 grid** |
| Modal H100 | ~25,000 tok/s | ~1.1 h | ~12 h (parallelisable) | **~$5/run, ~$55 grid** |

All figures are estimates to be replaced by the first real measurement. The conclusion is robust to being off by 2×: **the grid costs about the price of a dinner on Modal, or two weeks of a hot laptop.**

Add ~$15 for AWQ/GPTQ quantization + vLLM eval on Modal. **Total GPU spend: ~$70–100.**

### Reproducibility rules for the grid

- Same seed, same data order, same eval protocol for every run; only the ablated factor moves.
- When removing a data slice, **resample to hold total example count constant** — otherwise the ablation is confounded with dataset size.
- Log every run's full config + git SHA + dataset hash into `runs/<run_id>/config.json`.
- Report the V1 seed spread alongside every ablation delta.

### Open design decision this surfaces: do we train with retrieved context?

Spec §18.3 and §18.4 evaluate the fine-tuned model *without* and *with* RAG. That only works if training reflects both:

- Train **only with** context → the no-RAG baseline is out-of-distribution and looks artificially bad.
- Train **only without** context → the model never learns to *use* retrieved sections, so RAG helps less than it should.
- **Recommended: mixed, ~70% with retrieved context / 30% without.** Makes the §18.3 vs §18.4 comparison fair, and makes the deployed hybrid the in-distribution case.

This also drives sequence length: scenario + 4–6 retrieved sections + JSON answer can exceed 2048. Either cap retrieved context to ~1,400 tokens (keeps seq 2048 as the spec suggests) or move to 3072. **Decide after measuring real token distributions in the pilot** — that's a Block 3 measurement, not a guess.

---

## 2. Repo structure

The spec left this open. Proposal — a Python monorepo with one Android sub-project:

```
pocketrights/
├── pyproject.toml            # uv workspace root
├── docs/
│   ├── scope.md              # THE FROZEN SCOPE (Stage 1) — the contract everything else obeys
│   ├── response-contract.md  # exact output JSON schema + disclaimer text
│   ├── sources.md            # source registry: what, from where, licence, snapshot date
│   ├── model-card.md
│   └── paper/
├── packages/
│   ├── pr_corpus/            # Stage 2: acquisition, provenance, hashing, snapshots
│   ├── pr_store/             # Stage 3+4: statute store + facts table (SQLite)
│   ├── pr_retrieval/         # Stage 20: hybrid BM25 + dense retrieval
│   ├── pr_verify/            # Stage 5: THE VERIFIER — deterministic + judge-backed
│   ├── pr_datagen/           # Stages 6-10: scenarios → teacher → verify → repair
│   ├── pr_eval/              # Stages 11,12,15,17,18,19: bench harness + metrics + stats
│   ├── pr_train/             # Stages 13,14: QLoRA + ablations
│   └── pr_quant/             # Stage 16: GGUF ladder, AWQ, GPTQ, imatrix
├── data/
│   ├── raw/<source_id>/<snapshot_date>/   # IMMUTABLE. Never edited. Hashed.
│   ├── store/pocketrights.db              # the statute store + facts table
│   ├── datasets/{train,dev}.jsonl
│   └── bench/pocketrights_bench.jsonl     # NEVER touched by training
├── models/                   # adapters, merged, gguf/, awq/, gptq/
├── runs/                     # one dir per eval run: config.json + results.parquet
├── android/                  # Kotlin + Compose app
└── scripts/
```

Two hard rules that pay for themselves later:
- `data/raw/` is **append-only**. A re-crawl creates a new dated snapshot, never overwrites.
- `runs/` never gets cleaned. Every number in the paper traces to a run dir.

---

## 3. Global tech stack

| Layer | Choice | Why this one |
|---|---|---|
| Language / env | Python 3.12, `uv` | Fast, lockfile-based, workspace support for the monorepo |
| Storage | **SQLite** (+ FTS5, + brute-force vectors) | The single best decision available: the *same* database file ships to Android unchanged. No Postgres→mobile porting problem. Corpus is small (~2-3k sections). |
| Lexical search | SQLite FTS5 (BM25) | Built in, works on device |
| Dense search | `multilingual-e5-small` → int8, brute-force cosine | 384-dim × ~3k sections = trivial to search anywhere. Multilingual matters for the 15% Hinglish queries. |
| Base model | **Qwen3-4B-Instruct-2507** (primary), Gemma 3 4B IT (backup) | Apache-2.0 (clean release), ~4B per spec, non-thinking variant (no reasoning traces on a phone), first-class llama.cpp support, strong multilingual. **Re-verify what's current when we get to Stage 13 — the spec explicitly requires this (§19).** |
| Fine-tuning | `transformers` + `peft` + `trl` (SFTTrainer) + `bitsandbytes` NF4 | Standard QLoRA path, exactly matches spec §19 |
| Teacher | A hosted open-weights 70B-class or large-MoE model | Spec §13 requires an *open* teacher. Hosted API ≠ closed model. Costs ~$30-60 for the full dataset. |
| Judge | Different family from the teacher (spec §25) | Prevents the judge from rubber-stamping its own family's style |
| Quantization | `llama.cpp` (GGUF ladder + imatrix), `llm-compressor`/`autoawq` (AWQ), `gptqmodel` (GPTQ) | GGUF ladder is the spine of the study; AWQ/GPTQ are the cross-method comparison in §23 |
| Eval inference | `llama-server` (OpenAI-compatible) per rung; vLLM for AWQ/GPTQ | Swap rungs by restarting a server. Same client code for every rung. |
| Stats | `pandas` + `scipy` + bootstrap CIs | 500 items means a 3% difference may be noise. We need CIs or the curves are decoration. |
| Plots | `matplotlib` | Paper figures |
| Android | Kotlin + Jetpack Compose, minSdk 28 | — |
| On-device inference | **llama.cpp via our own thin JNI layer** | Critical: pin the *same llama.cpp commit* as the desktop eval, so phone results and bench results are apples-to-apples. A third-party wrapper breaks that. |
| On-device embeddings | Same llama.cpp runtime, embedding GGUF | One runtime, two models. Avoids shipping ONNX Runtime too. |
| On-device verifier | Pure Kotlin against the same SQLite file | Deterministic checks only (citation existence, numbers, scope). No Python on device. |

---

## 4. The build, in 8 blocks

The spec has 26 lifecycle steps. That's too many to hold in your head. Here they are grouped into 8 blocks, each with a clear "done" gate.

```
BLOCK 0  Foundations          spec §7            ~1 week
BLOCK 1  Knowledge layer      spec §8,9,10       ~3-4 weeks   ← the grind
BLOCK 2  Verifier             spec §11           ~1-2 weeks   ← the keystone
BLOCK 3  Dataset + Bench      spec §12-17        ~5-6 weeks   ← the bottleneck
BLOCK 4  Baselines + Model    spec §18-22        ~2-3 weeks
BLOCK 5  Compression study    spec §23-27        ~2-3 weeks   ← the research payload
BLOCK 6  Product (Android)    spec §20-24,28-32  ~3-4 weeks
BLOCK 7  Analysis + release   spec §33,37,38     ~2 weeks
```

Part-time (15-20 h/wk): **~5-6 months.** Full-time: **~10-12 weeks.**

---

### BLOCK 0 — Foundations

**What we build:** `docs/scope.md`, `docs/response-contract.md`, the repo skeleton, and a `uv` workspace that imports cleanly.

**Why it matters:** Spec §7 is blunt — "a stable research task requires a stable scope." Every downstream artifact (dataset, benchmark, verifier rules) encodes assumptions about what's in scope. If scope moves in month 3, the benchmark is invalid and the training data is mislabelled.

**Concretely, `docs/scope.md` must pin down:**
- The 5 verticals, and inside each, a closed list of *question categories* (e.g. consumer → `refund_refused`, `defective_product`, `delivery_failure`, `unfair_trade_practice`, `where_to_file`, `limitation_period`, …). ~8-12 categories per vertical, ~50 total.
- The out-of-scope list, with *near-miss* examples — "my landlord assaulted me" is tenancy-adjacent but criminal, so it must refuse-and-redirect.
- The clarification triggers: exactly when the model must ask for state / date / employment-type / policy-type before answering.
- The critical-omission catalogue: for each category, what *must* appear or the answer is dangerous (e.g. tenancy answers without a state caveat; gratuity answers without the continuous-service condition).

**Key decision I'm proposing here (extends the spec): make the response a strict JSON object, not prose.**

```json
{
  "in_scope": true,
  "needs_clarification": false,
  "clarifying_question": null,
  "answer_summary": "...",
  "what_the_law_says": "...",
  "citations": [{"act": "Consumer Protection Act, 2019", "section": "69", "supports": "..."}],
  "key_numbers": [{"claim": "...", "value": 2, "unit": "years", "fact_id": "..."}],
  "next_steps": ["..."],
  "caveats": ["..."],
  "escalation": {"authority": "...", "route": "..."},
  "disclaimer": "Information, not legal advice."
}
```

Why this is worth doing:
- The verifier gets citations and numbers **structurally**, not by regex-scraping prose. That removes an entire class of measurement error from your headline metrics.
- llama.cpp supports **GBNF grammar-constrained decoding**, so even the IQ2 rung is *guaranteed* to emit parseable JSON. Format collapse can't masquerade as reliability collapse.
- The Android app renders JSON → native UI. Much nicer than markdown-in-a-textview.
- Caveat: grammar constraints could *mask* degradation. So we evaluate **both** constrained and unconstrained at every rung — and "does structured decoding rescue low-bit models?" becomes a bonus finding.

**Done when:** `docs/scope.md` is written, you've read it and agreed, and the repo imports.

---

### BLOCK 1 — The knowledge layer (spec §8, §9, §10)

This is the least glamorous block and the one that determines whether the project is credible. Budget real time for it.

#### 1a. Corpus acquisition (`pr_corpus`)

**What:** Fetch authoritative primary sources for the 5 verticals, store the raw bytes untouched, record full provenance.

**Provenance record per source** (spec §8):
```
source_id, title, url, retrieved_at, sha256, jurisdiction,
publisher, doc_type (act|rules|regulation|notification|circular),
effective_from, effective_until, licence, snapshot_version
```

**Candidate sources per vertical** — all of these are *to be verified at fetch time*, not taken from this file as truth:

| Vertical | Primary sources to acquire |
|---|---|
| Consumer / e-commerce | Consumer Protection Act 2019; CP (E-Commerce) Rules 2020; CP (Jurisdiction…) Rules 2021; Legal Metrology (Packaged Commodities) Rules 2011 |
| Tenancy | Transfer of Property Act 1882 (ss.105-117); Model Tenancy Act 2021; **state** rent acts (start with 3-4: Delhi, Maharashtra, Karnataka, Tamil Nadu) |
| Traffic | Motor Vehicles Act 1988 (as amended 2019), Ch. XIII penalties; Central Motor Vehicles Rules 1989; **state compounding notifications** |
| Salary / PF / gratuity | Payment of Gratuity Act 1972; EPF & MP Act 1952; Payment of Wages Act 1936; Minimum Wages Act 1948; **Code on Wages 2019 + Social Security Code 2020** — see the temporal warning below |
| Insurance | Insurance Act 1938; IRDAI (Protection of Policyholders' Interests…) Regulations 2024; IRDAI master circulars on PPHI; Insurance Ombudsman Rules 2017 (as amended) |

**Portals:** India Code (`indiacode.nic.in`), e-Gazette (`egazette.gov.in`), IRDAI, EPFO, MoRTH/Parivahan, Dept. of Consumer Affairs, NCDRC, state legislature/law-department sites.

> ⚠️ **The single biggest legal-correctness risk in this project (spec §34.2).**
> India's four labour codes vs. the older Acts they subsume. My understanding is that the codes were brought into force on **21 Nov 2025** — but that is exactly the kind of claim this project exists to *not* take on faith. **Before writing a single employment training example, we establish from the Gazette which regime is in force at our snapshot date, and we never blend old Acts and new Codes in one answer.** If the picture is messy (partial commencement, rules pending), the honest move is to build the employment vertical *last*, or scope it to gratuity + EPF only, where continuity is clearest.

**Licence hygiene:** record the licence per source. Government text is generally reusable, but "generally" isn't a citation — check each portal's terms and log it. Crawl politely (rate-limit, cache, identify yourself).

**Stack:** `httpx` + `tenacity` for fetching, `trafilatura`/`selectolax` for HTML, `pymupdf` for PDFs, `pydantic` for the provenance model. Raw files land in `data/raw/<source_id>/<date>/`, manifest in JSON with SHA-256.

#### 1b. Statute store (`pr_store`) — spec §9

**What:** Parse raw sources into **one row per section**.

```sql
CREATE TABLE sections (
  section_uid     TEXT PRIMARY KEY,   -- "cpa2019.s69"
  act_id          TEXT NOT NULL,      -- "cpa2019"
  act_title       TEXT NOT NULL,      -- "Consumer Protection Act, 2019"
  section_number  TEXT NOT NULL,      -- "69", "69(1)", "2(7)"
  section_title   TEXT,
  text            TEXT NOT NULL,
  jurisdiction    TEXT NOT NULL,      -- "IN" | "IN-DL" | "IN-MH" ...
  doc_type        TEXT NOT NULL,
  effective_from  TEXT,
  effective_until TEXT,
  source_id       TEXT NOT NULL,
  retrieved_at    TEXT NOT NULL,
  content_hash    TEXT NOT NULL,
  corpus_version  TEXT NOT NULL
);
CREATE VIRTUAL TABLE sections_fts USING fts5(section_uid, act_title, section_title, text);
CREATE TABLE section_vectors (section_uid TEXT PRIMARY KEY, dim INT, vec BLOB);  -- int8
CREATE TABLE act_aliases (act_id TEXT, alias TEXT);  -- "CPA", "Consumer Protection Act"
```

**Why section-level is non-negotiable:** it buys three things at once (spec §9) — retrieval granularity, citable references, and **deterministic citation-existence checking**. When the model says "Act X, Section Y", you answer *exists / does not exist* with a SQL lookup, not another LLM.

The `act_aliases` table is what makes citation matching robust — the model will write "CPA 2019", "the Consumer Protection Act", "Consumer Protection Act, 2019". All must resolve to `cpa2019`.

**Expected size:** ~1,500-3,000 section rows, ~10-25 MB. Small enough to ship in the APK and to brute-force search. That's a genuinely nice property of this problem.

#### 1c. Facts table (`pr_store`) — spec §10

**What:** Every high-risk number, extracted once and verified by hand.

```sql
CREATE TABLE facts (
  fact_id, domain, act_id, section_uid, fact_type, value, unit,
  jurisdiction, effective_from, effective_until,
  source_quote,      -- the exact sentence it came from
  verified_by, verified_at, notes
);
```

`fact_type` examples: `limitation_period`, `pecuniary_jurisdiction`, `fine_amount`, `deposit_cap`, `notice_period`, `eligibility_years`, `contribution_rate`, `claim_settlement_deadline`, `ombudsman_limit`.

**Why:** numbers are the highest-hallucination-risk output and the easiest to check mechanically. This table *is* the ground truth for the Numeric Fidelity metric (§24.3).

**Process:** semi-automated extraction (regex + LLM proposal) → **human confirmation of every row against `source_quote`**. Expect 150-400 facts. This is a few days of careful work and it is not optional — spec §10 and §34.4 both say planning values are illustrative until verified.

**Done when:** you can run `pr-store query "refund not given by seller"` and get back real sections with citations, and every fact row has a verified `source_quote`.

---

### BLOCK 2 — The verifier (spec §11) — *build this before any dataset*

**What:** A library that takes a candidate answer (the JSON above) plus the retrieved context, and returns a structured pass/fail report.

Five checks, in order of how deterministic they are:

| Check | Method | Determinism |
|---|---|---|
| §11.1 Citation existence | SQL lookup in `sections` + `act_aliases` | 100% deterministic |
| §11.3 Numeric verification | Match `key_numbers[]` against `facts` on (domain, fact_type, jurisdiction, date) | ~100% deterministic |
| §11.4 Authority verification | Lookup in a curated `authorities` table (NCDRC/state commissions, RTO, EPFO, Insurance Ombudsman, National Consumer Helpline 1915, Bima Bharosa, e-Daakhil) | Deterministic |
| §11.5 Scope verification | Category classifier + rules from `scope.md`: should this have refused / asked for state? | Rules + small classifier |
| §11.2 Citation relevance | Does the cited section actually support the claim? Embedding similarity gate → judge model | **Not deterministic — must be calibrated (§25)** |

**Why this comes before the dataset:** spec §11 calls it "the quality gate between synthetic generation and training". If you generate 20,000 examples and *then* build the verifier, you throw most of them away. Build the gate first, then run generation through it.

**Design constraint that shapes the code:** checks 1, 3, 4, 5 must eventually run **in Kotlin on the phone** (spec §29). So write them as thin logic over SQL, with the rules stored as *data* (`rules.json`), not baked into Python control flow. Then the Kotlin port is a translation of ~300 lines, not a rewrite. Check 2 (relevance) stays research-only.

**Done when:** the verifier scores a hand-written set of ~30 deliberately-broken answers (fake sections, wrong numbers, missing state caveat, should-have-refused) exactly as you'd score them yourself.

---

### BLOCK 3 — Dataset and benchmark (spec §12 – §17)

#### 3a. Scenario matrix (§12)

**What:** Realistic citizen questions, not textbook questions. Varied along: domain × category × ambiguity × missing-facts × difficulty × persona × language style.

Target mix (from §16):
- 70% in-scope QA
- 15% out-of-scope refusal/redirect
- 10% clarification-required
- 5% multi-turn
- **~15% of all questions in romanized Hinglish** — answered in plain English

**Stack:** template-and-slot generation for coverage guarantees + LLM paraphrasing for naturalness + dedup by embedding similarity. Coverage is asserted programmatically: every (vertical × category × style) cell must be populated.

#### 3b. Teacher generation (§13)

**What:** For each scenario, retrieve the relevant sections, hand scenario + sections to a large **open** model, get back the structured JSON answer.

The teacher is a *generator*, not an oracle (§13). It never sees the facts table — it sees statute text and must ground in it.

#### 3c. Verify → repair → re-verify (§14)

```
generate → verifier → PASS → dataset
                    → FAIL → repair prompt (with the specific failure) → verifier again
                           → FAIL twice → reject, log the reason
```

Rejection reasons get logged and counted. If 40% of tenancy answers fail on missing state caveats, that's a bug in the *generation prompt*, not 40 bad examples to hand-fix. Spec §14: "synthetic data scales errors."

#### 3d. Pilot: 500 examples + human audit (§15)

**Do not skip this.** Generate ~500 spanning all verticals and all failure modes, then *you personally read a stratified sample* (~100) looking for: wrong citations, bad numbers, silent state assumptions, outdated regime, missing caveats, stilted language, unnecessary refusals, overconfidence.

Fix the *pipeline*, regenerate, re-audit. Two or three rounds is normal.

**Done when:** your audit finds <5% material defects in a fresh 100-sample draw.

#### 3e. Scale (§16)

Then generate 15,000-25,000 train + ~1,500 dev. Estimated teacher cost: **$30-60**.

#### 3f. PocketRights-Bench: the 500-item gold set (§17)

**This is the schedule bottleneck, and it's a human bottleneck, not a compute one.**

Spec §17 asks for 500 human-written, hand-verified items, never used in training. Done strictly, that is realistically **100-200 hours of your time** (write a realistic scenario → determine the correct answer → verify every citation and number → write the omission rubric).

Three honest options — **this is decision D4/D6 for you**:

| Option | Effort | Credibility |
|---|---|---|
| **A. Strict** — all 500 human-authored | 100-200 h | Highest. Publishable as a benchmark contribution. |
| **B. Tiered (recommended)** — 150 fully human-authored "core", 350 machine-drafted + human-verified-and-edited, each labelled | 40-70 h | High, *if* you report the split honestly and show core-vs-extended metrics agree |
| **C. Machine + spot-check** | 10 h | Weak. Undermines the whole "we measure reliability" thesis. |

I'd push for **B**, and report core-set and full-set numbers side by side.

Every bench item carries: question, domain, category, expected behaviour (`answer` / `clarify` / `refuse`), required citations, required numbers, **required-content rubric** (the critical-omission checklist), and a difficulty tag.

**Contamination control:** dedup bench against train by embedding cosine > 0.90 *and* 8-gram overlap. Run it as a CI check so it can't silently break.

---

### BLOCK 4 — Baselines and fine-tuning (spec §18 – §22)

#### 4a. Baselines first (§18) — *before you train anything*

| Baseline | Answers the question |
|---|---|
| Base model, zero-shot | How far does a stock 4B get? |
| Base model + RAG | **"Why fine-tune instead of just doing RAG?"** — the reviewer's first question |
| Fine-tuned, no RAG | Did specialization stick? |
| Fine-tuned + RAG | The shipping configuration |
| Frontier reference | An honest ceiling, clearly labelled as *not* the offline system |

Without these, no improvement can be attributed to anything (§18).

#### 4b. QLoRA (§19)

Starting config from the spec, to be validated not assumed:
- NF4 4-bit base, double quant, bf16 compute
- LoRA r=16, α=32, dropout 0.05, targets: all attention + MLP projections
- seq len 2048, effective batch ~32 via accumulation, grad checkpointing
- LR 1e-4 – 2e-4, cosine, warmup ~3%, 2-3 epochs
- **loss on completion tokens only** (this matters a lot for structured output)
- packing off initially

On an 8 GB card this fits but is slow (~10-14 h/run). For the *ablation grid* specifically, renting an L40S/A100 at ~$1-1.5/h turns each run into ~1.5-2 h; the whole grid costs $15-30. Worth it.

#### 4c. Ablations (§21)

- ± refusal/redirect examples → does refusal training cause **over-refusal**?
- ± explicit structured-citation training → does it improve citation validity?
- LoRA rank r ∈ {8, 16, 32} → how much adaptation capacity is actually needed?

DPO/RLHF is **explicitly out of scope** (§21) — it belongs to your separate RLHF project. Resist the temptation.

#### 4d. Evaluate and pick the reference model (§22)

Winner must improve in-domain reliability, keep refusal calibration sane, and not tank general ability (small MMLU/IFEval slices, §24.7).

---

### BLOCK 5 — The compression study (spec §23 – §27) — *the research payload*

#### 5a. Build the ladder (§23)

```
merged bf16 reference
  → F16 GGUF
  → Q8_0 → Q6_K → Q5_K_M → Q4_K_M → Q3_K_M → IQ2_M
plus, separately:  AWQ-INT4  and  GPTQ-INT4
```

IQ2-class needs an **importance matrix** (`llama-imatrix`). The calibration set is itself a design choice — generic text vs. a slice of PocketRights training data. Running both is one extra afternoon and gives you a real finding: *does domain-calibrated quantization preserve legal reliability better at 2 bits?*

#### 5b. The signature experiment (§26)

Same 500 questions, same retrieved context, same prompt, same decode settings, every rung.

**Non-obvious but critical: freeze the retrieval outputs.** Pre-compute the retrieved sections for each bench item once, store them in the bench file, and feed the identical context to every rung. Otherwise retrieval variance leaks into the compression curve and the whole result is muddy.

Decode settings: greedy (temp 0), fixed max tokens, fixed seed, one llama.cpp build for all rungs.

**Runs:** 7 rungs × 2 (grammar-constrained / free) × 2 (RAG / no-RAG) = 28 × 500 = 14,000 generations. On an M4 Pro or a 4060 that's roughly a day of wall-clock. Very manageable.

#### 5c. Metrics (§24) and stats

| Metric | How scored |
|---|---|
| Citation validity | Deterministic — SQL |
| Citation relevance | Judge model, calibrated |
| Numeric fidelity | Deterministic — facts table |
| Critical omissions | Rubric + judge |
| Hallucinated authority | Deterministic (authorities table) + judge for invented regs |
| Refusal calibration | Out-of-scope recall and in-scope over-refusal, **reported separately** |
| General capability retention | MMLU/IFEval slices |

With n=500 (and ~75 per vertical), a 3-point difference is often noise. So: **bootstrap 95% CIs (10k resamples)** on every metric, and **paired tests** (same items across rungs → McNemar / paired bootstrap) for rung-vs-rung claims. This is the difference between "a curve" and "a result."

#### 5d. Judge calibration (§25)

Judge from a different family than the teacher. Human-label ~150 gold items yourself. Report **Cohen's κ and raw agreement**. State the judge's error rate as a limitation. The spec is explicit: the judge is an instrument, not an oracle.

#### 5e. Hypotheses (§27)

H1 reliability degrades before fluency · H2 numbers are most fragile · H3 citations degrade at aggressive levels · H4 retrieval partially compensates · H5 fine-tuning + RAG are complementary.

Pre-register these in `docs/paper/hypotheses.md` **before** running the sweep. A disconfirmed hypothesis is a real result (§27); a hypothesis edited after seeing the data is not.

---

### BLOCK 6 — The product (spec §20, §21, §22, §23, §24)

#### 6a. Local RAG (§28)

Hybrid retrieval: FTS5 BM25 + dense cosine, fused with Reciprocal Rank Fusion, then a jurisdiction filter (if state is known, prefer state law + central; if unknown → trigger clarification), then top-k (4-6) sections into the context budget.

The retrieval corpus is versioned **separately from the model** (§28), so a corpus refresh doesn't require retraining.

#### 6b. On-device post-generation verification (§29)

```
generated JSON → citation check → numeric check → scope/safety check
                 PASS → render
                 FAIL → regenerate once → still FAIL → downgrade to
                        clarification, or a "can't verify this" refusal
```

The spec is emphatic: prefer uncertainty over a confident unsupported claim. The app should visibly show *"3 citations verified against Consumer Protection Act, 2019 (corpus snapshot 2026-08)"* — that badge is the whole product thesis in one UI element.

#### 6c. Android app (§30)

- Kotlin + Compose. Chat UI, structured answer cards, citation chips that open the actual section text, a persistent corpus-version + disclaimer footer.
- llama.cpp built with the NDK, **same commit as the eval harness**, thin JNI wrapper.
- Statute DB shipped as an APK asset (~10-25 MB). Model **not** in the APK (~2.5 GB) — one-time provisioning (ADB push for the demo, or a first-run download), then permanently offline.
- Threads pinned to big cores; mmap the model; `android:largeHeap`.

> ⚠️ **Feasibility flag:** 4B Q4_K_M ≈ 2.4-2.6 GB of weights plus KV cache, on a 6 GB phone that also runs Android. It's plausible but tight, and the OS may kill the process. Mitigations we should plan for from day one: quantized KV cache (q8_0/q4_0), short context, and a **fallback rung** — the ladder already tells us whether Q3_K_M at 4B or Q4 at a smaller model is the better trade. Real-device testing decides (§30), and "we measured that a 4B Q4 does not fit and here's what does" is a legitimate result, not a failure.

#### 6d. Airplane-mode demo (§31) and device benchmarks (§32)

Measure on the phone: disk size, peak RAM, TTFT, decode tok/s, end-to-end latency, sustained generation, thermal throttling, and task-level reliability. 3 runs each with cooldown. Reference environments: budget Android, Mac M4 Pro, RTX 4060, optionally Pi 5.

---

### BLOCK 7 — Production config, analysis, release (spec §33, §37, §38)

Pick the shipping configuration by **multi-objective trade-off**, not size (§33): if a rung is faster but loses numeric fidelity or citation validity, the bigger rung wins. Plot the Pareto frontier of reliability vs latency vs memory and justify the pick in writing.

Then: model card with the corpus snapshot date and explicit limitations, the "this model is not permanently current" statement (§34.3), the release version pinning corpus + model + llama.cpp commit, and the final write-up against the §38 Definition of Done checklist.

---

## 5. Risks, ranked

| # | Risk | Mitigation |
|---|---|---|
| R1 | **Gold set eats the schedule** (§17) | Decide tiering (§Block 3f) *now*, before generating anything |
| R2 | **Labour-code temporal ambiguity** (§34.2) | Establish the in-force regime from the Gazette first; consider building employment last or scoping to gratuity+EPF |
| R3 | **4B Q4 doesn't fit a 6 GB phone** (§30) | Plan the fallback rung from day one; treat the negative result as publishable |
| R4 | **Teacher produces subtly wrong legal *reasoning*** | The verifier catches citations/numbers, not reasoning. Cover with human audit + relevance judge + honest limitations section |
| R5 | **Bench contamination** | Automated dedup as a CI gate, not a one-time script |
| R6 | **Judge is wrong and you can't tell** (§25) | κ against human labels, reported as a limitation |
| R7 | **Scope creep into general legal advice** (§34.5) | `docs/scope.md` is version-controlled; expanding scope = a new project version |
| R8 | **Source portal changes / link rot** | `data/raw/` is immutable and hashed; every claim traces to a stored snapshot |
| R9 | **State-law variation swamps tenancy/traffic** | Clarification behaviour is a *trained skill*, not an afterthought; start with 3-4 states only |

**Estimated cloud spend, end to end: $150-300.** (Teacher ~$50, judge ~$50, GPU rental ~$100.)

---

## 6. Where we start

Block 0. Concretely, the first three artifacts:
1. `docs/scope.md` — the frozen scope
2. `docs/response-contract.md` — the JSON schema + disclaimer wording
3. `docs/sources.md` — the source registry with licence + snapshot plan

Nothing gets built until you've read and signed off on those three. That's the spec's own §7 discipline, and it's the cheapest hour in the project.
