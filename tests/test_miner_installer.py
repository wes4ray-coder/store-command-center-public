"""The standalone miner installer — shipped, served, and honest about its URL.

node-setup.sh installs the miner only as part of a full node build (ComfyUI, LM
Studio, video, 3D). install-miner.sh is the "I just want to point a spare card at
a friend's chain" path, which is what joining someone's network actually needs.
"""
import re
import subprocess
from pathlib import Path

from config import BASE

INSTALLER = BASE / "deploy" / "miner" / "install-miner.sh"


def test_installer_ships_and_is_valid_shell():
    assert INSTALLER.is_file(), "install-miner.sh must ship with the store"
    r = subprocess.run(["bash", "-n", str(INSTALLER)], capture_output=True, text=True)
    assert r.returncode == 0, f"syntax error in install-miner.sh: {r.stderr}"


def test_installer_check_mode_changes_nothing(tmp_path):
    """`check` must be safe to run anywhere — it reports, it never installs."""
    r = subprocess.run(["bash", str(INSTALLER), "check"],
                       capture_output=True, text=True, timeout=60,
                       env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"})
    assert r.returncode == 0, r.stderr
    assert not (tmp_path / "jellyminer-venv").exists(), "check mode must not install"
    assert not (tmp_path / ".config/systemd/user/jellyminer.service").exists()


def test_installer_requires_a_url(tmp_path):
    """Refuse rather than silently installing a miner pointed at nothing."""
    r = subprocess.run(["bash", str(INSTALLER), "install"],
                       capture_output=True, text=True, timeout=60,
                       env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"})
    assert r.returncode != 0
    assert "--url is required" in r.stdout


def test_store_serves_the_installer(client):
    r = client.get("/api/jelly/mining/install-miner.sh")
    assert r.status_code == 200, r.text
    body = r.text
    assert body.startswith("#!"), "must be served as a runnable script"
    assert "jellyminer-venv" in body and "pyopencl" in body


def test_miner_token_panel_offers_a_working_url_and_one_liner(client):
    """The copy-paste command used to carry a hardcoded LAN IP, which the retail
    scrub rewrote to 127.0.0.1 — every public user got a command that only worked
    on the store box. It must be derived at runtime instead."""
    d = client.get("/api/jelly/miner-token").json()
    assert d["token"]
    for field in ("run", "install", "url"):
        assert d.get(field), f"miner-token must expose {field}"
    assert "127.0.0.1" not in d["url"], "must advertise a reachable address, not loopback"
    assert re.search(r"https?://", d["url"])
    assert d["url"] in d["run"] and d["url"] in d["install"]
    assert d["token"] in d["run"]
    assert "install-miner.sh" in d["install"]


def test_installer_is_not_the_full_node_build():
    """Guards the whole point: this must not drag in the AI stack.

    Checks executable lines only — the header comment names those components
    precisely to explain what this installer deliberately is NOT.
    """
    code = "\n".join(ln for ln in INSTALLER.read_text().splitlines()
                     if not ln.lstrip().startswith("#"))
    for heavy in ("ComfyUI", "TripoSR", "lmstudio", "store_videogen", "AudioCraft"):
        assert heavy not in code, f"{heavy} has no business in the miner-only installer"


def test_installer_keeps_the_token_out_of_the_unit_file():
    body = INSTALLER.read_text()
    unit = body[body.find("[Unit]"):body.find("WantedBy=default.target")]
    assert "EnvironmentFile=" in unit
    assert "${JELLY_TOKEN}" in unit, "the unit must read the token from the env file"
    assert "chmod 600" in body, "the env file holding the token must not be world-readable"
