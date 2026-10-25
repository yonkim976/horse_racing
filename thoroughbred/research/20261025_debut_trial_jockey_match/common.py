"""Load the frozen parent study helpers without executing parent writers."""

import sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
PREVIOUS=HERE.parent/'20261025_debut_trial_prediction'
OUT=HERE/'outputs'
MODELS=HERE/'models'
sys.path.insert(0,str(PREVIOUS))
import model as parent  # noqa: E402
from prepare import DB,dump,sha  # noqa: E402

__all__=['DB','dump','sha','parent','HERE','ROOT','OUT','PREVIOUS','MODELS','QUALITY','IDENTITY','independent_paths']

QUALITY=['trial_j_at_trial_history_n','trial_j_at_trial_prior_win','trial_j_at_trial_prior_top3',
    'trial_j_at_debut_history_n','trial_j_at_debut_prior_win','trial_j_at_debut_prior_top3',
    'jockey_win_gap','jockey_top3_gap']
IDENTITY=['last_same']


def independent_paths():
    return sorted(p for p in PREVIOUS.rglob('*') if p.is_file() and '__pycache__' not in p.parts)+[HERE.parent/'conclusions/59_DEBUT_TRIAL_PREDICTION.md']
