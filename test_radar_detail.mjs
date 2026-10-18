// Offline regression tests of the real property detail endpoints.
// Never read Cloudflare secrets or call the live private database.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {onRequestGet, onRequestPatch} from './functions/api/property.js';

function fixture() {
  const seen=[];
  const db={
    prepare(sql){ return {
      bind(...args){ return {sql,args,
        async first(){
          seen.push({sql,args});
          if(sql.startsWith('SELECT id FROM properties')) {
            return args[0] === 'isir-doc:12' ? {id:'isir-doc:12'} : null;
          }
          if(sql.startsWith('SELECT * FROM property_decisions'))return null;
          throw Error('Unexpected SELECT');
        }
      }; }
    },
    async batch(statements){
      for(const s of statements)seen.push(s);
      if(statements[0]?.sql?.startsWith('SELECT p.*,')){
        const id=statements[0].args[0];
        return [
          {results:id === 'isir-doc:12'
            ? [{id,title:'Provizorní PDF',district:'Kutná Hora',
                status:'new',priority:'normal',tags_json:'[]',note:''}]
            : []},
          {results:[{source_type:'isir',source_url:'https://example.test/doc'}]},
          {results:[]}
        ];
      }
      return [{success:true},{success:true}];
    }
  };
  return {env:{DB:db},seen};
}

test('GET detail works with an encoded colon in an imported document ID',async()=>{
  const data=fixture();
  const result=await onRequestGet({
    request:new Request('https://isir-radar.pages.dev/api/property?id=isir-doc%3A12'),
    env:data.env
  });
  assert.equal(result.status,200);
  const json=await result.json();
  assert.equal(json.property.id,'isir-doc:12');
  assert.equal(json.property.title,'Provizorní PDF');
  assert.deepEqual(json.property.tags,[]);
  assert.equal(json.sources[0].source_type,'isir');
  assert.equal(data.seen[0].args[0],'isir-doc:12');
});

test('missing ID returns descriptive HTTP 400, not a spurious 404',async()=>{
  const data=fixture();
  const result=await onRequestGet({
    request:new Request('https://isir-radar.pages.dev/api/property'),
    env:data.env
  });
  assert.equal(result.status,400);
  assert.equal(data.seen.length,0);
});

test('unknown property returns JSON 404 instead of an HTML not-found page',async()=>{
  const data=fixture();
  const result=await onRequestGet({
    request:new Request('https://isir-radar.pages.dev/api/property?id=unknown'),
    env:data.env
  });
  assert.equal(result.status,404);
  assert.equal((await result.json()).error,'Nemovitost neexistuje.');
});

test('PATCH saves evaluation to the exact same imported document',async()=>{
  const data=fixture();
  const result=await onRequestPatch({
    request:new Request('https://isir-radar.pages.dev/api/property?id=isir-doc%3A12',
      {method:'PATCH',headers:{'Content-Type':'application/json'},
       body:JSON.stringify({status:'watching',priority:'high',note:'Prověřit'})}),
    env:data.env
  });
  assert.equal(result.status,200);
  assert.equal((await result.json()).ok,true);
  assert.equal(data.seen[0].args[0],'isir-doc:12');
  assert.equal(data.seen[2].args[0],'isir-doc:12');
  assert.equal(data.seen[2].args[1],'watching');
});

test('PATCH refuses missing property ID',async()=>{
  const data=fixture();
  const result=await onRequestPatch({
    request:new Request('https://isir-radar.pages.dev/api/property?id=unknown',
      {method:'PATCH',headers:{'Content-Type':'application/json'},
       body:JSON.stringify({note:'no'})}),
    env:data.env
  });
  assert.equal(result.status,404);
  assert.equal(data.seen.length,1);
});
