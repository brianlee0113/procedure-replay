"""Manifest access + license gate. Every entry point calls require_allowed() before touching a video.

Allowed: CC0, CC-BY, CC-BY-SA (any version suffix, e.g. CC-BY-4.0), Pexels license, Pixabay license, Apache-2.0.
Rejected: anything with ND (we edit videos) or NC, and rows missing creator / source_url.
Why this list: docs/HACKATHON_RULES.md ("Project policy").

    uv run python -m pr.license_check            # validate every manifest row, exit 1 on any failure
"""

import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "data" / "manifest.csv"
APP_MANIFEST = ROOT / "data" / "manifest_app.csv"
FIELDS = ["video_id", "task", "creator", "source_url", "license", "role", "local_path"]

_ALLOWED = re.compile(r"^(CC0|CC-BY|CC-BY-SA)(-\d+(\.\d+)?)?$|^(PEXELS|PIXABAY)(-LICENSE)?$|^APACHE-2\.0$")


class LicenseError(Exception):
    pass


def normalize(license_str: str) -> str:
    return re.sub(r"[\s_]+", "-", license_str.strip().upper())


def check_row(row: dict) -> list[str]:
    """Return a list of problems; empty means the row is allowed."""
    problems = []
    lic = normalize(row.get("license") or "")
    parts = set(lic.split("-"))
    if not lic:
        problems.append("license is empty")
    elif "ND" in parts or "NC" in parts:
        problems.append(f"license {row['license']!r} is ND/NC (not allowed)")
    elif not _ALLOWED.match(lic):
        problems.append(f"license {row['license']!r} is not in the allowed list")
    for field in ("creator", "source_url"):
        if not (row.get(field) or "").strip():
            problems.append(f"{field} is empty")
    if row.get("role") not in ("reference", "trainee"):
        problems.append(f"role {row.get('role')!r} must be reference|trainee")
    return problems


def load_manifest(path: Path = MANIFEST) -> list[dict]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def append_manifest_row(row: dict, path: Path = MANIFEST) -> None:
    with open(path, "a", newline="") as f:
        csv.DictWriter(f, fieldnames=FIELDS).writerow({k: row.get(k, "") for k in FIELDS})


def load_all() -> list[dict]:
    """Dataset rows plus the app's recordings (data/manifest_app.csv, not in git)."""
    return load_manifest() + (load_manifest(APP_MANIFEST) if APP_MANIFEST.exists() else [])


def find_row(video: str, rows: list[dict] | None = None) -> dict:
    """Look up a manifest row by video_id or by local_path (relative to repo root or absolute)."""
    rows = load_all() if rows is None else rows
    as_path = Path(video).expanduser()
    resolved = (as_path if as_path.is_absolute() else Path.cwd() / as_path).resolve()
    for row in rows:
        if row["video_id"] == video or (ROOT / row["local_path"]).resolve() == resolved:
            return row
    raise LicenseError(f"{video}: no row in {MANIFEST.relative_to(ROOT)} — add source_url, creator, license first")


def require_allowed(video: str) -> dict:
    """Return the manifest row for `video` (id or path) or raise LicenseError. Never process a video without this."""
    row = find_row(video)
    problems = check_row(row)
    if problems:
        raise LicenseError(f"{row['video_id']}: refused — " + "; ".join(problems))
    return row


def local_path(row: dict) -> Path:
    return ROOT / row["local_path"]


def main() -> int:
    rows = load_manifest()
    bad = 0
    for row in rows:
        problems = check_row(row)
        status = "OK  " if not problems else "FAIL"
        bad += bool(problems)
        print(f"{status} {row['video_id']:<40} {row['license']:<14} {'; '.join(problems)}")
    print(f"\n{len(rows) - bad}/{len(rows)} rows allowed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
