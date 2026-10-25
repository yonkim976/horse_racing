"""No-network, no-secret collector image routing/multiplicity smoke test."""
import json
import os
from datetime import date
from types import SimpleNamespace

from horse_racing.jobs import daily_training as job

assert os.geteuid() != 0
calls = []
for name in ('ingest_training', 'ingest_start_training', 'ingest_swim_training_date', 'ingest_hill_training'):
    def callback(*_args, _name=name, **kwargs):
        calls.append((_name, kwargs))
        return SimpleNamespace(records_fetched=1, records_written=1, run_id=1)
    setattr(job, name, callback)

def no_website(*args, **kwargs):
    raise AssertionError('Jeju starting website must not be called')
job.ingest_jeju_start_training_website = no_website
job.emit = lambda *_a, **_kw: None
results = job.run_tasks(SimpleNamespace(rollback=lambda: None), None, None, None,
                        days=job.training_window(date(2026, 10, 17)), raw_dir=None)
starts = [args for name, args in calls if name == 'ingest_start_training']
assert len(results) == 50 and len(starts) == 21
assert sum(args['meet'] == 2 for args in starts) == 7
assert all(r['status'] == 'completed' for r in results)
print(json.dumps({'jeju_api22_image_smoke': 'passed', 'tasks': 50,
                  'jeju_api22_dates': 7, 'non_root': True}))
