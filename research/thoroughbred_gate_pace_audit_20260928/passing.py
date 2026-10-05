import re
TOKEN=re.compile(r'\((?:\^?\d+,)*\^?\d+\)|\^?\d+')
def parse(raw):
    s=re.sub(r'\s+','',raw)
    if not s or any(c not in '0123456789^(),-=≡' for c in s):raise ValueError('unsupported notation')
    groups=[];cursor=0;allhorses=[]
    for m in TOKEN.finditer(s):
        sep=s[cursor:m.start()]
        if (cursor==0 and sep) or (cursor>0 and sep not in [',','-','=','≡']):raise ValueError('invalid delimiter')
        token=m.group();pack=token.startswith('(');ids=[int(x) for x in re.findall(r'\d+',token)]
        if min(ids)<1:raise ValueError('invalid horse number')
        groups.append({'members':ids,'pack':pack,'separator':sep,'marked':[int(x) for x in re.findall(r'\^(\d+)',token)]})
        allhorses+=ids;cursor=m.end()
    if cursor!=len(s) or len(set(allhorses))!=len(allhorses):raise ValueError('trailing text or duplicate horse')
    return groups
