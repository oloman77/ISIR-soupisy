// Stable detail endpoint: use a query parameter rather than a dynamic
// URL path, because imported property IDs contain ':' (e.g. isir-doc:123).
// The auth middleware protects this endpoint exactly as it protects the list.
import {onRequestGet as getDetail, onRequestPatch as saveDetail} from './properties/[id].js';

const invalid=()=>Response.json({error:'Chybí identifikátor nemovitosti.'},
  {status:400,headers:{'Cache-Control':'private, no-store'}});

function forProperty(ctx){
  const id=new URL(ctx.request.url).searchParams.get('id');
  if (!id || id.length>160) return null;
  return {...ctx,params:{...(ctx.params||{}),id}};
}

export function onRequestGet(ctx){
  const inner=forProperty(ctx);
  return inner ? getDetail(inner) : invalid();
}

export function onRequestPatch(ctx){
  const inner=forProperty(ctx);
  return inner ? saveDetail(inner) : invalid();
}
