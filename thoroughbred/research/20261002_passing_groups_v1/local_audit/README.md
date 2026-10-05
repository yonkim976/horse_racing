# 서울 통과조 414칸 로컬 원문 재점검

대상은 서울 2020~2021년 API corner 필드와 Dacom11 성적표 RPT 지점 원문이다. 네트워크/API 재수집 없이 API/RPT parquet를 각각 한 번 인메모리 DuckDB 테이블로 물질화해 독립 계산했다. 비교에만 양끝 ASCII 공백을 제거했고 `-`, `X`, 빈 문자열은 값에서 제외했다. 통과조 문법은 파싱하지 않았다. 기준 DB는 `backups/20261002_before_steward_reports/thoroughbred_core.duckdb`를 `read_only=True`로 열었다.

## 결과

- 원문 계산 및 기준 DB에서 미대응 API 셀 **414/414**. 모두 같은 경주의 API locator·필드명·리터럴까지 대조됐다. 2020년 **170셀/114경주**, 2021년 **244셀/145경주**다.
- 후보가 없거나 API 필드만 여러 개인 셀은 **0**이다. **310셀**은 같은 값이 API 필드 2개와 RPT 공식 지점 2곳에 반복됐다(155 값 그룹). **104셀**은 API 필드 1개 값이 RPT 공식 지점 2곳에 반복됐다(104 값 그룹). 따라서 414칸 모두 값만으로는 개별 API 필드와 RPT 지점을 일대일로 확정할 수 없다.
- 259개 경주×값 그룹 각각 RPT 후보 지점은 2곳이며, 후보 지점 쌍은 `1C+S1F` 206셀, `3C+S1F` 193셀, `2C+S1F` 12셀, `1C+2C` 2셀, `3C+4C` 1셀이다.
- 미대응 값이 반복된 공식 RPT 지점 키 **518개(259×2)** 모두 성적표에 정규화 리터럴이 하나씩 있었고 최종 선택도 RPT 값으로 보완됐다. 이 518개 중 결측·값 차이·선택 원천 차이는 **0**이다.
- 2020~2021 서울의 최종 경주×지점 키 6,531개를 원문 parquet에서 독립 재구성한 결과 기준 DB와 원천·정규화 값 차이는 **0**이었다. 최종 선택은 API 4,757개와 RPT 1,774개(미대응 셀이 있는 경주에서 666개, API 부재 경주에서 1,108개)다. DB 해시는 전후 동일하다.

그러므로 미대응 414칸은 **API 필드와 지점 라벨의 metadata 대응 보류**로 남기는 것이 타당하다. 반복값 때문에 최종 경주×공식 RPT 지점 값이 빠지지는 않는다. RPT가 각 지점의 값을 이미 제공해 518개 후보 지점 모두 보완한다.

## 원문 예시

- 2020-01-04 서울 1경주: `corner_3`와 `corner_7`의 API 값이 같고 RPT `C3`와 `S-1F` 값도 같다. 양쪽 후보가 각각 두 개라 API 필드별 연결은 확정할 수 없지만 `3C`와 `S1F` 최종 값은 둘 다 RPT에서 선택된다.
- 2020-01-04 서울 8경주: `corner_2` 한 칸의 값이 RPT `C3`와 `S-1F` 두 곳에 나타난다. API 필드 중복이 없어도 RPT 지점 중복 때문에 필드 연결은 확정되지 않는다. 두 지점 값은 각각 성적표에서 선택된다.
- 예외 지점 쌍 `3C+4C`: 2021-10-09 서울 4경주 `corner_4` 한 칸.
- 예외 지점 쌍 `1C+2C`: 2020-07-11 서울 12경주 `corner_3`, `corner_4` 두 칸.

## 산출물

- [summary.json](summary.json): 실행 범위, 원천 해시, 수량 및 DB parity
- [unmapped_cells.csv](unmapped_cells.csv): 미대응 414칸별 후보 필드·RPT 지점
- [ambiguous_value_groups.csv](ambiguous_value_groups.csv): 259개 동일값 그룹과 원문 위치
- [rpt_final_fill_points.csv](rpt_final_fill_points.csv): RPT 최종 보완 1,774개 중 전체 목록
- [point_selection_reconciliation.csv](point_selection_reconciliation.csv): 최종 6,531개 키의 독립 계산과 기준 DB 대조
- [recheck_unmapped.py](recheck_unmapped.py): 재현 가능한 읽기 전용 계산
