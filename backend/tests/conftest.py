import pytest


@pytest.fixture(autouse=True)
def isolated_artifacts(tmp_path, monkeypatch):
    """Keep tests away from the real artifacts/ campaign database and runtime lock."""
    monkeypatch.setenv("ROBOTOPS_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("ROBOTOPS_CAMPAIGN_DB", str(tmp_path / "campaigns.sqlite3"))
