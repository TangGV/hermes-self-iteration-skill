#!/usr/bin/env python3
import hashlib, json, sys, time, socket
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.request import Request, urlopen
from urllib.error import HTTPError

UPSTREAM='http://127.0.0.1:3000'
LISTEN=('127.0.0.1',8327)
HOP={'connection','keep-alive','proxy-authenticate','proxy-authorization','te','trailers','transfer-encoding','upgrade','content-length','host','accept-encoding'}
DROP_FOR_RESPONSES={'stream_options','metadata'}
DROP_FOR_CHAT={'input','instructions','store','previous_response_id','truncation','include','prompt_cache_retention','text','metadata','reasoning_summary','thinking','thinking_budget'}

def normalize_call_id(call_id, fallback_seed=''):
    """OpenAI Responses/Codex: call_id max 64 chars. Cursor may send longer ids."""
    s = str(call_id or '').strip()
    if not s:
        s = 'call_' + hashlib.sha256(str(fallback_seed).encode()).hexdigest()[:32]
    if len(s) <= 64:
        return s
    return 'call_' + hashlib.sha256(s.encode()).hexdigest()[:58]

def normalize_responses_input(items):
    if not isinstance(items, list):
        return items
    out = []
    for it in items:
        if not isinstance(it, dict):
            out.append(it)
            continue
        it = dict(it)
        typ = it.get('type')
        if typ == 'function_call':
            seed = str(it.get('name') or '') + str(it.get('arguments') or '')[:80]
            it['call_id'] = normalize_call_id(
                it.get('call_id') or it.get('id') or it.get('tool_call_id'), seed
            )
        elif typ in ('function_call_output', 'tool_result'):
            seed = str(it.get('output') or it.get('content') or '')[:80]
            it['call_id'] = normalize_call_id(
                it.get('call_id') or it.get('id') or it.get('tool_call_id'), seed
            )
        out.append(it)
    return out

def normalize_reasoning_effort(v):
    if v is None: return None
    if isinstance(v,dict): v=v.get('effort') or v.get('level')
    if not isinstance(v,str): return None
    x=v.strip().lower().replace('-', '').replace('_', '')
    if x in ('minimal','none'): return x
    if x in ('low','medium','high','xhigh'): return x
    if x in ('xhight','xhi','extra high','extrahigh','veryhigh'): return 'xhigh'
    return None

def content_to_chat(c):
    if c is None: return ''
    if isinstance(c,str): return c
    if isinstance(c,list):
        out=[]
        for it in c:
            if isinstance(it,str): out.append({'type':'text','text':it}); continue
            if not isinstance(it,dict): continue
            t=it.get('type')
            if t in ('input_text','output_text'):
                out.append({'type':'text','text':it.get('text','')})
            elif t=='text':
                out.append({'type':'text','text':it.get('text','')})
            elif t in ('input_image','image_url'):
                if 'image_url' in it:
                    img=it['image_url']
                    out.append({'type':'image_url','image_url':img if isinstance(img,dict) else {'url':img}})
                elif 'url' in it:
                    out.append({'type':'image_url','image_url':{'url':it['url']}})
                elif isinstance(it.get('image'),dict) and 'image_url' in it['image']:
                    img=it['image']['image_url']
                    out.append({'type':'image_url','image_url':img if isinstance(img,dict) else {'url':img}})
            elif 'text' in it:
                out.append({'type':'text','text':str(it.get('text',''))})
        if out and all(x.get('type')=='text' for x in out):
            return ''.join(x.get('text','') for x in out)
        return out if out else ''
    return str(c)

def input_to_messages(v, instructions=None):
    msgs=[]
    if instructions:
        msgs.append({'role':'system','content':content_to_chat(instructions)})
    if isinstance(v,str):
        return msgs+[{'role':'user','content':v}]
    if isinstance(v,list):
        for it in v:
            if isinstance(it,str): msgs.append({'role':'user','content':it}); continue
            if not isinstance(it,dict): continue
            typ=it.get('type')
            if typ in (None,'message') and ('role' in it or 'content' in it):
                role=it.get('role') or 'user'
                if role=='developer': role='system'
                if role not in ('system','user','assistant','tool'): role='user'
                msg={'role':role,'content':content_to_chat(it.get('content'))}
                if role=='tool' and it.get('tool_call_id'):
                    msg['tool_call_id']=normalize_call_id(it.get('tool_call_id'), str(it.get('content'))[:80])
                msgs.append(msg)
            elif typ in ('input_text','text'):
                msgs.append({'role':'user','content':it.get('text','')})
            elif typ=='function_call':
                call_id=normalize_call_id(it.get('call_id') or it.get('id') or it.get('tool_call_id'), (it.get('name') or '')+str(len(msgs)))
                name=str(it.get('name') or it.get('function_name') or 'tool')
                args=it.get('arguments') or it.get('args') or '{}'
                if not isinstance(args,str): args=json.dumps(args,ensure_ascii=False,separators=(',',':'))
                msgs.append({'role':'assistant','content':'','tool_calls':[{'id':call_id,'type':'function','function':{'name':name,'arguments':args}}]})
            elif typ in ('function_call_output','tool_result'):
                call_id=normalize_call_id(it.get('call_id') or it.get('id') or it.get('tool_call_id'), str(it.get('output') or it.get('content'))[:80])
                output=it.get('output') if 'output' in it else it.get('content')
                content=content_to_chat(output)
                if not isinstance(content,str): content=json.dumps(content,ensure_ascii=False,separators=(',',':'))
                msg={'role':'tool','content':content}
                if call_id: msg['tool_call_id']=call_id
                msgs.append(msg)
            elif typ in ('reasoning','summary'):
                continue
        if msgs: return msgs
    return msgs+[{'role':'user','content':content_to_chat(v)}]

def tools_to_chat(tools):
    if not isinstance(tools,list): return tools
    out=[]
    for t in tools:
        if not isinstance(t,dict): continue
        if t.get('type')=='function' and 'function' in t: out.append(t); continue
        if t.get('type')=='function' and t.get('name'):
            fn={'name':t.get('name')}
            if t.get('description') is not None: fn['description']=t.get('description')
            params=t.get('parameters') or t.get('schema')
            if params is not None: fn['parameters']=params
            out.append({'type':'function','function':fn})
    return out

def to_chat_payload(d):
    out=dict(d); changed=False
    if 'messages' not in out and 'input' in out:
        out['messages']=input_to_messages(out.get('input'), out.get('instructions')); changed=True
    if 'max_tokens' not in out and 'max_output_tokens' in out:
        out['max_tokens']=out.get('max_output_tokens'); changed=True
    if 'tools' in out:
        nt=tools_to_chat(out.get('tools'))
        if nt: out['tools']=nt
        else: out.pop('tools',None)
        changed=True
    effort=normalize_reasoning_effort(out.get('reasoning_effort')) or normalize_reasoning_effort(out.get('reasoning'))
    for k in DROP_FOR_CHAT:
        if k in out: out.pop(k,None); changed=True
    if 'reasoning' in out:
        out.pop('reasoning',None); changed=True
    if effort:
        out['reasoning_effort']=effort; changed=True
    return out,changed

def to_responses_payload(d):
    out=dict(d); changed=True
    for k in DROP_FOR_RESPONSES: out.pop(k,None)
    # Cursor sometimes sends Chat-only stream_options with Responses body.
    return out,changed

def response_text(obj):
    texts=[]
    for item in obj.get('output') or []:
        if not isinstance(item,dict): continue
        if item.get('type')=='message':
            for p in item.get('content') or []:
                if isinstance(p,dict) and p.get('type') in ('output_text','text') and p.get('text') is not None:
                    texts.append(str(p.get('text')))
                elif isinstance(p,str): texts.append(p)
        elif item.get('type')=='output_text' and item.get('text') is not None:
            texts.append(str(item.get('text')))
    if not texts and obj.get('output_text') is not None: texts.append(str(obj.get('output_text')))
    return ''.join(texts)

def responses_json_to_chat(payload):
    try: obj=json.loads(payload.decode('utf-8','replace'))
    except Exception: return payload
    if not isinstance(obj,dict) or obj.get('object')!='response': return payload
    created=obj.get('created_at') or int(time.time())
    chat={'id':obj.get('id','chatcmpl-cursor-compat'),'object':'chat.completion','created':int(created),'model':obj.get('model'),
          'choices':[{'index':0,'message':{'role':'assistant','content':response_text(obj)},'finish_reason':'stop'}]}
    if isinstance(obj.get('usage'),dict): chat['usage']=obj['usage']
    return json.dumps(chat,ensure_ascii=False,separators=(',',':')).encode('utf-8')

def chunk_json(resp_id,model,content='',finish=None):
    return json.dumps({'id':resp_id or 'chatcmpl-cursor-compat','object':'chat.completion.chunk','created':int(time.time()),'model':model,
        'choices':[{'index':0,'delta':({'content':content} if content else {}),'finish_reason':finish}]},ensure_ascii=False,separators=(',',':'))

def responses_sse_to_chat(resp):
    resp_id='chatcmpl-cursor-compat'; model=None; event=''; sent_done=False
    while True:
        raw=resp.readline()
        if not raw: break
        line=raw.decode('utf-8','replace').rstrip('\r\n')
        if not line: continue
        if line.startswith('event:'):
            event=line[6:].strip(); continue
        if not line.startswith('data:'): continue
        data=line[5:].strip()
        if data=='[DONE]':
            sent_done=True
            yield b'data: [DONE]\n\n'
            continue
        try: obj=json.loads(data)
        except Exception: continue
        if obj.get('id'): resp_id=obj.get('id')
        if obj.get('model'): model=obj.get('model')
        typ=obj.get('type') or event
        delta=obj.get('delta') or obj.get('text') or ''
        if typ in ('response.output_text.delta','response.refusal.delta') and delta:
            yield ('data: '+chunk_json(resp_id,model,str(delta))+'\n\n').encode('utf-8')
        elif typ in ('response.completed','response.output_text.done'):
            yield ('data: '+chunk_json(resp_id,model,'','stop')+'\n\n').encode('utf-8')
            yield b'data: [DONE]\n\n'
            sent_done=True
    if not sent_done:
        yield ('data: '+chunk_json(resp_id,model,'','stop')+'\n\n').encode('utf-8')
        yield b'data: [DONE]\n\n'

class Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    def setup(self):
        super().setup()
        try:
            self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except Exception:
            pass
    def log_message(self,fmt,*args): sys.stderr.write('%s %s\n'%(time.strftime('%Y-%m-%dT%H:%M:%S%z'),fmt%args))
    def base_path(self):
        p=self.path
        if p.startswith('/cursor/v1/'): p='/v1/'+p[len('/cursor/v1/'):]
        elif p=='/cursor/v1': p='/v1'
        elif not p.startswith('/v1'): p='/v1'+(p if p.startswith('/') else '/'+p)
        return p
    def make_headers(self,n=None):
        h={}
        for k,v in self.headers.items():
            if k.lower() not in HOP: h[k]=v
        if n is not None: h['Content-Length']=str(n)
        return h
    def common(self,changed=False,mode='newapi-native'):
        self.send_header('X-SubAPI-Cursor-Compat',mode); self.send_header('Connection','close')
        if changed: self.send_header('X-SubAPI-Cursor-Transform','responses-native')
    def proxy(self,method):
        body=None; changed=False; stream=False; mode='chat'; path=self.base_path()
        if method in ('POST','PUT','PATCH'):
            raw=self.rfile.read(int(self.headers.get('Content-Length') or 0)); body=raw
            if raw:
                try:
                    d=json.loads(raw.decode('utf-8'))
                    if isinstance(d,dict) and isinstance(d.get('input'),list):
                        d['input']=normalize_responses_input(d['input']); changed=True
                    stream=bool(isinstance(d,dict) and d.get('stream'))
                    if path.split('?',1)[0].endswith('/chat/completions') and isinstance(d,dict) and 'input' in d and 'messages' not in d:
                        # Cursor Agent needs Chat Completions tool_calls so file edits can execute; normalize body but keep /chat/completions.
                        d2,changed2=to_chat_payload(d); changed=changed or changed2; body=json.dumps(d2,ensure_ascii=False,separators=(',',':')).encode(); mode='chat'
                    elif path.split('?',1)[0].endswith('/chat/completions') and isinstance(d,dict):
                        d2,changed2=to_chat_payload(d)
                        if changed2: changed=True; body=json.dumps(d2,ensure_ascii=False,separators=(',',':')).encode()
                    elif isinstance(d,dict) and changed and body==raw:
                        body=json.dumps(d,ensure_ascii=False,separators=(',',':')).encode()
                except Exception as e: self.log_message('transform failed: %r',e)
        req=Request(UPSTREAM+path,data=body,headers=self.make_headers(len(body) if body is not None else None),method=method)
        try:
            with urlopen(req,timeout=3600) as r:
                if stream:
                    self.send_response(r.status)
                    for k,v in r.headers.items():
                        if k.lower() not in HOP: self.send_header(k,v)
                    self.common(changed,'newapi-native-responses' if mode=='responses' else 'newapi-native'); self.end_headers()
                    iterator=responses_sse_to_chat(r) if mode=='responses' else iter(lambda:r.readline(),b'')
                    for c in iterator:
                        if not c: break
                        try:
                            self.connection.sendall(c)
                        except (BrokenPipeError, ConnectionResetError, OSError):
                            break
                else:
                    payload=r.read()
                    if mode=='responses': payload=responses_json_to_chat(payload)
                    self.send_response(r.status)
                    for k,v in r.headers.items():
                        if k.lower() not in HOP: self.send_header(k,v)
                    self.send_header('Content-Length',str(len(payload))); self.common(changed,'newapi-native-responses' if mode=='responses' else 'newapi-native'); self.end_headers(); self.wfile.write(payload)
        except HTTPError as e:
            payload=e.read(); self.send_response(e.code)
            for k,v in e.headers.items():
                if k.lower() not in HOP: self.send_header(k,v)
            self.send_header('Content-Length',str(len(payload))); self.common(changed); self.end_headers(); self.wfile.write(payload)
    def do_GET(self): self.proxy('GET')
    def do_POST(self): self.proxy('POST')
    def do_OPTIONS(self): self.proxy('OPTIONS')

if __name__=='__main__':
    print(f'listening on {LISTEN} -> {UPSTREAM}',flush=True)
    ThreadingHTTPServer(LISTEN,Handler).serve_forever()
