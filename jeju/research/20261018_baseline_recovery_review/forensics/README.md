# Fixed Jeju baseline recovery evidence

**Review date:** 2026-10-18 KST  
**Scope:** Read-only investigation of the missing fixed baseline and locally available recovery candidates.

## Finding

The fixed baseline file existed and was later deleted during the 2026-10-17 storage cleanup. The deletion receipt records the exact path, 1,912,885,248-byte length, inode `98979541`, and SHA-256 `1de4756d4cb8824706d803097fc5b99c93c4324524fcef0a6db77bcc4fa87035`. It says the file did not exist after cleanup. The receipt began at 19:16:12.728 KST and finished at 19:16:39.989 KST.

This is distinct from the earlier refresh trial record, which says the frozen baseline was preserved when that trial was canceled. The later storage-cleanup receipt documents the subsequent deletion. The refresh code also identifies its own retention policy: rolling backups may be pruned, while the frozen baseline is excluded (`jeju/refresh/run.py`, lines 108–115).

## Recovery candidates

No exact-size copy was found in the readable project tree or mounted volumes. `tmutil` reported no local snapshots and no configured Time Machine destination. A targeted `lsof` query found no open deleted file descriptor matching the filename or inode.

The Trash could not be inspected: `find /Users/kimyongjin/.Trash ...` returned `Operation not permitted` (exit 1). A second attempt with elevated access was also denied by macOS with the same OS permission error; this was not an automatic approval rejection. A home-directory exact-size search printed no candidate but exited 1 with stderr suppressed, so unreadable locations may have been skipped. These results do **not** prove that no copy exists in protected locations. A user-side Trash check or an external backup may still find a copy.

The latest intact pre-refresh rolling backup is a usable replacement candidate. Its size is 1,980,116,992 bytes; a one-pass SHA-256 calculation matched its `pair_manifest.json` value `3382a2ed783493b18741482409b1d2c3229af23320b056568e1fe08a3a4fc79d`, and read-only `PRAGMA quick_check` returned `ok`. It is a later and different database state than the missing fixed baseline, so it cannot restore the fixed baseline byte-for-byte.

The retained `before_older_completion.sqlite3` copy also differs logically from the fixed baseline manifest: all 35 manifest tables were present, 15 table row counts differed, and eight additional tables were present. Reversing only the known rider-classification plans would therefore not recreate the baseline. No reconstruction or database write was attempted.

## Evidence index

- [Machine-readable evidence and command outcomes](evidence.json)
- Deletion receipt: `reports/storage_review_20261017/db_copy_deletion_receipt.json` (SHA-256 `829e4ea13b81d1ac58689e684b54224fcb078f11fe59ea087bb0780220defd1d`); target entry is at lines 145–153, completion time at line 180.
- Cleanup pointer: `jeju/maintenance/db_copy_cleanup_20261017.json` (SHA-256 `7e2a2eb0bda3b83f835904cdb052acccc9af9296b757a62348b5127facdc29cc`); target path is at line 15.
- Fixed baseline manifest: `jeju/research/20261017_core_refresh/baseline/pair_manifest.json` records the deleted database's SHA-256 and byte count. The baseline directory currently contains its JSON manifests but no SQLite database.
- Refresh outcome: `jeju/research/20261017_core_refresh/runs/20261017T220226_4747d5bd/application_manifest.json` records the later pre-refresh database size, post-refresh database size and hash, and fixed snapshot path at lines 554–557.

## Limits

The exact source was not found in the locations that could be inspected. Trash access was denied even with an elevated retry, and the home-wide search had an unreported filesystem error because stderr was redirected. No Codex session logs were searched, and the deletion receipt does not identify the command or who initiated it. The evidence supports the recorded deletion and the available replacement candidate; it does not establish that no protected or remote copy exists. A user-side Trash check or an external backup restore remains possible.

The investigation only read files and opened SQLite databases read-only. The new files in this folder are the only files written for this review; no database, original backup, or existing baseline manifest was changed.
