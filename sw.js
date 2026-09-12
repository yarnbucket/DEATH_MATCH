const CACHE_NAME = 'death-trails-v4-pwa-009-master666';
const APP_SHELL = [
  './',
  './index.html',
  './manifest.webmanifest',
  './master666.json'
];

const CATEGORY_SPECS = [
  ['director',"DIRECTOR'S CUT",'Movie ↔ Director','MOVIES','DIRECTORS'],
  ['character','BEHIND THE FACE','Character ↔ Actor / Actress','CHARACTERS','ACTORS / ACTRESSES'],
  ['year','TIMELINE OF TERROR','Movie ↔ Release Year','MOVIES','YEARS'],
  ['curse','THE RULES','Rule / Detail ↔ Movie','RULES / DETAILS','MOVIES'],
  ['setting','WHERE NIGHTMARES LIVE','Setting ↔ Movie','PLACES / SETTINGS','MOVIES'],
  ['adaptation','FROM PAGE TO SCREAM','Author / Source ↔ Film Adaptation','AUTHORS / SOURCES','MOVIES'],
  ['weapon',"KILLER'S ARSENAL",'Killer / Villain ↔ Signature Weapon','KILLERS','WEAPONS'],
  ['quote','LAST WORDS','Famous Line ↔ Movie','LINES','MOVIES'],
  ['haunted','HAUNTED GROUND','Haunted Place ↔ Movie','HAUNTED PLACES','MOVIES'],
  ['survivor','FINAL GIRLS & SURVIVORS','Survivor ↔ Movie','SURVIVORS','MOVIES'],
  ['royalty','SCREAM ROYALTY','Horror Performer ↔ Signature Film','HORROR ROYALTY','MOVIES'],
  ['fx','MONSTER MAKERS','FX Artist ↔ Horror Work','FX ARTISTS','MOVIES / CREATURES'],
  ['halloween','ON THE SCREEN','Visual Detail ↔ Movie','ON-SCREEN DETAILS','MOVIES']
];
const TRAILS=['blood','ghost','static','ember','slime','dirt','rot','claw'];

function makeLevels(master){
  const levels={};
  for(const [key,name,desc,left,right] of CATEGORY_SPECS){
    const src=master.categories?.[name];
    if(!Array.isArray(src)) throw new Error('Missing Master 666 category: '+name);
    const scaredCount=src.length===52?18:17;
    const curiousEnd=scaredCount+17;
    levels[key]={
      name,desc,left,right,
      pairs:src.map((p,i)=>[
        p.question,
        p.answer,
        TRAILS[i%TRAILS.length],
        i<scaredCount?'scared':(i<curiousEnd?'curious':'madman')
      ])
    };
  }
  const total=Object.values(levels).reduce((n,l)=>n+l.pairs.length,0);
  if(total!==666) throw new Error('Master 666 count mismatch: '+total);
  return levels;
}

function replaceLevels(html,levels){
  const marker='const LEVELS = ';
  const start=html.indexOf(marker);
  if(start<0) throw new Error('LEVELS marker not found');
  const brace=html.indexOf('{',start);
  let depth=0,end=-1,inString=false,escape=false;
  for(let i=brace;i<html.length;i++){
    const c=html[i];
    if(inString){
      if(escape) escape=false;
      else if(c==='\\') escape=true;
      else if(c==='"') inString=false;
    }else{
      if(c==='"') inString=true;
      else if(c==='{') depth++;
      else if(c==='}'){
        depth--;
        if(depth===0){ end=i; break; }
      }
    }
  }
  if(end<0) throw new Error('LEVELS object end not found');
  const tag='<!-- MASTER 666 RUNTIME DATA -->';
  let out=html.slice(0,start)+marker+JSON.stringify(levels)+html.slice(end+1);
  if(!out.includes(tag)) out=out.replace('</head>',tag+'\n</head>');
  return out;
}

async function master666Response(request){
  const [pageResponse,masterResponse]=await Promise.all([
    fetch(request,{cache:'no-store'}),
    fetch('./master666.json',{cache:'no-store'})
  ]);
  if(!pageResponse.ok||!masterResponse.ok) return pageResponse;
  const [html,master]=await Promise.all([pageResponse.text(),masterResponse.json()]);
  const updated=replaceLevels(html,makeLevels(master));
  const headers=new Headers(pageResponse.headers);
  headers.set('content-type','text/html; charset=utf-8');
  headers.set('cache-control','no-cache');
  headers.delete('content-length');
  return new Response(updated,{status:pageResponse.status,statusText:pageResponse.statusText,headers});
}

self.addEventListener('install',event=>{
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache=>cache.addAll(APP_SHELL))
      .then(()=>self.skipWaiting())
  );
});

self.addEventListener('activate',event=>{
  event.waitUntil(
    caches.keys()
      .then(keys=>Promise.all(keys.filter(k=>k!==CACHE_NAME).map(k=>caches.delete(k))))
      .then(()=>self.clients.claim())
  );
});

self.addEventListener('fetch',event=>{
  const request=event.request;
  if(request.method!=='GET') return;
  const url=new URL(request.url);

  if(request.mode==='navigate'){
    event.respondWith(
      master666Response(request)
        .then(async response=>{
          const copy=response.clone();
          const cache=await caches.open(CACHE_NAME);
          await cache.put('./index.html',copy);
          return response;
        })
        .catch(()=>caches.match('./index.html'))
    );
    return;
  }

  if(url.origin===self.location.origin){
    event.respondWith(
      caches.match(request).then(cached=>cached||fetch(request).then(async response=>{
        if(response&&response.ok){
          const cache=await caches.open(CACHE_NAME);
          await cache.put(request,response.clone());
        }
        return response;
      }))
    );
    return;
  }

  event.respondWith(
    caches.match(request).then(cached=>{
      const network=fetch(request).then(async response=>{
        if(response&&(response.ok||response.type==='opaque')){
          const cache=await caches.open(CACHE_NAME);
          await cache.put(request,response.clone());
        }
        return response;
      }).catch(()=>cached);
      return cached||network;
    })
  );
});
