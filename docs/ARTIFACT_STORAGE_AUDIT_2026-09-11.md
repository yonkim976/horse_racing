# 모델·데이터 파일 저장 감사 — 2026-09-11

## 결론

핵심 산출물 연결 상태는 **PASS**다. 실험 원장이 가리키는 모델 파일과 데이터셋 manifest는
모두 존재하며, 등록되지 않은 모델 디렉터리·보고서 run ID·0바이트 핵심 파일은 없다.
파일 이동이나 삭제는 하지 않았다.

## 수량

| 구분 | 수량 |
|---|---:|
| 실험 원장 run | 131 |
| artifact 경로가 등록된 run | 74 |
| 모델 디렉터리 | 74 |
| 데이터셋 manifest | 34 |
| 자동 실험 보고서 파일 | 145 |
| 보고서에 포함된 고유 run ID | 125 |
| walk-forward 실행 디렉터리 | 47 |
| 확률 calibration 디렉터리 | 5 |
| RaceValue 연구 실행 | 3 |
| RacePortfolio 연구 실행 | 5 |
| 데이터 archive | 1 |

보고서 파일 수가 run 수보다 많은 이유는 한 run에서 기본 보고서와 구간별 보고서를 함께
만드는 경우가 있기 때문이다. 보고서 파일명에 UUID가 없는 6개 run은 기준선 4개와 공용
파일명을 사용하는 feature ablation 2개이며, 실험 원장에 report 경로·설명이 남아 있다.

## 연결 무결성

| 검사 | 결과 |
|---|---:|
| JSONL 파싱 오류 | 0 |
| 중복 run ID | 0 |
| 누락 모델 artifact | 0 |
| 누락 데이터셋 manifest | 0 |
| 원장 미등록 모델 디렉터리 | 0 |
| 원장 미등록 보고서 run ID | 0 |
| docs·datasets·experiments 0바이트 파일 | 0 |
| 임시·backup 이름 파일 | 0 |

## 저장 규모

2026-09-11 확인값이며 파일시스템 표시 단위에 따라 반올림된다.

| 위치 | 크기 | 역할 |
|---|---:|---|
| `data/horse_racing.sqlite3` | 약 896MB | 운영 DB |
| `data/raw` | 약 1.3GB | 원본 응답·수집 자료 |
| `data/datasets` | 약 1.0GB | 재현 가능한 학습 프레임 |
| `data/experiments` | 약 509MB | 모델·예측·보고서 |
| `data/predictions` | 약 3.0MB | 날짜별 실전·진단 예측 |
| `data/archives` | 약 924KB | 한라마 제거 전 복구 archive |

## 디렉터리 판정

- `data/datasets/<version>/<as_of>/`: 데이터와 manifest가 함께 있어 양호하다.
- `data/experiments/models/<run_id>/`: 모델 run ID 기준으로 정리되어 있고 원장과 일치한다.
- `data/experiments/reports/`: 보고서가 한 디렉터리에 누적되어 파일 수가 많지만 UUID로
  추적 가능하다. 지금은 이동하지 않는다.
- `data/experiments/walk_forward/<run_id>/`: 시간순 검증 산출물이 별도 분리되어 양호하다.
- `data/experiments/race_value_v1`, `race_portfolio_v1`: 일반 model registry 밖의 연구
  manifest를 자체 보유한다. 향후 단일 registry에 연결할 여지가 있다.
- `data/predictions/`: 날짜별 폴더와 `current_*` 진단 폴더가 섞여 있다. 유실은 없지만
  장기적으로 `live/`, `analysis/`, `preliminary/` 하위 분리를 권장한다.
- `data/logs/`: 수집 로그와 복구 감사 로그가 함께 있다. 기능상 문제는 없으며 날짜·작업별
  하위 폴더 규칙을 새 작업부터 적용하는 편이 안전하다.

## 남은 위험

1. 현재 코드·문서 변경 다수가 Git 미커밋 상태다. 로컬 저장은 되었지만 원격 백업은 아니다.
2. `data/raw`, DB, 데이터셋, 모델은 용량과 민감정보 정책상 Git 밖에 있으므로 별도 백업이 필요하다.
3. 과거 실험을 삭제하면 원장의 재현 링크가 끊어진다. 정리할 때는 삭제보다 archive manifest와
   checksum을 남기는 방식을 사용해야 한다.
4. RaceValue·RacePortfolio 실행은 자체 manifest만 사용하므로 중앙 원장과의 연결을 추후
   보강해야 한다.

## 재검사

```bash
.venv/bin/python scripts/audit_artifacts.py \
  --output data/logs/artifact_audit_20260911.json
```

기계 판독 결과는
[`data/logs/artifact_audit_20260911.json`](../data/logs/artifact_audit_20260911.json)에 저장한다.
