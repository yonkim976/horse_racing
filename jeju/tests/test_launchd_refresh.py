"""A skipped/failed child must never be presented as a successful refresh."""
import json
import subprocess

import pytest

from jeju.refresh import launchd_runner as runner


@pytest.mark.parametrize('stdout,exit_code,status', [
    ('{"status":"already_running"}', 0, 'busy_duplicate'),
    ('no receipt was emitted', 1, 'no_receipt'),
    ('{"status":"applied_verified","manifest":"/tmp/unrelated/application_manifest.json"}', 1, 'no_receipt'),
])
def test_skip_or_missing_receipt_preserves_last_success(tmp_path, monkeypatch, stdout, exit_code, status):
    home = tmp_path / 'jeju/research/20261017_core_refresh'
    home.mkdir(parents=True)
    state_path = home / 'launchd_execution_status.json'
    last_success = {'run_id': 'previous_success', 'database_sha256_after': 'previous_sha'}
    state_path.write_text(json.dumps({'last_success': last_success}))
    monkeypatch.setattr(runner, 'ROOT', tmp_path)
    monkeypatch.setattr(runner, 'REFRESH_HOME', home)
    monkeypatch.setattr(runner, 'STATUS_PATH', state_path)
    monkeypatch.setattr(runner.subprocess, 'run', lambda *a, **kw: subprocess.CompletedProcess(a, 0, stdout))
    assert runner.execute() == exit_code
    saved = json.loads(state_path.read_text())
    assert saved['last_success'] == last_success
    assert saved['last_execution']['status'] == status
