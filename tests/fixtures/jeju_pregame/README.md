# KRA public HTML parser fixtures

Extracted table structures from public KRA pages inspected on 2026-09-16.
Stored in UTF-8; actual HTTP responses use their advertised encoding.
These fixtures test parsing, not historical publication timestamps.

- schedule: ChulmaDetailInfoList.do, meet=2; 2026-09-17..19 declarations.
- card: chulmaDetailInfoChulmapyo.do, meet=2, rcDate=20260917, rcNo=1.
- card_rated: same detail endpoint, rcNo=3; explicit rating/change syntax.
- changes: ChulmapyoChange.do, meet=2; empty cancellation and jockey tables.
- weight_index: ChuljumaWeightWeight.do, meet=2; links explicitly dated 20260912.
- weight: ChuljumaWeightList.do, meet=2, date=20260912, rcNo=1.
- track: trackView.do, meet=2; 2026-09-13 09:00 effective status, 4% moisture.

Full timed responses and hashes are separately preserved in the research
observation store. Fixture HTML is deliberately reduced to relevant tables;
it is not an HTTP response archive. No results are used for model evaluation.
