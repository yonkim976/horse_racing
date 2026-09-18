"""Read official API303; archive public bodies, never credentials or request URLs."""
import hashlib
import json
from pathlib import Path

from horse_racing.collectors.kra_api import KraApiClient
from horse_racing.config import get_settings

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/research/jeju_tempo_api303_20260917'

def main():
    OUT.mkdir(exist_ok=True)
    settings=get_settings()
    params=[{'rc_year':str(y)} for y in range(2018,2026)]
    params += [{'rc_month':f'2026{m:02d}'} for m in range(1,9)]
    params += [{'rc_date':f'202609{day:02d}'} for day in [4,5,11,12]]
    ledger=[]
    if settings.data_go_kr_service_key is None:
        raise RuntimeError('Configured service key is missing')
    with KraApiClient(settings.data_go_kr_service_key.get_secret_value(), timeout_seconds=25) as client:
        for q in params:
            tag=next(iter(q.values()))
            path=OUT/(tag+'.json')
            if path.exists():
                ledger.append(json.loads(path.read_text())['meta']);continue
            try:
                pages=list(client.iter_pages(endpoint='/API303/corner_rank',operation='corner_rank',
                    public_params={'meet':2,'_type':'json',**q},page_size=1000,service_key_parameter='serviceKey'))
                meta={'query':q,'pages':len(pages),'retrieved_at_ms':pages[-1].retrieved_at_ms if pages else None}
                payload={'meta':meta,'payloads':[p.payload for p in pages]}
                path.write_text(json.dumps(payload,ensure_ascii=False,indent=2))
                ledger.append(meta)
                print(tag,'pages',len(pages),flush=True)
            except Exception as exc:
                # Exception messages can carry request URLs containing the service key.
                meta={'query':q,'error_type':type(exc).__name__}
                ledger.append(meta);print(tag,meta['error_type'],flush=True)
                break
    (OUT/'request_ledger.json').write_text(json.dumps(ledger,ensure_ascii=False,indent=2))
    manifest={p.name:hashlib.file_digest(p.open('rb'),'sha256').hexdigest() for p in OUT.glob('*.json') if p.name!='manifest.json'}
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2))

if __name__=='__main__':main()
