"""Replay the three saved F1_STYLE6 models into this study's new outputs folder.

This wrapper reuses only the immutable replay implementation and score
contract from the 2026-10-17 study. It redirects every generated artifact to
this study and never invokes training or a database verifier.
"""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
REFERENCE_STUDY = ROOT / "jeju/research/20261017_1000m_five_section_ablation_v1"
REFERENCE_TRAINER = REFERENCE_STUDY / "train_candidate.py"
REFERENCE_REPLAYER = REFERENCE_STUDY / "replay_baseline.py"


def replay() -> dict:
    for path in (REFERENCE_TRAINER, REFERENCE_REPLAYER):
        if not path.is_file():
            raise FileNotFoundError(path)
    study_text = str(REFERENCE_STUDY)
    if study_text not in sys.path:
        sys.path.insert(0, study_text)

    # Importing this module loads fixed STYLE6 constants but performs no fit.
    import train_candidate as reference_train

    # The legacy replay code writes only through this module-level output path.
    # Set it before loading the replay module; all input paths remain immutable.
    reference_train.OUT = OUT
    replay_namespace = runpy.run_path(str(REFERENCE_REPLAYER), run_name="saved_style6_replay")
    return replay_namespace["replay"]()


if __name__ == "__main__":
    import json

    print(json.dumps(replay(), ensure_ascii=False, indent=2))
