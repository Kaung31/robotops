import subprocess

from robotops_backend.software import software_identity


def git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def make_repo(root):
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "config", "user.name", "test")
    (root / "a.txt").write_text("one\n")
    git(root, "add", "a.txt")
    git(root, "commit", "-q", "-m", "init")


def test_clean_checkout_is_identified_by_revision(tmp_path):
    make_repo(tmp_path)
    identity = software_identity(tmp_path)
    assert identity["available"] and identity["branch"] == "main"
    assert not identity["dirty"]
    assert identity["describe"] == f"git:{identity['revision']}"


def test_uncommitted_and_untracked_changes_change_the_identity(tmp_path):
    make_repo(tmp_path)
    (tmp_path / "a.txt").write_text("two\n")
    modified = software_identity(tmp_path)
    assert modified["dirty"]
    assert modified["describe"].startswith(f"git:{modified['revision']}+dirty:")

    (tmp_path / "new.txt").write_text("x\n")
    untracked = software_identity(tmp_path)
    assert untracked["untracked_files"] == 1
    assert untracked["describe"] != modified["describe"]

    (tmp_path / "new.txt").write_text("y\n")  # same names, different content
    changed = software_identity(tmp_path)
    assert changed["untracked_sha256"] != untracked["untracked_sha256"]
    assert changed["describe"] != untracked["describe"]


def test_missing_repository_is_reported_not_guessed(tmp_path):
    identity = software_identity(tmp_path)
    assert identity["available"] is False
    assert "revision" not in identity
