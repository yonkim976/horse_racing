"""Replace one reviewed function in the pinned collector, never a dirty checkout."""
import ast
import hashlib
import json
from pathlib import Path

TARGET = Path('/app/src/horse_racing/jobs/daily_training.py')
EXPECTED = '9ddb3567965e2c2c15acadc5dd2ce8f989443be4eaec4674ebf7c9e37d5dbfc7'
source = TARGET.read_text()
tree = ast.parse(source)
matches = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'run_tasks']
assert len(matches) == 1
node = matches[0]
lines = source.splitlines(keepends=True)
old = ''.join(lines[node.lineno - 1:node.end_lineno]).rstrip('\n')
assert hashlib.sha256(old.encode()).hexdigest() == EXPECTED, 'Unexpected deployed function'
replacement = Path('/tmp/run_tasks.py').read_text()
new_tree = ast.parse(replacement)
assert len(new_tree.body) == 1 and isinstance(new_tree.body[0], ast.FunctionDef)
assert new_tree.body[0].name == 'run_tasks'
patched = ''.join(lines[:node.lineno-1]) + replacement.rstrip('\n') + '\n' + ''.join(lines[node.end_lineno:])
compile(patched, str(TARGET), 'exec')
TARGET.write_text(patched)
print(json.dumps({'patched_function': 'run_tasks', 'old_sha256': EXPECTED,
                  'new_sha256': hashlib.sha256(replacement.rstrip('\n').encode()).hexdigest()}))
