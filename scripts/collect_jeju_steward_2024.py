"""Archive 2024 official daily steward responses; no database mutation."""
import json
import hashlib
from pathlib import Path
import polars as pl
from horse_racing.collectors.kra_api import KraApiClient
from horse_racing.config import get_settings

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/research/jeju_steward_2024_backfill_20260917'


def main():
    OUT.mkdir(exist_ok=True)
    dates=sorted(pl.read_parquet(ROOT/'data/research/jeju_tempo_pace_features_20260917/observations.parquet').filter(pl.col('event_date').dt.year()==2024)['event_date'].unique().to_list())
    settings=get_settings();ledger=[]
    with KraApiClient(settings.data_go_kr_service_key.get_secret_value(),timeout_seconds=25) as client:
        for d in dates:
            day=d.strftime('%Y%m%d');path=OUT/(day+'.json')
            if path.exists():
                ledger.append(json.loads(path.read_text())['meta']);continue
            try:
                pages=list(client.iter_pages(endpoint='/API215/JudgeReport',operation='JudgeReport',
                    public_params={'meet':2,'rc_date':day,'_type':'json'},page_size=1000))
                meta={'day':day,'pages':len(pages),'retrieved_at_ms':pages[-1].retrieved_at_ms if pages else None}
                path.write_text(json.dumps({'meta':meta,'payloads':[p.payload for p in pages]},ensure_ascii=False,indent=2))
                ledger.append(meta)
                print(day,'pages',len(pages),flush=True)
            except Exception as exc:
                ledger.append({'day':day,'error_type':type(exc).__name__})
                print(day,type(exc).__name__,flush=True)
            (OUT/'request_ledger.json').write_text(json.dumps(ledger,indent=2))
    (OUT/'manifest.json').write_text(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.glob('*.json') if p.name!='manifest.json'},indent=2))
    print('requested',len(dates),'completed',sum('error_type' not in r for r in ledger),flush=True)


if __name__=='__main__':main()
