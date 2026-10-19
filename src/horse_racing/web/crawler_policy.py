"""Narrow, cheap guards for paths this read-only Python site never serves."""

from urllib.parse import unquote


def scanner_probe_reason(path: str) -> str | None:
    # ASGI normally decodes once; one additional pass also rejects common
    # double-encoded probes. This is classification, never a filesystem path.
    parts = unquote(path).replace("\\", "/").lower().split("/")
    if any(part == ".env" or part.startswith(".env.") for part in parts):
        return "environment_file"
    if any(part in {".git", ".svn", ".hg"} for part in parts):
        return "source_control_metadata"
    if any(part in {"wp-admin", "wp-content", "wp-includes", "wp-login.php"} for part in parts):
        return "wordpress_path"
    if any(part.endswith((".php", ".php3", ".php4", ".php5", ".phtml", ".phar"))
           for part in parts):
        return "php_endpoint"
    return None
