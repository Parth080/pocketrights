# data/inbox — drop zone

Put hand-downloaded source documents here, then record them:

```bash
uv run pr-corpus ingest --source <source_id> --file data/inbox/<file>
```

The URL and metadata come from `contracts/sources.yaml`, so you usually don't
need to pass anything else.

Ingest **copies** the file into `data/raw/<source_id>/<date>/` with a hash and a
provenance record. What's left here is just your download — safe to delete
afterwards, and not tracked in git.

Why files land here by hand: none of the primary publishers allow automated
downloading. IRDAI publishes `Disallow: /`; India Code and labour.gov.in return
403 to anything that isn't a browser. See `docs/acquisition-guide.md`.
