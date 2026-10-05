# Busan 2015-03-29 cancellation verification

This is an independent row-level check of the official KRA daily scoretable capture. The archived EUC-KR page has exactly one race-card row for each requested key: Busan-Gyeongnam (meet 3), 2015-03-29, race 5 and race 6. Both rows explicitly label the outcome `취소` and give the reason `경주 진행 장애 (고객들이 4경주 1번마 경주성적 불만으로 출장로 점거)`. The evidence supports `race_cancelled` for both keys; it does not use `경주불성립`.

The source bytes are at [daily_20150329.html](../root_busan_direct/daily_20150329.html); capture details and the byte hash are in [capture_manifest.json](../root_busan_direct/capture_manifest.json). Verification details and extracted exact row text are in [verification.json](verification.json). The HTML SHA-256 is `a9b077b77ea457204da944256939b76ffb8b5154b03911c6a8734df762d4fd86`. No network request or database/configuration change was made.
