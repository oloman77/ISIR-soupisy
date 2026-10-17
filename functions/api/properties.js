const reply = (body,status=200) => Response.json(body,{status,headers:{'Cache-Control':'private, no-store'}});
const clean = (v,max=120) => typeof v==='string'?v.trim().slice(0,max):'';
const validUrl = input => {
  if (!input) return '';
  try {
    const u=new URL(input);
    return ['http:','https:'].includes(u.protocol)?u.href.slice(0,1000):null;
  } catch { return null; }
};
export async function onRequestGet({request,env}) {
  const query=new URL(request.url).searchParams;
  const where=[], args=[];
  const filters={
    district:clean(query.get('district'),80), municipality:clean(query.get('municipality'),80),
    status:clean(query.get('status'),30),priority:clean(query.get('priority'),20),
    type:clean(query.get('type'),80),source:clean(query.get('source'),40),
    tag:clean(query.get('tag'),40),q:clean(query.get('q'),24)
  };
  if(filters.district){
    if(filters.district==='__unknown__') where.push("COALESCE(NULLIF(d.district_override,''),p.district)=''");
    else { where.push("COALESCE(NULLIF(d.district_override,''),p.district)=?"); args.push(filters.district); }
  }
  if(filters.municipality){where.push('p.municipality=?');args.push(filters.municipality);}
  if(filters.status){where.push("COALESCE(d.status,'new')=?");args.push(filters.status);}
  if(filters.priority){where.push("COALESCE(d.priority,'normal')=?");args.push(filters.priority);}
  if(filters.type){where.push('p.property_type=?');args.push(filters.type);}
  if(filters.source){where.push('EXISTS (SELECT 1 FROM property_sources s WHERE s.property_id=p.id AND s.source_type=?)');args.push(filters.source);}
  if(filters.tag){where.push("EXISTS (SELECT 1 FROM json_each(COALESCE(d.tags_json,'[]')) WHERE value=?)");args.push(filters.tag);}
  if(filters.q){
    const pattern='%'+filters.q.replace(/[%_\\]/g,'\\$&')+'%';
    where.push("(p.title LIKE ? ESCAPE '\\' OR p.municipality LIKE ? ESCAPE '\\' OR p.cadastral_territory LIKE ? ESCAPE '\\' OR p.parcel LIKE ? ESCAPE '\\' OR p.lv LIKE ? ESCAPE '\\' OR d.note LIKE ? ESCAPE '\\')");
    args.push(pattern,pattern,pattern,pattern,pattern,pattern);
  }
  const base=' FROM properties p LEFT JOIN property_decisions d ON d.property_id=p.id '+(where.length?' WHERE '+where.join(' AND '):'');
  const limit=Math.max(1,Math.min(100,Number.parseInt(query.get('limit')||'40',10)||40));
  const page=Math.max(1,Math.min(100000,Number.parseInt(query.get('page')||'1',10)||1));
  const statement=[
    "SELECT p.id, COALESCE(NULLIF(d.title_override,''),p.title) AS title,",
    "p.property_type, COALESCE(NULLIF(d.district_override,''),p.district) AS district,",
    "p.municipality,p.cadastral_territory,p.parcel,p.lv,p.area_m2,p.address,",
    "p.location_confidence,p.sale_phase,p.created_at,p.updated_at,",
    "COALESCE(d.status,'new') AS status,COALESCE(d.priority,'normal') AS priority,",
    "COALESCE(d.tags_json,'[]') AS tags_json,COALESCE(d.note,'') AS note,d.follow_up_date,",
    "(SELECT COUNT(*) FROM property_sources s WHERE s.property_id=p.id) AS source_count,",
    "(SELECT MAX(s.last_seen_at) FROM property_sources s WHERE s.property_id=p.id) AS last_seen,",
    "(SELECT s.source_type FROM property_sources s WHERE s.property_id=p.id ORDER BY s.found_at LIMIT 1) AS first_source",
    base,
    "ORDER BY CASE COALESCE(d.status,'new') WHEN 'rejected' THEN 2 WHEN 'archived' THEN 3 ELSE 0 END,",
    "CASE COALESCE(d.priority,'normal') WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END,",
    "COALESCE(p.updated_at,p.created_at) DESC,p.id DESC LIMIT ? OFFSET ?"
  ].join(' ');
  try{
    const [records,count,summary,districts,types,sources,tags]=await env.DB.batch([
      env.DB.prepare(statement).bind(...args,limit,(page-1)*limit),
      env.DB.prepare('SELECT COUNT(*) AS total '+base).bind(...args),
      env.DB.prepare("SELECT COALESCE(d.status,'new') AS status,COUNT(*) AS total FROM properties p LEFT JOIN property_decisions d ON d.property_id=p.id GROUP BY COALESCE(d.status,'new')"),
      env.DB.prepare("SELECT DISTINCT district AS name FROM properties WHERE district<>'' ORDER BY district LIMIT 100"),
      env.DB.prepare('SELECT DISTINCT property_type AS name FROM properties ORDER BY property_type LIMIT 100'),
      env.DB.prepare('SELECT DISTINCT source_type AS name FROM property_sources ORDER BY source_type LIMIT 100'),
      env.DB.prepare("SELECT DISTINCT tags_json AS value FROM property_decisions WHERE tags_json<>'[]' LIMIT 500")
    ]);
    const uniqueTags=new Set();
    for(const t of tags.results||[]){try{for(const x of JSON.parse(t.value)) uniqueTags.add(x);}catch{}}
    return reply({
      items:(records.results||[]).map(row=>{
        const {tags_json,...other}=row;
        let parsed=[];try{parsed=JSON.parse(tags_json||'[]');}catch{}
        return {...other,tags:parsed};
      }),
      total:count.results?.[0]?.total||0,page,limit,
      stats:Object.fromEntries((summary.results||[]).map(r=>[r.status,r.total])),
      options:{
        districts:(districts.results||[]).map(r=>r.name),
        types:(types.results||[]).map(r=>r.name),
        sources:(sources.results||[]).map(r=>r.name),
        tags:[...uniqueTags].sort((a,b)=>a.localeCompare(b,'cs'))
      }
    });
  }catch(e){
    console.error('Radar list failed',e?.message);
    return reply({error:'Databáze není připravena nebo nastala chyba čtení.'},503);
  }
}
export async function onRequestPost({request,env}){
  let b;try{b=await request.json();}catch{return reply({error:'Neplatný JSON'},400);}
  const title=clean(b.title,180),type=clean(b.property_type,80)||'nezjištěno',
    district=clean(b.district,80),municipality=clean(b.municipality,120),
    cadastral=clean(b.cadastral_territory,120),parcel=clean(b.parcel,100),
    lv=clean(b.lv,80),note=clean(b.note,4000);
  const sourceUrl=validUrl(clean(b.source_url,1000));
  if(title.length<3)return reply({error:'Doplň název nemovitosti (alespoň 3 znaky).'},400);
  if(sourceUrl===null)return reply({error:'URL musí začínat http:// nebo https://'},400);
  if(district&&!['Kutná Hora','Havlíčkův Brod'].includes(district))
    return reply({error:'Vyber cílový okres nebo Neurčeno.'},400);
  const id='manual:'+crypto.randomUUID();
  try{
    await env.DB.batch([
      env.DB.prepare('INSERT INTO properties (id,title,property_type,district,municipality,cadastral_territory,parcel,lv,location_confidence) VALUES (?,?,?,?,?,?,?,?,?)')
        .bind(id,title,type,district,municipality,cadastral,parcel,lv,'suggested'),
      env.DB.prepare('INSERT INTO property_decisions (property_id,status,priority,note) VALUES (?,?,?,?)')
        .bind(id,'new','normal',note),
      env.DB.prepare('INSERT INTO property_sources (id,property_id,source_type,external_id,source_title,source_url) VALUES (?,?,?,?,?,?)')
        .bind('manual-source:'+crypto.randomUUID(),id,'manual',id,title,sourceUrl||'')
    ]);
    return reply({id},201);
  }catch(e){console.error('Radar create failed',e?.message);return reply({error:'Záznam se nepodařilo uložit.'},503);}
}
