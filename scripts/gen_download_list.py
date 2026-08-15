#!/usr/bin/env python3
"""Generate docs/download-list.md from the contracts.

The list is derived, never hand-written, so it cannot drift from
contracts/sources.yaml. Re-run it after any change to the registry:

    uv run python scripts/gen_download_list.py

Output lands in docs/, which is untracked by design — the registry is the
tracked artifact, this is just a readable view of it.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "download-list.md"

# Which categories each source is expected to serve. Hand-maintained, because
# only a human can say that the Jurisdiction Rules are what answer "which forum
# hears my claim". Verified against scope.yaml category ids at generation time.
SERVES: dict[str, list[str]] = {
    "cpa2019": ["consumer.defective_product", "consumer.refund_refused",
                "consumer.deficiency_in_service", "consumer.limitation_and_timeline",
                "consumer.compensation_and_relief", "consumer.unfair_trade_practice"],
    "ecommerce_rules_2020": ["consumer.delivery_failure", "consumer.platform_liability"],
    "cpa_jurisdiction_rules_2021": ["consumer.where_to_complain"],
    "lm_pc_rules_2011": ["consumer.warranty_dispute"],

    "tpa1882": ["tenancy.lock_in_notice", "tenancy.agreement_registration"],
    "mta2021": ["tenancy.security_deposit", "tenancy.rent_increase", "tenancy.eviction",
                "tenancy.landlord_entry", "tenancy.repairs_maintenance",
                "tenancy.where_to_complain"],
    "rent_dl": ["tenancy.rent_increase", "tenancy.eviction", "tenancy.utilities_charges"],
    "rent_mh": ["tenancy.rent_increase", "tenancy.eviction", "tenancy.utilities_charges"],
    "rent_ka": ["tenancy.rent_increase", "tenancy.eviction", "tenancy.utilities_charges"],

    "mva1988": ["traffic.document_offences", "traffic.helmet_seatbelt",
                "traffic.overspeeding", "traffic.vehicle_impound",
                "traffic.accident_immediate_steps", "traffic.licence_suspension",
                "traffic.drunk_driving", "traffic.where_to_complain"],
    "cmvr1989": ["traffic.document_offences"],
    "traffic_compounding_notifications": ["traffic.challan_amount",
                                          "traffic.compounding_payment"],

    "wages_code_2019": ["employment.unpaid_salary", "employment.minimum_wages",
                        "employment.bonus", "employment.payslip_deductions",
                        "employment.final_settlement"],
    "social_security_code_2020": ["employment.gratuity_eligibility",
                                  "employment.gratuity_calculation",
                                  "employment.pf_contribution", "employment.pf_withdrawal",
                                  "employment.maternity_benefits"],
    "gratuity1972": ["employment.gratuity_eligibility", "employment.gratuity_calculation"],
    "epf1952": ["employment.pf_contribution", "employment.pf_withdrawal"],
    "legacy_wage_acts": ["employment.unpaid_salary", "employment.minimum_wages",
                         "employment.bonus"],
    "ir_code_2020": ["employment.termination_notice", "employment.retrenchment",
                     "employment.resignation_notice", "employment.where_to_complain"],
    "osh_code_2020": ["employment.working_hours", "employment.leave_entitlement"],
    "id_act_1947": ["employment.termination_notice", "employment.retrenchment"],
    "maternity_1961": ["employment.maternity_benefits"],
    "posh2013": ["employment.workplace_harassment"],
    "posh_rules_2013": ["employment.workplace_harassment"],
    "shops_estab_dl": ["employment.working_hours", "employment.leave_entitlement",
                       "employment.appointment_terms"],
    "shops_estab_mh": ["employment.working_hours", "employment.leave_entitlement",
                       "employment.appointment_terms"],
    "shops_estab_ka": ["employment.working_hours", "employment.leave_entitlement",
                       "employment.appointment_terms"],
    "labour_codes_commencement_2025": [],

    "insurance1938": ["insurance.claim_rejected", "insurance.premium_lapse_revival",
                      "insurance.mis_selling"],
    "irdai_pphi_2024": ["insurance.claim_rejected", "insurance.claim_delay",
                        "insurance.cashless_authorisation", "insurance.free_look_cancellation",
                        "insurance.waiting_period", "insurance.motor_claim"],
    "irdai_pphi_master_circular": ["insurance.claim_delay",
                                   "insurance.cashless_authorisation"],
    "ombudsman_rules_2017": ["insurance.where_to_complain"],
}

PORTALS = {
    "indiacode": ("India Code", "https://www.indiacode.nic.in/"),
    "egazette": ("eGazette", "https://egazette.gov.in/"),
    "irdai": ("IRDAI — Legal → Regulations / Circulars", "https://irdai.gov.in/"),
    "doca": ("Dept of Consumer Affairs", "https://consumeraffairs.nic.in/"),
    "morth": ("MoRTH", "https://morth.nic.in/"),
    "labour": ("Ministry of Labour", "https://labour.gov.in/"),
    "epfo": ("EPFO", "https://www.epfindia.gov.in/"),
    "state_portal": ("State law / labour department portal", ""),
}

DOMAIN_ORDER = ["consumer", "tenancy", "traffic", "employment", "insurance"]


def acquired(source_id: str) -> str | None:
    base = ROOT / "data" / "raw" / source_id
    if not base.is_dir():
        return None
    snaps = sorted(p.name for p in base.iterdir() if p.is_dir())
    return snaps[-1] if snaps else None


def main() -> int:
    sources = yaml.safe_load((ROOT / "contracts/sources.yaml").read_text())
    scope = yaml.safe_load((ROOT / "contracts/scope.yaml").read_text())

    valid = {c["id"] for d in scope["domains"] for c in d["categories"]}
    for sid, cats in SERVES.items():
        for c in cats:
            if c not in valid:
                raise SystemExit(f"SERVES[{sid}] names unknown category '{c}'")

    by_domain: dict[str, list[dict]] = {}
    for s in sources["sources"]:
        by_domain.setdefault(s["domain"], []).append(s)

    done = [s for s in sources["sources"] if acquired(s["id"])]
    todo = [s for s in sources["sources"] if not acquired(s["id"])]

    L: list[str] = []
    add = L.append

    add("# Download list — what to get and how\n")
    add(f"**{len(todo)} documents remaining · {len(done)} acquired**\n")
    add("> Generated from `contracts/sources.yaml`. Do not edit by hand —")
    add("> re-run `uv run python scripts/gen_download_list.py`.\n")
    add("**States: Delhi, Maharashtra, Karnataka.**\n")
    add("---\n")

    # ---- how to download -------------------------------------------------
    add("## How to download\n")
    add("No portal allows automated downloading (IRDAI publishes `Disallow: /`;")
    add("India Code and labour.gov.in return 403 to anything that is not a")
    add("browser). So this part is you, in a browser.\n")
    add("### Download everything first, record it in one go\n")
    add("**1 — Save each PDF into `data/inbox/`, named after its `source_id`.**")
    add("The id is in the tables below, and `uv run pr-corpus names` prints the")
    add("full list of expected filenames.\n")
    add("```")
    add("data/inbox/cpa2019.pdf")
    add("data/inbox/mva1988.pdf")
    add("data/inbox/cpa2019.hi.pdf        <- Hindi companion, same source")
    add("data/inbox/mva1988__schedule.pdf <- a second file for one source")
    add("```\n")
    add("**2 — Preview.** This reads the folder and reports what it found;")
    add("it writes nothing.\n")
    add("```bash")
    add("uv run pr-corpus batch")
    add("```\n")
    add("It tells you, per file: which source it matched, page count, any")
    add('"As on" date it found in the text, whether the file looks scanned or')
    add("looks like a bundle of several documents, and whether the source is")
    add("use-gated. Unmatched files are listed with suggested ids — nothing is")
    add("ever matched by guesswork, because a wrong match writes a document into")
    add("the wrong Act's provenance chain.\n")
    add("**3 — Apply.**\n")
    add("```bash")
    add("uv run pr-corpus batch --apply")
    add("```\n")
    add("Each file is copied into `data/raw/<source_id>/<date>/`, hashed, and")
    add("given a provenance record. Re-running is safe: identical bytes are")
    add("recognised and skipped. Your originals in `data/inbox/` are untouched.\n")
    add("### One file at a time\n")
    add("If you would rather not rename, ingest individually:\n")
    add("```bash")
    add("uv run pr-corpus ingest --source cpa2019 --file data/inbox/whatever.pdf \\")
    add('  --url "https://the-url-you-actually-used"')
    add("```\n")
    add("Pass `--url` whenever you landed somewhere other than the link below, so")
    add("the provenance record reflects where the file actually came from.\n")
    add("Check progress any time with `uv run pr-corpus status`.\n")

    add("### Three things to watch\n")
    add("**Take `eng.pdf` when India Code offers it.** India Code serves two PDFs")
    add("per Act: `a1988-59.pdf` is the *original enactment*, `eng.pdf` is the")
    add("*consolidated current text* stamped \"As on \\<date\\>\". The consolidated")
    add("one includes amendments. Always prefer it.\n")
    add("**The \"As on\" date is detected automatically** where the document")
    add("states it, and recorded as `content_as_of` — a different field from when")
    add("you downloaded it. Conflating the two is how a model ends up implying it")
    add("knows current law when it does not. If `pr-corpus batch` does not find a")
    add("date and you can see one on the cover, tell me. The Consumer Protection")
    add("file we have is a July 2020 compilation.\n")
    add("**Grab the Hindi version wherever offered.** The Gazette publishes")
    add("authoritative Hindi alongside English — law, not translation. Ingest it")
    add("under the same `source_id`; the parser detects and tags language itself.")
    add("This is the parallel corpus hypothesis H7 depends on.\n")
    add("**Bundles are flagged for you.** The Consumer Protection download turned")
    add("out to hold eight documents in one bilingual 94-page PDF. `pr-corpus")
    add('batch` warns when a file is large enough to be a bundle; I write a bundle')
    add("map for those before parsing.\n")
    add("---\n")

    # ---- the documents ---------------------------------------------------
    add("## The documents\n")
    for domain in DOMAIN_ORDER:
        items = sorted(by_domain.get(domain, []), key=lambda s: (s["priority"], s["id"]))
        n_left = sum(1 for s in items if not acquired(s["id"]))
        title = next(d["title"] for d in scope["domains"] if d["id"] == domain)
        add(f"### {title} — {n_left} to get\n")
        add("| ✓ | source_id | Document | Where | Serves |")
        add("|---|---|---|---|---|")
        for s in items:
            snap = acquired(s["id"])
            tick = f"✅ {snap}" if snap else ("⭐" if s["priority"] == 1 else "")
            portal_name, portal_url = PORTALS.get(s["publisher"], (s["publisher"], ""))
            if s.get("url"):
                where = f"**[direct link]({s['url']})**"
            elif portal_url:
                where = f"[{portal_name}]({portal_url}) — search the title"
            else:
                where = portal_name
            cats = SERVES.get(s["id"], [])
            serves = (f"{len(cats)} categor{"y" if len(cats) == 1 else "ies"}"
                      if cats else "—")
            if s["id"] == "labour_codes_commencement_2025":
                serves = "**unblocks 10 gated sources**"
            title_txt = " ".join(s["title"].split())
            add(f"| {tick} | `{s['id']}` | {title_txt} | {where} | {serves} |")
        add("")

    # ---- priority order --------------------------------------------------
    add("---\n")
    add("## Suggested order\n")
    p1 = [s for s in todo if s["priority"] == 1]
    add(f"**Priority 1 first — {len(p1)} documents.** These carry the facts the")
    add("model is most often asked for.\n")
    add("1. **`labour_codes_commencement_2025`** — the four Gazette notifications of")
    add("   21 Nov 2025 plus each Code's repeal section. Closes task 7 and unblocks")
    add("   ten gated employment sources. Highest value document on the list.")
    add("2. The six with direct links above — fastest wins.")
    add("3. Remaining priority-1 documents.")
    add("4. Priority 2, then 3.")
    add("5. State laws last — hardest to find, fiddliest portals.\n")
    add("**If something defeats you, skip it and tell me which.** A missing")
    add("priority-3 source is not worth an hour of hunting.\n")

    # ---- gate ------------------------------------------------------------
    gate = next(
        b for b in sources["blocking_determinations"] if b["id"] == "labour_regime"
    )
    if gate["status"] != "resolved":
        add("---\n")
        add("## ⚠ The one document that unblocks the most\n")
        add("Ten employment sources are collectable but **cannot be loaded into the")
        add("store** until the labour-regime question is answered from primary")
        add("sources. Provisionally the four labour codes came into force")
        add("**21 November 2025** — but that rests on secondary summaries, and")
        add("sources conflict on whether the EPF Act specifically was repealed.\n")
        add("From **https://egazette.gov.in** (search by date), get:\n")
        add("- the four commencement notifications dated 21 November 2025")
        add("- the repeal-and-savings section of each Code (e.g. Social Security")
        add("  Code s.164) from India Code\n")
        add("Ingest them under `labour_codes_commencement_2025`. I read them, record")
        add("the answer, and the gate opens automatically.\n")
        add("**Why the care:** an answer citing a repealed Act states a real section")
        add("number with a real figure from the wrong regime. Citation-existence")
        add("passes. The numeric check passes. The answer is still wrong. Nothing")
        add("downstream catches it.\n")

    # ---- coverage ---------------------------------------------------------
    covered = {c for cats in SERVES.values() for c in cats}
    uncovered = sorted(valid - covered)
    add("---\n")
    add("## Coverage check\n")
    add(f"**{len(covered)} of {len(valid)} categories have at least one source.**\n")
    if uncovered:
        add("Categories with no source mapped — these will have no statutory")
        add("grounding, so either a source is missing or the category should go:\n")
        for c in uncovered:
            add(f"- `{c}`")
        add("")
    else:
        add("Every category in `contracts/scope.yaml` maps to at least one source.\n")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(L))
    print(f"wrote {OUT.relative_to(ROOT)}  ({len(todo)} to get, {len(done)} acquired)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
