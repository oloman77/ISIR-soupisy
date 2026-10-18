// Offline security regression tests for Cloudflare Pages middleware.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {onRequest} from './functions/_middleware.js';

const secret = 'Cq3w!7L9-Ax28B6_Pq4rS1t8R5v0';
const credentials = (password=secret, user='radar') =>
  'Basic ' + Buffer.from(user + ':' + password).toString('base64');
function context({
  authorization, password=secret, url='https://isir-radar.pages.dev/',
  method='GET', origin, contentType='application/json',
  db={}
}={}) {
  const headers = new Headers();
  if(authorization !== undefined) headers.set('Authorization',authorization);
  if(origin) headers.set('Origin',origin);
  if(method !== 'GET' && contentType) headers.set('Content-Type',contentType);
  let called = 0;
  return {
    context: {
      env: {RADAR_LOGIN_PASSWORD:password,DB:db},
      request: new Request(url,{method,headers,
        ...(method==='POST'||method==='PATCH'?{body:'{"test":true}'}:{})}),
      next: async () => { called++;return new Response('ok',{headers:{'Cache-Control':'public,max-age=300'}}); }
    },
    called: ()=>called
  };
}

test('fails closed without a configured strong secret',async()=>{
  const {context:ctx,called}=context({authorization:credentials(),password:undefined});
  delete ctx.env.RADAR_LOGIN_PASSWORD;
  const r=await onRequest(ctx);
  assert.equal(r.status,503); assert.equal(called(),0);
  assert.equal(r.headers.get('Cache-Control'),'private, no-store');
});

test('rejects secrets shorter than 12 characters',async()=>{
  for (const password of ['short','Abc!1234567']) {
    const a=context({authorization:credentials(password),password});
    assert.equal((await onRequest(a.context)).status,503);
    assert.equal(a.called(),0);
  }
});

test('accepts a unique 12-character password',async()=>{
  const password='K7!sA0_9$2rx';
  const a=context({authorization:credentials(password),password});
  const r=await onRequest(a.context);
  assert.equal(r.status,200);
  assert.equal(a.called(),1);
});

test('challenges unauthorized browsers even for static pages',async()=>{
  const a=context();
  const r=await onRequest(a.context);
  assert.equal(r.status,401);
  assert.match(r.headers.get('WWW-Authenticate'),/Basic realm="ISIR Radar"/);
  assert.equal(a.called(),0);
});

test('rejects wrong password and wrong user',async()=>{
  for(const auth of [credentials('wrong'),credentials(secret,'admin'),
    'Bearer token','Basic !!!']){
    const a=context({authorization:auth});
    assert.equal((await onRequest(a.context)).status,401);
    assert.equal(a.called(),0);
  }
});

test('valid credentials allow pages and disable caching',async()=>{
  const a=context({authorization:credentials()});
  const r=await onRequest(a.context);
  assert.equal(r.status,200); assert.equal(a.called(),1);
  assert.equal(await r.text(),'ok');
  assert.equal(r.headers.get('Cache-Control'),'private, no-store');
  assert.equal(r.headers.get('X-Robots-Tag'),'noindex, nofollow, noarchive');
});

test('protects API reads identically',async()=>{
  const a=context({url:'https://isir-radar.pages.dev/api/properties'});
  assert.equal((await onRequest(a.context)).status,401);
  assert.equal(a.called(),0);
});

test('rejects HTTP even with correct password',async()=>{
  const a=context({authorization:credentials(),url:'http://isir-radar.pages.dev/'});
  assert.equal((await onRequest(a.context)).status,403);
});

test('rejects cross-origin and missing origin on authenticated writes',async()=>{
  for (const origin of [undefined,'https://untrusted.invalid']){
    const a=context({authorization:credentials(),method:'PATCH',
      url:'https://isir-radar.pages.dev/api/properties/1',origin});
    assert.equal((await onRequest(a.context)).status,403);
    assert.equal(a.called(),0);
  }
});

test('rejects HTML form and non-JSON submissions',async()=>{
  const a=context({authorization:credentials(),method:'POST',
    url:'https://isir-radar.pages.dev/api/properties',
    origin:'https://isir-radar.pages.dev',contentType:'application/x-www-form-urlencoded'});
  assert.equal((await onRequest(a.context)).status,415);
  assert.equal(a.called(),0);
});

test('allows same-origin authenticated JSON updates',async()=>{
  const a=context({authorization:credentials(),method:'PATCH',
    url:'https://isir-radar.pages.dev/api/properties/1',
    origin:'https://isir-radar.pages.dev'});
  assert.equal((await onRequest(a.context)).status,200);
  assert.equal(a.called(),1);
});

test('API with no D1 binding fails closed',async()=>{
  const a=context({authorization:credentials(),
    url:'https://isir-radar.pages.dev/api/properties',db:null});
  assert.equal((await onRequest(a.context)).status,503);
  assert.equal(a.called(),0);
});
