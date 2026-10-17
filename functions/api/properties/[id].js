const response=(data,status=200)=>Response.json(data,{status,headers:{'Cache-Control':'private, no-store'}});
const STATUSES=['new','watching','contact','offer_sent','waiting_sale','rejected','archived','acquired'];
const PRIORITIES=['low','normal','high'];
const text=(v,max=4000)=>typeof v==='string'?v.trim().slice(0,max):'';

export async function onRequestGet({params,env}){
  const id=String(params.id||'');
  try{
    const [p,s,h]=await env.DB.batch([
      env.DB.prepare("SELECT p.*,COALESCE(d.status,'new') AS status,COALESCE(d.priority,'normal') AS priority,COALESCE(d.tags_json,'[]') AS tags_json,COALESCE(d.note,'') AS note,d.follow_up_date,d.title_override,d.district_override FROM properties p LEFT JOIN property_decisions d ON d.property_id=p.id WHERE p.id=?").bind(id),
      env.DB.prepare("SELECT source_type,source_title,source_url,published_at,found_at,last_seen_at,price_czk,raw_excerpt FROM property_sources WHERE property_id=? ORDER BY found_at DESC LIMIT 60").bind(id),
      env.DB.prepare("SELECT changed_at,change_json FROM decision_history WHERE property_id=? ORDER BY id DESC LIMIT 30").bind(id)
    ]);
    const property=p.results?.[0];
    if(!property)return response({error:'Nemovitost neexistuje.'},404);
    const {tags_json,...rest}=property;
    let tags=[];try{tags=JSON.parse(tags_json);}catch{}
    return response({property:{...rest,tags},sources:s.results||[],history:(h.results||[]).map(r=>({...r,change:JSON.parse(r.change_json||'{}'),change_json:undefined}))});
  }catch(e){console.error('Radar detail failed',e?.message);return response({error:'Chyba databáze.'},503);}
}

export async function onRequestPatch({request,params,env}){
  const id=String(params.id||'');
  let body;
  try{body=await request.json();}catch{return response({error:'Neplatný JSON.'},400);}
  if(!body||typeof body!=='object'||Array.isArray(body))return response({error:'Neplatné změny.'},400);
  const allowed=['status','priority','tags','note','follow_up_date','title_override','district_override'];
  if(Object.keys(body).some(k=>!allowed.includes(k)))return response({error:'Nepovolené pole.'},400);
  if('status' in body&&!STATUSES.includes(body.status))return response({error:'Neznámý stav.'},400);
  if('priority' in body&&!PRIORITIES.includes(body.priority))return response({error:'Neznámá priorita.'},400);
  if('tags' in body&&(!Array.isArray(body.tags)||body.tags.length>20||
    body.tags.some(t=>typeof t!=='string'||!t.trim()||t.length>35)))return response({error:'Neplatné štítky.'},400);
  if('note' in body&&(typeof body.note!=='string'||body.note.length>4000))return response({error:'Poznámka je příliš dlouhá.'},400);
  if('title_override' in body&&body.title_override!==null&&
    (typeof body.title_override!=='string'||body.title_override.length>180))
    return response({error:'Název je příliš dlouhý.'},400);
  if('district_override' in body&&body.district_override!==null&&
    !['','Kutná Hora','Havlíčkův Brod'].includes(body.district_override))
    return response({error:'Neplatný okres.'},400);
  if('follow_up_date' in body&&body.follow_up_date!==null&&body.follow_up_date!==''&&
    (typeof body.follow_up_date!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(body.follow_up_date)||
      !Number.isFinite(Date.parse(body.follow_up_date))))return response({error:'Neplatné datum.'},400);
  try{
    const exists=await env.DB.prepare('SELECT id FROM properties WHERE id=?').bind(id).first();
    if(!exists)return response({error:'Nemovitost nenalezena.'},404);
    const current=await env.DB.prepare('SELECT * FROM property_decisions WHERE property_id=?').bind(id).first();
    const next={
      status:body.status??current?.status??'new',
      priority:body.priority??current?.priority??'normal',
      tags_json:'tags' in body ? JSON.stringify([...new Set(body.tags.map(t=>t.trim()))]) : current?.tags_json??'[]',
      note:'note' in body ? body.note : current?.note??'',
      follow_up_date:'follow_up_date' in body ? body.follow_up_date||null : current?.follow_up_date??null,
      title_override:'title_override' in body ? text(body.title_override,180)||null : current?.title_override??null,
      district_override:'district_override' in body ? body.district_override||null : current?.district_override??null,
    };
    await env.DB.batch([
      env.DB.prepare(
        'INSERT INTO property_decisions (property_id,status,priority,tags_json,note,follow_up_date,title_override,district_override,updated_at) VALUES (?,?,?,?,?,?,?,?,datetime("now"))'+
        ' ON CONFLICT(property_id) DO UPDATE SET status=excluded.status,priority=excluded.priority,tags_json=excluded.tags_json,note=excluded.note,'+
        ' follow_up_date=excluded.follow_up_date,title_override=excluded.title_override,district_override=excluded.district_override,updated_at=datetime("now")'
      ).bind(id,next.status,next.priority,next.tags_json,next.note,next.follow_up_date,next.title_override,next.district_override),
      env.DB.prepare('INSERT INTO decision_history (property_id,change_json) VALUES (?,?)').bind(id,JSON.stringify(body))
    ]);
    return response({ok:true,decision:{...next,tags:JSON.parse(next.tags_json)}});
  }catch(e){console.error('Radar decision update failed',e?.message);return response({error:'Změnu se nepodařilo uložit.'},503);}
}
