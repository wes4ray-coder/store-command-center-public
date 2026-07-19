"""3D models pipeline for Cults3D — backlog → review → propose → approve → publish.

Drop raw 3D files (STL/OBJ/3MF/GLB/ZIP) into MODELS3D_BACKLOG. `scan` ingests them,
`render` makes turntable thumbnails, `propose` has the LLM draft the listing, you
approve, and `publish` pushes to Cults3D via createCreation. Assets are served to
Cults from a token-guarded public route (no session needed, that's how Cults pulls).

This module is a package: the shared ``router`` + asset-token/backlog/row helpers +
job registries live in ``_base``; the routes are split across ``backlog`` (config /
scan / list / counts), ``genmodels`` (3D-gen model catalog), ``listings`` (per-model
CRUD + render/hero/propose/publish), ``generate`` (local text/image→mesh) and
``assets`` (the public token route). The submodules are imported IN ORDER so the
route registration order matches the original file — the specific static paths must
register before ``/api/models3d/{model_id}`` (see the note in ``genmodels``).
"""
from ._base import router                              # shared router + helpers
from . import backlog, genmodels, listings, generate, assets  # noqa: F401  (order matters — registers routes)
from .listings import _PROPOSE_SYSTEM                  # noqa: F401  (prompts registry ref)
from .generate import Generate3dRequest, generate_model3d_ep  # noqa: F401  (used by routers.nsfw)

__all__ = ["router", "_PROPOSE_SYSTEM", "Generate3dRequest", "generate_model3d_ep"]
