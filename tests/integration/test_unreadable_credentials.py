"""A stored credential that cannot be decrypted answers with the localized message.

The routes used to return str(e) from the cryptography library, which told the operator
nothing and was not translated. The answer keeps the same 200 + success:false shape as a
BMC failure, so an unreadable credential is still not distinguishable by status code.
"""

from __future__ import annotations

import sqlite3

from backend.core.i18n import t


def _corrupt_first_server(tmp_path) -> str:
    con = sqlite3.connect(tmp_path / "ipmideck.db")
    try:
        server_id = con.execute("SELECT id FROM servers ORDER BY id LIMIT 1").fetchone()[0]
        con.execute(
            "UPDATE servers SET password_enc = ? WHERE id = ?", ("v2:not-a-credential", server_id)
        )
        con.commit()
    finally:
        con.close()
    return str(server_id)


def test_connection_test_reports_an_unreadable_credential(client, tmp_path):
    server_id = _corrupt_first_server(tmp_path)
    resp = client.post(f"/api/servers/{server_id}/test")
    assert resp.status_code == 200
    assert resp.json() == {"success": False, "error": t("credentials_unreadable", "en")}


def test_power_command_reports_an_unreadable_credential(client, tmp_path):
    server_id = _corrupt_first_server(tmp_path)
    resp = client.post(f"/api/modules/power/{server_id}/command", json={"action": "on"})
    assert resp.status_code == 200
    assert resp.json() == {"success": False, "error": t("credentials_unreadable", "en")}
