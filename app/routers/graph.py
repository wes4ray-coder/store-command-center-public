"""Knowledge Graph (Graphify) — /api/graph/*

Wraps the `graphify` CLI (github.com/safishamsi/graphify): a queryable knowledge
graph of the whole repo (code + docs) — a real graph version of the book/bible.
The graph lives on disk in graphify-out/ (graph.json + GRAPH_TREE.html +
GRAPH_REPORT.md). These endpoints serve the viz, answer questions via BFS
traversal, and rebuild the graph. Because the store mounts every endpoint as an
MCP tool (localhost bypass), OpenClaw can query the graph too via `graph_query`.
"""
import os
import json
import subprocess
from pathlib import Path

from fastapi import APIRouter, Body, BackgroundTasks
from fastapi.responses import FileResponse, PlainTextResponse, JSONResponse, HTMLResponse

try:
    from config import BASE            # store code root (holds graphify-out/)
except Exception:
    BASE = Path(__file__).resolve().parent.parent

router = APIRouter()

GRAPHIFY = os.getenv("STORE_GRAPHIFY_BIN", str(Path(BASE).parent / "graphify-venv" / "bin" / "graphify"))
OUT = Path(BASE) / "graphify-out"
GRAPH_JSON = OUT / "graph.json"
_stats_cache = {"mtime": 0, "data": None}


def _have_graph():
    return GRAPH_JSON.exists()


def _stats():
    """Node/edge/community counts, cached by graph.json mtime (the file is big)."""
    if not _have_graph():
        return {"built": False}
    mt = GRAPH_JSON.stat().st_mtime
    if _stats_cache["data"] and _stats_cache["mtime"] == mt:
        return _stats_cache["data"]
    try:
        g = json.loads(GRAPH_JSON.read_text())
        nodes = g.get("nodes") or []
        edges = g.get("edges") or g.get("links") or []
        comms = {n.get("community") for n in nodes if isinstance(n, dict) and n.get("community")}
        data = {"built": True, "nodes": len(nodes), "edges": len(edges),
                "communities": len(comms), "updated": int(mt),
                "force_viz": True,   # generated live from graph.json (capped backbone), always available
                "tree_viz": (OUT / "GRAPH_TREE.html").exists()}
    except Exception as ex:
        data = {"built": True, "error": str(ex)}
    _stats_cache.update(mtime=mt, data=data)
    return data


@router.get("/api/graph/stats")
def graph_stats():
    return _stats()


_force_cache = {"mtime": 0, "n": 0, "html": None}


def _build_force_html(top_n: int = 300) -> str:
    """Self-contained force-directed picture of the graph's BACKBONE (top-N nodes by
    degree + the edges among them). graphify's own graph.html embeds ALL nodes inline
    (41k → vis-network never stabilizes → blank box); this caps to a renderable
    backbone, community-coloured, and regenerates from the live graph.json (cached by
    mtime). vis-network is loaded from unpkg (no CSP on the store)."""
    gc = _load_graph()
    if not gc:
        return "<html><body style='background:#0b0f16;color:#889;font:14px sans-serif;padding:24px'>Graph not built yet — hit Rebuild.</body></html>"
    nodes, deg, adj = gc["nodes"], gc["deg"], gc["adj"]
    top = sorted(nodes.keys(), key=lambda i: -deg.get(i, 0))[:max(50, top_n)]
    tops = set(top)

    def _hue(c):
        try:
            return (int(c) * 47) % 360
        except Exception:
            return abs(hash(str(c))) % 360

    vnodes = []
    for i in top:
        n = nodes[i]
        c = n.get("community")
        d = deg.get(i, 0)
        vnodes.append({
            "id": i, "label": n.get("label", i), "value": d,
            "color": f"hsl({_hue(c)},60%,58%)",
            "title": f"{n.get('label', i)} · deg {d} · {n.get('community_name') or ''} · {n.get('repo') or ''}".strip(" ·"),
        })
    seen, vedges = set(), []
    for i in top:
        for t, _rel, _conf in adj.get(i, []):
            if t in tops:
                k = (i, t) if i < t else (t, i)
                if k in seen:
                    continue
                seen.add(k)
                vedges.append({"from": i, "to": t})

    payload = json.dumps({"nodes": vnodes, "edges": vedges})
    total = len(nodes)
    return """<!doctype html><html><head><meta charset="utf-8">
<script src="https://unpkg.com/vis-network@9.1.6/standalone/umd/vis-network.min.js"></script>
<style>html,body{margin:0;height:100%;background:#0b0f16;overflow:hidden}
#net{width:100%;height:100vh}
#hint{position:fixed;left:10px;top:8px;color:#9fb0cc;font:12px/1.4 ui-sans-serif,sans-serif;background:rgba(11,15,22,.72);padding:4px 9px;border-radius:8px;z-index:9}
#load{position:fixed;left:50%;top:50%;transform:translate(-50%,-50%);color:#9fb0cc;font:13px sans-serif}</style></head>
<body><div id="hint">Backbone: __SHOWN__ highest-degree nodes of __TOTAL__ · drag to pan · scroll to zoom · use 🧭 Explore to slice a repo/folder</div>
<div id="load">laying out the graph…</div><div id="net"></div>
<script>
const DATA = __PAYLOAD__;
const nodes = new vis.DataSet(DATA.nodes.map(n => ({id:n.id,label:n.label,value:n.value,color:n.color,title:n.title})));
const edges = new vis.DataSet(DATA.edges.map((e,i) => ({id:i,from:e.from,to:e.to})));
const net = new vis.Network(document.getElementById('net'), {nodes,edges}, {
  nodes:{shape:'dot',scaling:{min:6,max:34,label:{enabled:true,min:9,max:22}},font:{color:'#dce6f7',strokeWidth:3,strokeColor:'#0b0f16'},borderWidth:0},
  edges:{color:{color:'rgba(130,160,205,.22)',highlight:'#8fb4ff'},width:.5,smooth:false},
  physics:{solver:'forceAtlas2Based',forceAtlas2Based:{gravitationalConstant:-42,springLength:90,springConstant:.05},stabilization:{iterations:220,updateInterval:25},timestep:.4},
  interaction:{hover:true,tooltipDelay:120,hideEdgesOnDrag:true}
});
net.once('stabilizationIterationsDone',()=>{document.getElementById('load').style.display='none';net.setOptions({physics:false});});
setTimeout(()=>{const l=document.getElementById('load');if(l)l.style.display='none';},6000);
</script></body></html>""".replace("__PAYLOAD__", payload).replace("__SHOWN__", str(len(vnodes))).replace("__TOTAL__", f"{total:,}")


@router.get("/api/graph/viz")
def graph_viz(kind: str = "graph", n: int = 300):
    """The interactive viz. kind='graph' → self-contained force-directed BACKBONE
    (top-N by degree, generated live from graph.json — renders at any graph size);
    kind='tree' → graphify's collapsible D3 tree (served from disk)."""
    if kind == "tree":
        tree = OUT / "GRAPH_TREE.html"
        if tree.exists():
            return FileResponse(str(tree), media_type="text/html")
        return PlainTextResponse("The tree viz hasn't been built yet — hit Rebuild.", status_code=404)
    # force graph — generate a capped, renderable backbone (cached by graph.json mtime + n)
    if not _have_graph():
        return PlainTextResponse("The graph hasn't been built yet — hit Rebuild.", status_code=404)
    mt = GRAPH_JSON.stat().st_mtime
    n = max(50, min(2000, n))
    if _force_cache["html"] is None or _force_cache["mtime"] != mt or _force_cache["n"] != n:
        _force_cache.update(mtime=mt, n=n, html=_build_force_html(n))
    return HTMLResponse(_force_cache["html"])


@router.get("/api/graph/report")
def graph_report():
    f = OUT / "GRAPH_REPORT.md"
    if not f.exists():
        return PlainTextResponse("No report yet — build the graph first.", status_code=404)
    return PlainTextResponse(f.read_text(), media_type="text/markdown")


@router.post("/api/graph/query")
def graph_query(body: dict = Body(...)):
    """Answer a question by traversing the graph (BFS). {q: '...', budget: 1500}.
    Also exposed to OpenClaw as an MCP tool."""
    q = (body.get("q") or body.get("question") or "").strip()
    if not q:
        return JSONResponse({"error": "missing 'q'"}, status_code=400)
    if not _have_graph():
        return JSONResponse({"error": "graph not built yet"}, status_code=409)
    budget = str(int(body.get("budget") or 1500))
    try:
        r = subprocess.run([GRAPHIFY, "query", q, "--budget", budget],
                           cwd=str(BASE), capture_output=True, text=True, timeout=90)
        out = r.stdout.strip() or r.stderr.strip()
        return {"ok": r.returncode == 0, "question": q, "answer": out}
    except subprocess.TimeoutExpired:
        return JSONResponse({"error": "query timed out"}, status_code=504)
    except FileNotFoundError:
        return JSONResponse({"error": f"graphify not installed at {GRAPHIFY}"}, status_code=500)


@router.post("/api/graph/explain")
def graph_explain(body: dict = Body(...)):
    """Plain-language explanation of one node + its neighbours. {node: 'choose_work()'}"""
    node = (body.get("node") or "").strip()
    if not node or not _have_graph():
        return JSONResponse({"error": "missing 'node' or graph not built"}, status_code=400)
    try:
        r = subprocess.run([GRAPHIFY, "explain", node], cwd=str(BASE),
                           capture_output=True, text=True, timeout=60)
        return {"ok": r.returncode == 0, "node": node, "answer": (r.stdout or r.stderr).strip()}
    except Exception as ex:
        return JSONResponse({"error": str(ex)}, status_code=500)


@router.post("/api/graph/path")
def graph_path(body: dict = Body(...)):
    """Shortest path between two nodes — 'how does A connect to B?'. {a, b}."""
    a, b = (body.get("a") or "").strip(), (body.get("b") or "").strip()
    if not a or not b or not _have_graph():
        return JSONResponse({"error": "need 'a' and 'b' and a built graph"}, status_code=400)
    try:
        r = subprocess.run([GRAPHIFY, "path", a, b], cwd=str(BASE),
                           capture_output=True, text=True, timeout=60)
        return {"ok": r.returncode == 0, "a": a, "b": b, "answer": (r.stdout or r.stderr).strip()}
    except Exception as ex:
        return JSONResponse({"error": str(ex)}, status_code=500)


@router.post("/api/graph/affected")
def graph_affected(body: dict = Body(...)):
    """Reverse traversal — 'what depends on / is impacted by X?'. {node, depth}."""
    node = (body.get("node") or "").strip()
    if not node or not _have_graph():
        return JSONResponse({"error": "need 'node' and a built graph"}, status_code=400)
    depth = str(int(body.get("depth") or 2))
    try:
        r = subprocess.run([GRAPHIFY, "affected", node, "--depth", depth], cwd=str(BASE),
                           capture_output=True, text=True, timeout=60)
        return {"ok": r.returncode == 0, "node": node, "answer": (r.stdout or r.stderr).strip()}
    except Exception as ex:
        return JSONResponse({"error": str(ex)}, status_code=500)


_graph_cache = {"mtime": 0, "nodes": None, "adj": None, "deg": None}


def _load_graph():
    """Parse graph.json once, cache by mtime, precompute degree + adjacency."""
    if not _have_graph():
        return None
    mt = GRAPH_JSON.stat().st_mtime
    if _graph_cache["nodes"] is not None and _graph_cache["mtime"] == mt:
        return _graph_cache
    g = json.loads(GRAPH_JSON.read_text())
    nodes = {n["id"]: n for n in (g.get("nodes") or []) if isinstance(n, dict) and n.get("id")}
    adj, deg = {}, {}
    for e in (g.get("links") or g.get("edges") or []):
        s, t = e.get("source"), e.get("target")
        if s in nodes and t in nodes:
            conf = e.get("confidence", "")
            adj.setdefault(s, []).append((t, e.get("relation", ""), conf))
            adj.setdefault(t, []).append((s, e.get("relation", ""), conf))
            deg[s] = deg.get(s, 0) + 1
            deg[t] = deg.get(t, 0) + 1
    _graph_cache.update(mtime=mt, nodes=nodes, adj=adj, deg=deg)
    return _graph_cache


def _node_out(nid, nodes, deg):
    n = nodes.get(nid, {})
    return {"id": nid, "label": n.get("label", nid), "community": n.get("community"),
            "community_name": n.get("community_name"), "kind": n.get("file_type"),
            "file": n.get("source_file"), "degree": deg.get(nid, 0)}


@router.get("/api/graph/scopes")
def graph_scopes():
    """Selectable slices for the explorer: top source directories + biggest communities."""
    gc = _load_graph()
    if not gc:
        return {"built": False}
    nodes, deg = gc["nodes"], gc["deg"]
    dirs, comms, repos = {}, {}, {}
    for n in nodes.values():
        # repo = top-level partition of a merged cross-repo graph (present after merge-graphs)
        rp = n.get("repo")
        if rp:
            repos[rp] = repos.get(rp, 0) + 1
        sf = n.get("source_file") or ""
        if "/" in sf:
            d = "/".join(sf.split("/")[:2]) if sf.count("/") > 1 else sf.split("/")[0]
            dirs[d] = dirs.get(d, 0) + 1
        cn = n.get("community_name")
        if cn:
            comms[cn] = comms.get(cn, 0) + 1
    top_repos = [{"scope": r, "count": c} for r, c in sorted(repos.items(), key=lambda kv: -kv[1])]
    top_dirs = [{"scope": d, "count": c} for d, c in sorted(dirs.items(), key=lambda kv: -kv[1])[:20]]
    top_comms = [{"scope": c, "count": n} for c, n in sorted(comms.items(), key=lambda kv: -kv[1])[:20]]
    return {"built": True, "repos": top_repos, "dirs": top_dirs, "communities": top_comms}


@router.get("/api/graph/subgraph")
def graph_subgraph(scope: str = "", by: str = "path", depth: int = 1, limit: int = 350):
    """A focused slice of the graph for the in-app force viewer.
    by='path' → nodes whose source_file starts with `scope`;
    by='community' → nodes in that community_name;
    by='ego' → `scope` node + neighbours out to `depth`.
    Capped at `limit` (highest-degree kept)."""
    gc = _load_graph()
    if not gc:
        return {"built": False}
    nodes, adj, deg = gc["nodes"], gc["adj"], gc["deg"]
    sel = set()
    if by == "ego" and scope:
        # match a node by id or label, BFS out to depth
        start = scope if scope in nodes else next((i for i, n in nodes.items() if n.get("label") == scope), None)
        if start:
            frontier, sel = {start}, {start}
            for _ in range(max(1, int(depth))):
                nxt = set()
                for nid in frontier:
                    for t, _r, _c in adj.get(nid, []):
                        if t not in sel:
                            nxt.add(t)
                sel |= nxt
                frontier = nxt
    elif by == "community" and scope:
        sel = {i for i, n in nodes.items() if n.get("community_name") == scope}
    elif by == "repo" and scope:
        sel = {i for i, n in nodes.items() if n.get("repo") == scope}
    else:  # path prefix
        sc = scope.strip()
        sel = {i for i, n in nodes.items() if (n.get("source_file") or "").startswith(sc)} if sc else set(nodes)
    # cap to the highest-degree nodes so the force layout stays readable
    if len(sel) > limit:
        sel = set(sorted(sel, key=lambda i: -deg.get(i, 0))[:limit])
    out_nodes = [_node_out(i, nodes, deg) for i in sel]
    seen, out_edges = set(), []
    for nid in sel:
        for t, rel, conf in adj.get(nid, []):
            if t in sel:
                key = tuple(sorted((nid, t))) + (rel,)
                if key not in seen:
                    seen.add(key)
                    out_edges.append({"source": nid, "target": t, "relation": rel, "confidence": conf})
    return {"built": True, "scope": scope, "by": by, "nodes": out_nodes, "edges": out_edges,
            "capped": len(out_nodes) >= limit}


@router.get("/api/graph/export")
def graph_export(scope: str = "", by: str = "path", limit: int = 2000):
    """Export a slice as GraphML (opens in Gephi / yEd / Cytoscape)."""
    sg = graph_subgraph(scope=scope, by=by, depth=2, limit=limit)
    if not sg.get("built"):
        return PlainTextResponse("graph not built", status_code=409)
    import html as _h
    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">',
             '<key id="label" for="node" attr.name="label" attr.type="string"/>',
             '<key id="community" for="node" attr.name="community" attr.type="string"/>',
             '<key id="kind" for="node" attr.name="kind" attr.type="string"/>',
             '<key id="degree" for="node" attr.name="degree" attr.type="int"/>',
             '<key id="relation" for="edge" attr.name="relation" attr.type="string"/>',
             '<key id="confidence" for="edge" attr.name="confidence" attr.type="string"/>',
             '<graph edgedefault="directed">']
    for n in sg["nodes"]:
        parts.append(f'<node id="{_h.escape(str(n["id"]))}">'
                     f'<data key="label">{_h.escape(str(n.get("label") or ""))}</data>'
                     f'<data key="community">{_h.escape(str(n.get("community_name") or ""))}</data>'
                     f'<data key="kind">{_h.escape(str(n.get("kind") or ""))}</data>'
                     f'<data key="degree">{int(n.get("degree") or 0)}</data></node>')
    for i, e in enumerate(sg["edges"]):
        parts.append(f'<edge id="e{i}" source="{_h.escape(str(e["source"]))}" target="{_h.escape(str(e["target"]))}">'
                     f'<data key="relation">{_h.escape(str(e.get("relation") or ""))}</data>'
                     f'<data key="confidence">{_h.escape(str(e.get("confidence") or ""))}</data></edge>')
    parts.append('</graph></graphml>')
    fname = (scope or "graph").replace("/", "_") + ".graphml"
    return PlainTextResponse("\n".join(parts), media_type="application/xml",
                             headers={"Content-Disposition": f'attachment; filename="{fname}"'})


_hl_cache = {"mtime": 0, "data": None}


@router.get("/api/graph/highlights")
def graph_highlights():
    """The 'god nodes' (most-connected concepts) + biggest communities — the map's
    landmarks. Cached by graph.json mtime (the file is big)."""
    if not _have_graph():
        return {"built": False}
    mt = GRAPH_JSON.stat().st_mtime
    if _hl_cache["data"] and _hl_cache["mtime"] == mt:
        return _hl_cache["data"]
    try:
        g = json.loads(GRAPH_JSON.read_text())
        nodes = {n["id"]: n for n in (g.get("nodes") or []) if isinstance(n, dict) and n.get("id")}
        deg = {}
        for e in (g.get("links") or g.get("edges") or []):
            for k in (e.get("source"), e.get("target")):
                if k is not None:
                    deg[k] = deg.get(k, 0) + 1
        top = sorted(deg.items(), key=lambda kv: -kv[1])[:24]
        gods = [{"id": nid, "label": nodes.get(nid, {}).get("label", nid),
                 "degree": d, "community": nodes.get(nid, {}).get("community_name"),
                 "file": nodes.get(nid, {}).get("source_file"),
                 "kind": nodes.get(nid, {}).get("file_type")} for nid, d in top if nid in nodes]
        # biggest communities by node count
        comm = {}
        for n in nodes.values():
            cn = n.get("community_name")
            if cn:
                comm[cn] = comm.get(cn, 0) + 1
        communities = [{"name": c, "size": s} for c, s in sorted(comm.items(), key=lambda kv: -kv[1])[:16]]
        data = {"built": True, "gods": gods, "communities": communities}
    except Exception as ex:
        data = {"built": True, "error": str(ex)}
    _hl_cache.update(mtime=mt, data=data)
    return data


_rebuild_state = {"running": False, "last": None}


def _rebuild_job():
    _rebuild_state["running"] = True
    try:
        r = subprocess.run([GRAPHIFY, "update", "."], cwd=str(BASE),
                           capture_output=True, text=True, timeout=1200)
        subprocess.run([GRAPHIFY, "tree", "--label", "The Company / Store"],
                       cwd=str(BASE), capture_output=True, text=True, timeout=300)
        tail = (r.stdout or r.stderr).strip().splitlines()[-1:] or [""]
        _rebuild_state["last"] = tail[0]
    except Exception as ex:
        _rebuild_state["last"] = f"error: {ex}"
    finally:
        _rebuild_state["running"] = False


@router.post("/api/graph/rebuild")
def graph_rebuild(background: BackgroundTasks):
    """Re-extract the code graph (AST, no LLM) + regenerate the tree viz. Runs in the background."""
    if _rebuild_state["running"]:
        return {"ok": True, "already": True}
    background.add_task(_rebuild_job)
    return {"ok": True, "started": True}


@router.get("/api/graph/rebuild/status")
def graph_rebuild_status():
    return _rebuild_state
