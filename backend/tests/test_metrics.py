from tests.test_documents_api import analyzed


def test_operational_metrics_follow_reviews(client):
    doc, body = analyzed(client)  # 1 automatic decision, 2 routed to review
    m = client.get("/metrics").json()
    assert (m["documents"], m["analyses"], m["decisions"], m["auto_decisions"]) == (1, 1, 3, 1)
    assert m["automation_rate"] == 1 / 3 and m["pending_reviews"] == 2 and m["override_rate"] is None
    assert m["clauses_analyzed"] == 3 and m["clauses_without_human"] == 2 / 3  # only clause 3 needs review

    pending = {d["rule_id"]: d["id"] for d in body["decisions"] if d["status"] == "pending"}
    client.post(f"/decisions/{pending['R-08']}/review", json={"action": "override", "reviewer": "dana", "reason": "wrong"})
    client.post(f"/decisions/{pending['R-01']}/review", json={"action": "approve", "reviewer": "dana"})

    m = client.get("/metrics").json()
    rules = {r["rule_id"]: r for r in m["rules"]}
    assert m["reviewed"] == 2 and m["override_rate"] == 0.5 and m["labels"] == 2
    assert rules["R-08"]["override_rate"] == 1.0 and rules["R-08"]["reviewer_precision"] == 0.0
    assert rules["R-01"]["override_rate"] == 0.0 and rules["R-01"]["reviewer_precision"] is None  # not a finding
    (today,) = m["volume"]
    assert (today["uploaded"], today["analyzed"], today["reviewed"]) == (1, 1, 2)


def test_eval_history_lists_saved_runs(client):
    runs = client.get("/metrics/evals").json()
    assert runs and runs == sorted(runs, key=lambda r: r["run_at"])
    final = [r for r in runs if r["split"] == "test_core" and r["pipeline"] == "v1+pf+fs+ver" and r["policy_version"] == 1]
    assert final and 0 < final[0]["precision"] <= 1 and "R-01" in final[0]["per_rule"]
