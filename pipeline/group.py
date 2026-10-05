"""Stage 4 - GROUP (code membership + small-model naming).

Code owns membership: every completed complaint/cancellation record joins exactly
one issue, keyed by its fixed (topic, subtopic) labels, so issue IDs are stable
and re-ranking needs no model. A small model only names each issue from a
bounded, deterministic evidence pack and rates coherence; its names are saved in
group_mapping.json and never change membership.
"""
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from . import common, config, db, llm


def issue_id(topic, subtopic):
    return f"ISS-{topic}-{subtopic}"


def build_membership(records):
    members = defaultdict(list)
    for r in records:
        if r["status"] == "completed" and r["intent"] in ("complaint", "cancellation"):
            members[issue_id(r["topic"], r["subtopic"])].append(r["review_id"])
    return {k: sorted(v) for k, v in sorted(members.items())}


def evidence_pack(members, recs_by_id, k):
    """Deterministic examples: distinct quotes ordered by sha256(issue_id:review_id)."""
    pack = {}
    for iid, ids in members.items():
        seen, ex = set(), []
        for rid in sorted(ids, key=lambda r: hashlib.sha256(f"{iid}:{r}".encode()).hexdigest()):
            q = recs_by_id[rid]["evidence_quote"].strip()
            if q.lower() in seen or len(q) < 4:
                continue
            seen.add(q.lower())
            ex.append({"review_id": rid, "quote": q[:300]})
            if len(ex) >= k:
                break
        pack[iid] = ex
    return pack


def run_group(con, run_dir, run_id, records, budget, client=None):
    out = Path(run_dir) / "outputs"
    members = build_membership(records)
    recs_by_id = {r["review_id"]: r for r in records}
    rows = [(iid, rid) for iid, ids in members.items() for rid in ids]
    common.write_csv(out / "membership.csv", ["issue_id", "review_id"], rows)
    pack = evidence_pack(members, recs_by_id, config.GROUP["examples_per_issue"])
    pack_json = json.dumps({"prompt": config.GROUP["prompt_version"], "model": config.GROUP["model"], "pack": pack},
                           sort_keys=True, ensure_ascii=False)
    pack_hash = hashlib.sha256(pack_json.encode()).hexdigest()
    common.write_json(out / "group_evidence_pack.json", {"sha256": pack_hash, "pack": pack})
    mapping_path = out / "group_mapping.json"
    if mapping_path.exists() and json.loads(mapping_path.read_text()).get("evidence_pack_sha256") == pack_hash:
        print("[group] evidence pack unchanged -> reusing saved issue names (0 model calls)")
        return json.loads(mapping_path.read_text())

    client = client or llm.get_client()
    system = common.load_prompt("group_v1.md")
    ledger = llm.Ledger(budget)
    names = {}
    iids = list(members)
    for start in range(0, len(iids), 10):  # bounded: 10 issues x <=12 quotes per request
        chunk = iids[start:start + 10]
        user = "\n\n".join(
            f"ISSUE {iid} (topic={iid.split('-')[1]}, subtopic={iid.split('-', 2)[2]})\n" +
            "\n".join(f"- \"{e['quote']}\"" for e in pack[iid]) for iid in chunk)
        sent_ids = [e["review_id"] for iid in chunk for e in pack[iid]]
        text, recs = llm.call(client, config.GROUP, system, user, config.GROUP["max_output_tokens"], sent_ids, ledger,
                              {"role": "group", "run_id": run_id, "phase": "group",
                               "label_config": f"{config.GROUP['model']}+{config.GROUP['prompt_version']}",
                               "artifact": "outputs/group_evidence_pack.json"}, cache_system=False)
        with db.tx(con):
            for r in recs:
                db.insert_call(con, r)
        for line in (text or "").splitlines():
            parts = [p.strip() for p in line.split("|")]
            if len(parts) == 4 and parts[0] in chunk and parts[2] in {"high", "mixed", "low"}:
                names[parts[0]] = {"name": parts[1][:80], "coherence": parts[2], "note": parts[3][:200]}
    mapping = {"evidence_pack_sha256": pack_hash, "model": config.GROUP["model"],
               "prompt_version": config.GROUP["prompt_version"], "issues": {}}
    for iid, ids in members.items():
        n = names.get(iid) or {"name": iid.split("-", 2)[2].replace("_", " "), "coherence": "unrated",
                               "note": "model name missing; code fallback name"}
        mapping["issues"][iid] = dict(n, members=len(ids), example_review_ids=[e["review_id"] for e in pack[iid]])
    common.write_json(mapping_path, mapping)
    print(f"[group] {len(members)} issues, {len(rows)} memberships, named {len(names)}/{len(members)} by model")
    return mapping
