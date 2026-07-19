"""Research Lab — prompts/model-slot registration, endpoints, and an offline
run of the whole pipeline (LLM + web monkeypatched)."""
import json


# ── registry wiring ───────────────────────────────────────────────────────────
def test_research_prompts_registered():
    from prompts import get_prompt, PROMPTS
    for key in ("research_plan", "research_digest", "research_report",
                "research_review", "research_revise", "research_answer",
                "research_deeper", "research_suggest", "research_price"):
        assert len(get_prompt(key)) > 50, f"prompt {key} missing/empty"
    cats = {p.category for p in PROMPTS}
    assert "Research" in cats


def test_research_model_slot():
    import model_registry
    keys = {s["key"] for s in model_registry.REGISTRY}
    assert "research_model" in keys
    slot = [s for s in model_registry.REGISTRY if s["key"] == "research_model"][0]
    assert slot.get("fallback") == "enhance_model"
    # blank slot falls back to the global text model default
    assert model_registry.resolve("research_model") != ""


# ── endpoints ─────────────────────────────────────────────────────────────────
def test_overview_and_toggles(client):
    r = client.get("/api/research/overview")
    assert r.status_code == 200, r.text
    d = r.json()
    assert len(d["geniuses"]) == 3
    assert {g["name"] for g in d["geniuses"]} == {"Newton", "Curie", "Vinci"}
    for k in ("research_autostart", "research_images", "research_gen_images",
              "research_auto_library", "research_peer_review"):
        assert k in d["config"]


def test_specialty_assignment(client):
    import research_lab
    assert research_lab._assign_genius("Build a chicken coop", "wood frame", "build")["name"] == "Newton"
    assert research_lab._assign_genius("Start an Etsy side hustle", "sell crafts", "business")["name"] == "Vinci"
    assert research_lab._assign_genius("Compost and soil science for the garden", "", "")["name"] == "Curie"


def test_propose_list_detail_cancel_delete(client):
    # autostart OFF so no real pipeline thread ever runs in tests
    assert client.patch("/api/settings", json={"research_autostart": "off"}).status_code == 200
    r = client.post("/api/research/projects",
                    json={"title": "Build a chicken coop", "description": "for 6 hens"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["started"] is False and d["genius"] in ("Newton", "Curie", "Vinci")
    pid = d["id"]

    lst = client.get("/api/research/projects").json()["projects"]
    assert any(p["id"] == pid and p["status"] == "proposed" for p in lst)

    det = client.get(f"/api/research/projects/{pid}")
    assert det.status_code == 200
    assert det.json()["title"] == "Build a chicken coop"

    # no report yet
    assert client.get(f"/api/research/projects/{pid}/report").status_code == 400

    assert client.post(f"/api/research/projects/{pid}/cancel").status_code == 200
    assert client.get(f"/api/research/projects/{pid}").json()["status"] == "cancelled"

    assert client.delete(f"/api/research/projects/{pid}").status_code == 200
    assert client.get(f"/api/research/projects/{pid}").status_code == 404


def test_empty_title_rejected(client):
    assert client.post("/api/research/projects", json={"title": "  "}).status_code == 400


def test_media_endpoint_guards(client):
    assert client.get("/api/research/media/1/nope.png").status_code == 404
    assert client.get("/api/research/media/1/bad name.png").status_code == 400


# ── report rendering ──────────────────────────────────────────────────────────
def test_render_report_html_images_and_escaping():
    import research_lab
    md = ("## Overview\nA <script>alert(1)</script> plan.\n\n"
          "![coop diagram](/api/research/media/7/img1.jpg)\n")
    html = research_lab.render_report_html(md)
    assert "<script>" not in html
    assert '<img src="/store/api/research/media/7/img1.jpg"' in html or \
           '<img src="/api/research/media/7/img1.jpg"' in html
    assert "coop diagram" in html


# ── the whole pipeline, offline ───────────────────────────────────────────────
def test_pipeline_offline(client, monkeypatch):
    import research_lab
    import library

    plan = {"kind": "build", "overview": "A sturdy coop.",
            "sections": ["Overview", "Steps"], "search_queries": ["chicken coop plans"],
            "image_queries": ["chicken coop diagram"], "hero_image_prompt": "a coop",
            "safety": ["predator proofing"]}

    def fake_llm(prompt_key, user, max_tokens=1800, desc=""):
        if prompt_key == "research_plan":
            return json.dumps(plan)
        if prompt_key == "research_digest":
            return "- 2x4 lumber ~ $5 each\n- hardware cloth beats chicken wire"
        return ("## Overview\nBuild it well.\n\n## Step-by-step guide\n1. Frame the base.\n\n"
                "## Materials, parts & tools\n| Item | Qty | Est. cost |\n|---|---|---|\n"
                "| 2x4 lumber | 12 | $60 |\n\n## Safety notes\nMind the saw.\n" + "x" * 120)

    monkeypatch.setattr(research_lab, "_llm", fake_llm)
    monkeypatch.setattr(research_lab, "_searx",
                        lambda q, n=5, categories="": [{"title": "Coop guide",
                                                        "url": "http://example.com/coop",
                                                        "snippet": "how to build",
                                                        "img_src": ""}])
    monkeypatch.setattr(library, "fetch_readable_text",
                        lambda url: ("Coop guide", "lots of text about coops " * 40))
    filed = {}
    monkeypatch.setattr(library, "save_library_doc",
                        lambda cat, name, md_text: filed.update(
                            {"cat": cat, "name": name, "md": md_text}) or
                        {"category": cat, "path": "build-a-chicken-coop.md", "title": name})

    # web images off (no network); library filing on
    client.patch("/api/settings", json={"research_images": "off",
                                        "research_gen_images": "off",
                                        "research_auto_library": "on",
                                        "research_autostart": "off"})
    pid = client.post("/api/research/projects",
                      json={"title": "Build a chicken coop"}).json()["id"]

    research_lab._set(pid, status="running")
    research_lab._run_pipeline(pid)          # synchronous, fully offline

    p = research_lab._get(pid)
    assert p["status"] == "done", p["error"]
    assert p["progress"] == 100
    assert "Step-by-step guide" in p["report_md"]
    assert "## Sources" in p["report_md"]
    assert p["library_path"].startswith("research/")
    assert filed["cat"] == "research" and "chicken coop" in filed["name"].lower()

    det = client.get(f"/api/research/projects/{pid}").json()
    assert det["events"], "pipeline should write research_events"
    rep = client.get(f"/api/research/projects/{pid}/report").json()
    assert "Materials" in rep["html"]


# ── the "after the report" features (research_lab_deep), offline ──────────────
def _mk_done_project(client, title):
    import research_lab
    client.patch("/api/settings", json={"research_autostart": "off"})
    pid = client.post("/api/research/projects", json={"title": title}).json()["id"]
    research_lab._set(
        pid, status="done", progress=100,
        report_md="## Overview\nA fine coop.\n\n## Safety notes\nMind the saw.",
        notes='[{"url":"http://example.com","title":"Guide","digest":"- fact"}]',
        sources='[{"title":"Guide","url":"http://example.com","snippet":"s"}]')
    return pid


def test_specialty_assignment_endpoint_uses_kind(client):
    client.patch("/api/settings", json={"research_autostart": "off"})
    r = client.post("/api/research/projects",
                    json={"title": "Etsy shop branding", "kind": "business"}).json()
    assert r["genius"] == "Vinci"


def test_peer_review_revise_path(client, monkeypatch):
    import research_lab
    import research_lab_deep

    pid = _mk_done_project(client, "Peer review target")

    def fake_llm(key, user, max_tokens=1800, desc=""):
        if key == "research_review":
            return json.dumps({"verdict": "revise", "strengths": ["clear"],
                               "issues": ["costs are missing"],
                               "summary": "needs cost figures"})
        if key == "research_revise":
            return "## Overview\nRevised with costs.\n" + "x" * 300
        raise AssertionError(f"unexpected prompt {key}")

    monkeypatch.setattr(research_lab, "_llm", fake_llm)
    body = research_lab_deep.peer_review(pid, "## Overview\ndraft body\n" + "y" * 400)
    assert "Revised with costs" in body

    p = research_lab._get(pid)
    rv = json.loads(p["review"])
    assert rv["verdict"] == "revise" and rv["issues"]
    assert rv["reviewer"] != p["genius_name"], "a DIFFERENT Genius must review"
    # the review surfaces in the API rows
    det = client.get(f"/api/research/projects/{pid}").json()
    assert det["review"]["reviewer"] == rv["reviewer"]


def test_ask_the_genius(client, monkeypatch):
    import research_lab
    import research_lab_deep

    pid = _mk_done_project(client, "QA target")
    monkeypatch.setattr(research_lab_deep, "_spawn", lambda fn, *a: fn(*a))   # inline
    monkeypatch.setattr(research_lab, "_llm",
                        lambda key, user, max_tokens=1800, desc="":
                        "Use **hardware cloth**, not chicken wire.")

    r = client.post(f"/api/research/projects/{pid}/ask",
                    json={"question": "wire or hardware cloth?"})
    assert r.status_code == 200, r.text

    det = client.get(f"/api/research/projects/{pid}").json()
    assert det["qa"] and det["qa"][0]["status"] == "answered"
    assert "hardware cloth" in det["qa"][0]["answer"]
    assert det["qa"][0]["answer_html"]

    # guards: empty question / project without a report
    assert client.post(f"/api/research/projects/{pid}/ask",
                       json={"question": "  "}).status_code == 400
    pid2 = client.post("/api/research/projects", json={"title": "no report yet"}).json()["id"]
    assert client.post(f"/api/research/projects/{pid2}/ask",
                       json={"question": "hm?"}).status_code == 400
    # deleting the project sweeps its Q&A
    client.delete(f"/api/research/projects/{pid}")
    from db import get_conn
    conn = get_conn()
    assert conn.execute("SELECT COUNT(*) FROM research_qa WHERE project_id=?",
                        (pid,)).fetchone()[0] == 0
    conn.close()


def test_dig_deeper(client, monkeypatch):
    import research_lab
    import research_lab_deep
    import library

    client.patch("/api/settings", json={"research_auto_library": "off",
                                        "research_peer_review": "off"})
    pid = _mk_done_project(client, "Deeper target")

    def fake_llm(key, user, max_tokens=1800, desc=""):
        if key == "research_deeper":
            return json.dumps({"search_queries": ["coop insulation"],
                               "focus_note": "insulation"})
        if key == "research_digest":
            return "- foam board R-5 ~ $20"
        if key == "research_report":
            assert "PREVIOUS REPORT" in user and "DEEPER-PASS" in user
            return ("## Overview\nDeeper and better.\n\n"
                    "## Materials, parts & tools\nfoam board.\n" + "z" * 200)
        raise AssertionError(f"unexpected prompt {key}")

    monkeypatch.setattr(research_lab, "_llm", fake_llm)
    monkeypatch.setattr(research_lab, "_searx",
                        lambda q, n=5, categories="": [{"title": "Insulation guide",
                                                        "url": "http://example.com/insul",
                                                        "snippet": "warm", "img_src": ""}])
    monkeypatch.setattr(library, "fetch_readable_text",
                        lambda url: ("Insulation guide", "insulating a coop " * 60))

    # endpoint guards
    assert client.post("/api/research/projects/999999/deeper", json={}).status_code == 404
    pid2 = client.post("/api/research/projects", json={"title": "no report"}).json()["id"]
    assert client.post(f"/api/research/projects/{pid2}/deeper", json={}).status_code == 400

    research_lab._set(pid, status="running")
    research_lab_deep._run_deeper(pid, "insulation")     # synchronous, fully offline

    p = research_lab._get(pid)
    assert p["status"] == "done", p["error"]
    assert p["version"] == 2
    assert "Deeper and better" in p["report_md"]
    srcs = json.loads(p["sources"])
    assert any("insul" in (s.get("url") or "") for s in srcs), "new sources must be merged in"


# ── the market layer: materials → Money tab, price watch, recurrence ──────────
_MAT_MD = ("## Overview\nBuild it.\n\n"
           "## Materials, parts & tools\n"
           "| Item | Qty | Est. cost |\n"
           "|---|---|---|\n"
           "| 2x4 lumber | 12 | $60 |\n"
           "| Hardware cloth | 1 roll | $45.50 |\n"
           "| Misc screws | 1 box | — |\n"
           "| **Total** | | ~$110 |\n\n"
           "## Safety notes\nCareful.")


def test_parse_materials():
    import research_lab_market as mkt
    mats = mkt.parse_materials(_MAT_MD)
    assert [m["item"] for m in mats] == ["2x4 lumber", "Hardware cloth", "Misc screws"]
    assert mats[0]["cost"] == 60.0 and mats[1]["cost"] == 45.5 and mats[2]["cost"] is None
    assert mkt.parse_materials("## Overview\nno table here") == []


def test_materials_to_money_and_baseline(client):
    import research_lab
    import research_lab_market as mkt

    pid = _mk_done_project(client, "Market target")
    research_lab._set(pid, report_md=_MAT_MD)
    mkt.after_report(pid)          # baseline snapshot + Money-tab filing (toggle on)

    info = mkt.market_info(pid)
    assert info["filed"] == 3, "all materials (even cost-less ones) become shop searches"
    assert len(info["runs"]) == 1 and info["runs"][0]["kind"] == "report"
    assert info["runs"][0]["total"] == 105.5
    assert mkt.file_to_money(pid) == 0, "re-filing must dedup"

    from db import get_conn
    conn = get_conn()
    sig = conn.execute(
        "SELECT * FROM money_signals WHERE source='research' AND query=? AND meta LIKE ?",
        ("2x4 lumber", f'%"project_id": {pid},%')).fetchone()
    conn.close()
    assert sig, "the material must land in money_signals tagged with its project"
    import json as _j
    assert _j.loads(sig["meta"])["est_cost"] == 60.0

    r = client.get(f"/api/research/projects/{pid}/market")
    assert r.status_code == 200 and r.json()["filed"] == 3


def test_price_check_and_recurrence(client, monkeypatch):
    import research_lab
    import research_lab_market as mkt

    pid = _mk_done_project(client, "Recur target")
    research_lab._set(pid, report_md=_MAT_MD)
    mkt.snapshot_report_prices(pid)

    monkeypatch.setattr(research_lab, "_searx",
                        lambda q, n=5, categories="": [{"title": "Store", "url": "http://x",
                                                        "snippet": "great price",
                                                        "img_src": ""}])
    monkeypatch.setattr(research_lab, "_llm",
                        lambda key, user, max_tokens=1800, desc="": json.dumps(
                            {"prices": [{"item": "2x4 lumber", "price": 72.0},
                                        {"item": "Hardware cloth", "price": None}]}))
    mkt._run_price_check(pid)      # synchronous, fully offline

    info = mkt.market_info(pid)
    assert len(info["runs"]) == 2 and info["runs"][1]["kind"] == "check"
    # carry-forward total: lumber re-priced to 72, cloth keeps its 45.50 baseline
    assert info["runs"][1]["total"] == 117.5
    assert len(info["series"]["2x4 lumber"]) == 2

    # recurrence: endpoint sets cadence, scheduler tick starts due projects
    assert client.post(f"/api/research/projects/{pid}/recur",
                       json={"days": 7}).status_code == 200
    p = research_lab._get(pid)
    assert p["recur_days"] == 7 and p["next_run_at"]

    research_lab._set(pid, next_run_at="2020-01-01 00:00:00")   # make it due
    calls = []
    monkeypatch.setattr(mkt, "start_price_check", lambda i: calls.append(i) or True)
    r = mkt.recur_tick()
    assert calls == [pid] and r["started"] == [pid]
    p = research_lab._get(pid)
    assert p["next_run_at"] > "2026-01-01", "next_run_at must be bumped into the future"

    assert client.post(f"/api/research/projects/{pid}/recur",
                       json={"days": 999}).status_code == 400
    assert client.post(f"/api/research/projects/{pid}/recur",
                       json={"days": 0}).status_code == 200
    assert research_lab._get(pid)["recur_days"] == 0


def test_price_drop_alerts(client, monkeypatch):
    import research_lab
    import research_lab_market as mkt

    pid = _mk_done_project(client, "Alert target")
    research_lab._set(pid, report_md=_MAT_MD)
    mkt.snapshot_report_prices(pid)            # lumber baseline $60

    monkeypatch.setattr(research_lab, "_searx",
                        lambda q, n=5, categories="": [{"title": "Store", "url": "http://x",
                                                        "snippet": "sale", "img_src": ""}])
    monkeypatch.setattr(research_lab, "_llm",
                        lambda key, user, max_tokens=1800, desc="": json.dumps(
                            {"prices": [{"item": "2x4 lumber", "price": 42.0}]}))   # −30%
    mkt._run_price_check(pid)

    info = mkt.market_info(pid)
    assert len(info["alerts"]) == 1
    a = info["alerts"][0]
    assert a["item"] == "2x4 lumber" and a["price"] == 42.0 and a["pct"] == 30.0

    from db import get_conn
    conn = get_conn()
    board = conn.execute("SELECT * FROM world_messages WHERE kind='research' "
                         "AND text LIKE '%Buy window%' ORDER BY id DESC LIMIT 1").fetchone()
    sig = conn.execute("SELECT * FROM money_signals WHERE source='research-alert' "
                       "AND query LIKE '2x4 lumber%'").fetchall()
    conn.close()
    assert board, "the buy window must land on the God Console community board"
    assert len(sig) == 1

    # same price again → no duplicate alert; a further big drop → fresh alert
    mkt._run_price_check(pid)
    assert len(mkt.market_info(pid)["alerts"]) == 1
    monkeypatch.setattr(research_lab, "_llm",
                        lambda key, user, max_tokens=1800, desc="": json.dumps(
                            {"prices": [{"item": "2x4 lumber", "price": 30.0}]}))   # −50%
    mkt._run_price_check(pid)
    assert len(mkt.market_info(pid)["alerts"]) == 2

    # threshold respected: a small dip stays quiet
    client.patch("/api/settings", json={"research_price_alert_pct": "40"})
    monkeypatch.setattr(research_lab, "_llm",
                        lambda key, user, max_tokens=1800, desc="": json.dumps(
                            {"prices": [{"item": "Hardware cloth", "price": 40.0}]}))  # −12%
    mkt._run_price_check(pid)
    assert len(mkt.market_info(pid)["alerts"]) == 2
    client.patch("/api/settings", json={"research_price_alert_pct": "10"})


def test_suggest_ideas(client, monkeypatch):
    import research_lab
    monkeypatch.setattr(research_lab, "_llm",
                        lambda key, user, max_tokens=1800, desc="": json.dumps(
                            {"ideas": [{"title": "Build a cold frame",
                                        "description": "Extend the growing season.",
                                        "kind": "build"},
                                       {"title": "", "description": "dropped — no title"}]}))
    r = client.post("/api/research/suggest", json={"theme": "garden"})
    assert r.status_code == 200
    ideas = r.json()["ideas"]
    assert len(ideas) == 1 and ideas[0]["title"] == "Build a cold frame"
