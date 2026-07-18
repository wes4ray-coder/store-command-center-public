"""First-run login flow (the retail onboarding bug).

A fresh install must: advertise the default password on the login page, accept
it (and ONLY it), flag the session as default-password so the UI shows the
change-it banner, and clear that flag once a real password is set.
"""


def _clear_auth(client):
    import auth_core
    from deps import get_conn
    conn = get_conn()
    conn.execute("DELETE FROM settings WHERE key IN ('_auth_password_hash','_auth_default_pw')")
    conn.commit()
    conn.close()


def test_fresh_install_flow(client):
    _clear_auth(client)

    # 1) the login page tells a fresh install the default password
    r = client.get("/login")
    assert r.status_code == 200
    assert "default password" in r.text and "store" in r.text

    # 2) a made-up password does NOT work (and doesn't get silently set)
    r = client.post("/login", data={"password": "my-own-password"}, follow_redirects=False)
    assert r.status_code != 303

    # 3) the default works, and the install is flagged as default-password
    r = client.post("/login", data={"password": "store"}, follow_redirects=False)
    assert r.status_code == 303
    assert client.get("/api/auth/status").json()["default_password"] is True

    # 4) changing the password clears the flag and the login-page hint
    r = client.post("/api/auth/change-password",
                    json={"current": "store", "new_password": "better-pass"})
    assert r.status_code == 200
    assert client.get("/api/auth/status").json()["default_password"] is False
    assert "default password" not in client.get("/login").text

    # 5) old default no longer works; the new password does
    assert client.post("/login", data={"password": "store"}, follow_redirects=False).status_code != 303
    assert client.post("/login", data={"password": "better-pass"}, follow_redirects=False).status_code == 303
