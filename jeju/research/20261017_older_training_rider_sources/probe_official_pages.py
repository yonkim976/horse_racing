"""Bounded public KRA source discovery; never writes the research database."""
from pathlib import Path
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.parse import urlsplit, urlencode
import argparse
import hashlib
import json
from datetime import datetime, timezone
from bs4 import BeautifulSoup

HERE=Path(__file__).resolve().parent
HOSTS={'race.kra.co.kr','m.kra.co.kr','todayrace.kra.co.kr'}
LIMIT=4*1024*1024

class OfficialRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        p=urlsplit(newurl)
        if p.scheme!='https' or p.hostname not in HOSTS or p.username or p.password or p.port not in (None,443):
            raise ValueError('Redirect outside official HTTPS hosts')
        return super().redirect_request(req,fp,code,msg,headers,newurl)

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--batch',required=True);a.add_argument('--post-json');a.add_argument('urls',nargs='+');args=a.parse_args()
    form=json.loads(args.post_json) if args.post_json else None
    if form is not None:
        assert isinstance(form,dict) and set(form)<={'meet','Act','Sub','trDate','trYo','pageIndex','rcDate','rcNo','trDateReplace','trNo','trName'}
        assert all(isinstance(v,str) and len(v)<=30 for v in form.values())
    assert args.batch.replace('_','').isalnum() and len(args.urls)<=12
    out=HERE/'homepage'/args.batch;out.mkdir(parents=True,exist_ok=False)
    result=[]
    for n,url in enumerate(args.urls,1):
        p=urlsplit(url)
        assert p.scheme=='https' and p.hostname in HOSTS and not p.username and not p.password and p.port in (None,443)
        if form is not None:
            assert p.path in {'/trainer/dailyGroupTrainList.do','/trainer/dailyAllTrainDetail.do','/trainer/dailyDayDetailTrain.do','/chulmainfo/chulmaDetailInfoTrainState.do'}
        r={'url':url,'retrieved_at_utc':datetime.now(timezone.utc).isoformat(),'method':'POST' if form is not None else 'GET','form_fields':form}
        try:
            req=Request(url,data=urlencode(form).encode() if form is not None else None,headers={'User-Agent':'Mozilla/5.0 (KRA official source research)','Accept':'text/html,application/pdf'})
            with build_opener(OfficialRedirect()).open(req,timeout=20) as response:
                b=response.read(LIMIT+1);r.update(http_status=response.status,final_url=response.geturl(),content_type=response.headers.get('Content-Type',''))
            assert len(b)<=LIMIT,'Response over limit'
            r.update(bytes=len(b),sha256=hashlib.sha256(b).hexdigest())
            ext='pdf' if b.startswith(b'%PDF') else 'html'
            path=out/f'{n}.{ext}';path.write_bytes(b);r['source_path']=str(path.relative_to(HERE.parents[2]))
            if ext=='html':
                for enc in ['utf-8','cp949','euc-kr']:
                    try:text=b.decode(enc);break
                    except UnicodeDecodeError:continue
                else:raise ValueError('No strict HTML decoder')
                soup=BeautifulSoup(text,'html.parser')
                (out/f'{n}.txt').write_text(soup.get_text(' ',strip=True))
                r['forms']=[{'action':f.get('action'),'method':f.get('method'),'fields':[{'tag':x.name,'name':x.get('name'),'value':x.get('value'),'type':x.get('type'),'options':[o.get('value') for o in x.find_all('option')][:30]} for x in f.find_all(['input','select'])]} for f in soup.find_all('form')]
                r['relevant_links']=[{'text':x.get_text(' ',strip=True),'href':x.get('href'),'onclick':x.get('onclick')} for x in soup.find_all('a') if any(k.lower() in str(x).lower() for k in ['조교','train','chulma','pdf'])][:150]
                r['inline_scripts']=[s.get_text() for s in soup.find_all('script') if not s.get('src') and any(x in s.get_text().lower() for x in ['train','chulma','rcdate','racedate','trdate'])]
            r['status']='saved'
        except Exception as exc:r.update(status='failed',error_type=type(exc).__name__,error=str(exc)[:350])
        result.append(r)
    (out/'manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps([{k:v for k,v in r.items() if k not in ('forms','relevant_links','inline_scripts')} for r in result],ensure_ascii=False))
