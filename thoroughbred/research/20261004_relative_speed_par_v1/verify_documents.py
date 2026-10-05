"""Check the completed report links and central conclusion/source hashes."""

import hashlib
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"


def main():
    manifest = json.loads((HERE.parent / "conclusions/source_manifest.json").read_text())
    assert len(manifest["sources"]) == 20 and len(manifest["conclusions"]) == 12
    hash_checks = 0
    for entry in manifest["sources"] + manifest["conclusions"]:
        assert hashlib.sha256((ROOT / entry["path"]).read_bytes()).hexdigest() == entry["sha256"]
        hash_checks += 1
    documents = list(HERE.glob("*.md")) + [
        HERE.parent / "conclusions/10_RELATIVE_SPEED_PAR.md",
        HERE.parent / "conclusions/README.md",
        HERE.parent / "conclusions/SOURCES.md",
        HERE.parent / "README.md",
        HERE.parent / "RESEARCH_PUBLICATION_POLICY.md",
        HERE.parent / "DISTANCE_RECORD_BENCHMARK_POLICY.md",
        HERE.parent / "20261004_relative_speed_scope/README.md",
        HERE.parent / "20261004_website_research_review/README.md",
    ]
    links = 0
    for path in documents:
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", path.read_text()):
            if "://" in target or target.startswith("#"):
                continue
            target = target.split("#")[0]
            destination = (path.parent / target).resolve()
            assert destination.exists(), (path, target)
            links += 1
    report = dict(
        status="passed",
        documents=len(documents),
        local_links=links,
        central_source_hashes=hash_checks,
        source_documents=20,
        conclusion_markdown_files=12,
        mismatches=0,
    )
    (OUT / "document_verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
