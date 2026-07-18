"""Turntable rendering of 3D meshes to PNG — CPU-only, headless.

Loads STL/OBJ/3MF/GLB/PLY via trimesh and renders shaded views from several
angles with matplotlib (no OpenGL needed, works on a headless server). Good
enough for listing thumbnails; the actual mesh the buyer downloads is unchanged.

Heavy imports (trimesh, matplotlib, numpy) are done lazily so importing this
module never slows app startup.
"""
from pathlib import Path
import zipfile
import tempfile

# Extensions trimesh can load directly as a mesh.
_MESH_EXTS = {".stl", ".obj", ".3mf", ".glb", ".gltf", ".ply", ".off"}


def _extract_mesh_from_zip(zip_path: Path) -> Path | None:
    """Return the first loadable mesh inside a ZIP, extracted to a temp file."""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for name in zf.namelist():
                ext = Path(name).suffix.lower()
                if ext in _MESH_EXTS:
                    tmpdir = Path(tempfile.mkdtemp(prefix="m3d_"))
                    out = tmpdir / Path(name).name
                    with zf.open(name) as src, open(out, "wb") as dst:
                        dst.write(src.read())
                    return out
    except Exception:
        return None
    return None


def render_turntable(src_path: str, out_dir: str, prefix: str,
                     angles=(30, 120, 210, 300), elev: float = 25.0,
                     size: int = 768) -> list[str]:
    """Render `src_path` from several azimuth angles. Returns list of PNG paths.

    Raises RuntimeError with a readable message on failure (unloadable mesh, etc).
    """
    import numpy as np
    import trimesh
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    src = Path(src_path)
    if not src.exists():
        raise RuntimeError(f"file not found: {src}")

    load_path = src
    if src.suffix.lower() == ".zip":
        extracted = _extract_mesh_from_zip(src)
        if not extracted:
            raise RuntimeError("no loadable mesh (.stl/.obj/.3mf/.glb) inside the ZIP")
        load_path = extracted

    scene_or_mesh = trimesh.load(str(load_path), force="mesh")
    if isinstance(scene_or_mesh, trimesh.Scene):
        geoms = list(scene_or_mesh.geometry.values())
        if not geoms:
            raise RuntimeError("mesh contained no geometry")
        mesh = trimesh.util.concatenate(geoms)
    else:
        mesh = scene_or_mesh
    if mesh is None or len(mesh.faces) == 0:
        raise RuntimeError("could not read any faces from the mesh")

    # Center + scale to a unit-ish box so the framing is consistent.
    verts = mesh.vertices - mesh.center_mass if mesh.is_watertight else mesh.vertices - mesh.vertices.mean(axis=0)
    scale = float(np.abs(verts).max()) or 1.0
    verts = verts / scale
    faces = mesh.faces

    # Simple lambert-ish shading from face normals for depth cues.
    tris = verts[faces]
    normals = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    nlen = np.linalg.norm(normals, axis=1, keepdims=True)
    nlen[nlen == 0] = 1.0
    normals = normals / nlen
    light = np.array([0.3, 0.4, 0.85])
    shade = np.clip(np.abs(normals @ light), 0.25, 1.0)
    base = np.array([0.42, 0.45, 0.78])  # muted indigo, matches app accent
    facecolors = np.clip(shade[:, None] * base[None, :], 0, 1)

    out_paths: list[str] = []
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    for i, azim in enumerate(angles):
        fig = plt.figure(figsize=(size / 100, size / 100), dpi=100)
        ax = fig.add_subplot(111, projection="3d")
        coll = Poly3DCollection(tris, facecolors=facecolors, edgecolors="none",
                                linewidths=0, antialiased=True)
        ax.add_collection3d(coll)
        ax.set_xlim(-0.7, 0.7); ax.set_ylim(-0.7, 0.7); ax.set_zlim(-0.7, 0.7)
        ax.set_box_aspect((1, 1, 1))
        ax.view_init(elev=elev, azim=azim)
        ax.set_axis_off()
        fig.patch.set_alpha(0.0)
        out = Path(out_dir) / f"{prefix}_v{i}.png"
        fig.savefig(out, transparent=True, bbox_inches="tight", pad_inches=0)
        plt.close(fig)
        out_paths.append(str(out))

    return out_paths


def mesh_stats(src_path: str) -> dict:
    """Quick facts about a mesh for the review card (best-effort)."""
    import trimesh
    try:
        m = trimesh.load(src_path, force="mesh")
        if isinstance(m, trimesh.Scene):
            m = trimesh.util.concatenate(list(m.geometry.values()))
        ext = m.bounds[1] - m.bounds[0]
        return {
            "vertices": int(len(m.vertices)),
            "faces": int(len(m.faces)),
            "watertight": bool(m.is_watertight),
            "dims_mm": [round(float(x), 1) for x in ext],
        }
    except Exception as e:
        return {"error": str(e)[:120]}
