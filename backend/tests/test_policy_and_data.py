"""Guards on the policy, the hand-labeled edge cases, and the frozen splits."""

import json
from collections import Counter

import pytest
import yaml

from app.config import get_settings
from app.policy import load_policy

DATA = get_settings().data_dir
CUAD_CATEGORIES = {
    "Document Name", "Parties", "Agreement Date", "Effective Date", "Expiration Date",
    "Renewal Term", "Notice Period To Terminate Renewal", "Governing Law", "Most Favored Nation",
    "Non-Compete", "Exclusivity", "No-Solicit Of Customers", "Competitive Restriction Exception",
    "No-Solicit Of Employees", "Non-Disparagement", "Termination For Convenience", "Rofr/Rofo/Rofn",
    "Change Of Control", "Anti-Assignment", "Revenue/Profit Sharing", "Price Restrictions",
    "Minimum Commitment", "Volume Restriction", "Ip Ownership Assignment", "Joint Ip Ownership",
    "License Grant", "Non-Transferable License", "Affiliate License-Licensor",
    "Affiliate License-Licensee", "Unlimited/All-You-Can-Eat-License",
    "Irrevocable Or Perpetual License", "Source Code Escrow", "Post-Termination Services",
    "Audit Rights", "Uncapped Liability", "Cap On Liability", "Liquidated Damages",
    "Warranty Duration", "Insurance", "Covenant Not To Sue", "Third Party Beneficiary",
}

policy = load_policy(1)
rule_ids = {r.id for r in policy.rules}
edge_cases = yaml.safe_load((DATA / "edge_cases.yaml").read_text(encoding="utf-8"))["cases"]


def test_policy_maps_only_real_cuad_categories():
    assert {c for r in policy.rules for c in r.cuad_categories} <= CUAD_CATEGORIES


def test_edge_cases_are_valid():
    ids = [c["id"] for c in edge_cases]
    assert len(ids) == len(set(ids))
    for c in edge_cases:
        assert c["split"] in {"dev", "test"}
        assert set(c["rule_ids"]) <= rule_ids
        assert c["rationale"].strip()


def test_edge_cases_cover_every_rule_in_both_splits():
    # Each block of four cases targets one rule; count positives and negatives per split.
    per_split = Counter(c["split"] for c in edge_cases)
    assert per_split["dev"] == per_split["test"] == 2 * len(rule_ids)
    for split in ("dev", "test"):
        positives = {r for c in edge_cases if c["split"] == split for r in c["rule_ids"]}
        assert positives == rule_ids, f"{split} is missing positives for {rule_ids - positives}"


def test_edge_cases_do_not_leak_policy_examples():
    examples = {e for r in policy.rules for e in r.matches + r.does_not_match}
    assert not examples & {c["text"] for c in edge_cases}


@pytest.fixture(scope="module")
def splits():
    path = DATA / "processed" / "splits.json"
    if not path.exists():
        pytest.skip("run scripts.build_dataset first")
    return json.loads(path.read_text(encoding="utf-8"))


def test_splits_are_disjoint_and_complete(splits):
    dev, test = set(splits["dev"]), set(splits["test"])
    assert not dev & test
    assert len(dev) == 408 and len(test) == 102
    assert set(splits["dev_core"]) <= dev
    assert set(splits["test_core"]) <= test
