import asyncio,json,uuid,logging,websockets,random,time,os,hashlib
from fastapi import FastAPI, responses, Request
from fastapi.responses import JSONResponse, RedirectResponse
from datetime import datetime
import uvicorn,httpx,edge_tts

VOLC_APPID = "你的火山引擎AppID"
VOLC_AT = "你的火山引擎AccessToken"
DS_KEY = "你的DeepSeek API Key"

logging.basicConfig(level=logging.INFO);log=logging.getLogger("QinYi")

DEFAULT_PROVIDERS = [
    {"name":"DeepSeek","api_url":"https://api.deepseek.com","api_key":DS_KEY,"models":"deepseek-chat,deepseek-reasoner","selected":"deepseek-chat","priority":1,"enabled":True},
    {"name":"Claude","api_url":"https://api.anthropic.com","api_key":"","models":"claude-opus-4-8-20250514,claude-sonnet-5-20250601","selected":"claude-sonnet-5-20250601","priority":2,"enabled":False,"headers":"{\"anthropic-version\":\"2023-06-01\"}"},
    {"name":"OpenAI","api_url":"https://api.openai.com","api_key":"","models":"gpt-4o,gpt-4o-mini","selected":"gpt-4o","priority":3,"enabled":False},
]
DEFAULT_MCP = [
    {"name":"示例MCP","url":"ws://localhost:8080/mcp","token":"","enabled":False}
]

CFG={
    "config_password":"songziyan",
    "bot_name":"琴一","master_name":"主人",
    "sys_prompt":"你是琴一，一个温柔可爱的AI陪伴机器人。说话像朋友一样自然，关心主人的情绪。称呼主人为\"主人\"。",
    "personality_tone":"温柔","conversation_style":"简洁","formality":"朋友",
    "tts_voice":"zh-CN-XiaoxiaoNeural","tts_speed":"1.0","tts_pitch":"0","tts_volume":"1.0",
    "welcome_msg":"主人你好呀，我是琴一~今天想聊什么呢？","goodbye_msg":"主人再见~",
    "emotion_enabled":"true","emotion_style":"auto",
    "keep_history":"true","max_history":"20","enable_smalltalk":"true","smalltalk_interval":"300",
    "auto_greet":"true","enable_interrupt":"true","voice_timeout":"5",
    "led_enabled":"true","led_brightness":"128","led_color":"#00d2ff","led_breathing":"true",
    "screen_brightness":"180","screen_saver":"clock","screen_timeout":"30","show_time":"true","show_battery":"true",
    "wake_word":"你好琴一","wake_sensitivity":"medium","listening_mode":"auto","double_tap_action":"camera",
    "server_url":"ws://your_server_ip:8001","enable_ota":"true","ota_url":"",
    "web_search_enabled":"true",
    "search_api_key":"",
    "search_api_provider":"anysearch",
    "enable_debug":"false","timezone":"Asia/Shanghai",
    "llm_providers":DEFAULT_PROVIDERS,
    "mcp_servers":DEFAULT_MCP,
}

EMOJI_MAP={"happy":"😊","sad":"😢","angry":"😠","surprised":"😮","sleepy":"😴","thinking":"🤔","neutral":"😐","laughing":"😂","love":"🥰","confused":"😕","singing":"🎵"}

def detect_emotion(text):
    t=text.lower()
    if any(w in t for w in["哈哈","笑死","搞笑","哈哈哈","hhhh","😂"]):return"laughing"
    if any(w in t for w in["爱","喜欢","想你了","想你","宝贝","亲爱的","🥰","❤️"]):return"love"
    if any(w in t for w in["笑","开心","高兴","棒","好","谢谢","感谢","嘻嘻","nice","great"]):return"happy"
    if any(w in t for w in["哭","难过","伤心","悲伤","委屈","呜呜","唉","不开心","泪","😭"]):return"sad"
    if any(w in t for w in["生气","愤怒","烦","滚","讨厌","烦死","气死","😠","🔥"]):return"angry"
    if any(w in t for w in["惊","哇","真的吗","不会吧","天哪","啊?","什么?","😮"]):return"surprised"
    if any(w in t for w in["困","累","睡","晚安","疲惫","zzz","😴"]):return"sleepy"
    if any(w in t for w in["唱","歌","音乐","听","🎵","🎶"]):return"singing"
    if any(w in t for w in["?","？","吗","什么","怎么","为什么","不懂","啥","谁","哪"]):return"thinking"
    return"neutral"

class Session:
    def __init__(s,w):
        s.ws=w;s.id=uuid.uuid4().hex[:8];s.st="idle"
        s.q=asyncio.Queue();s.history=[]
        s.created=s.last_active=time.time();s.msg_count=0
        s.tts_task=s.asr_task=None
sessions={}

# ====== 工具定义 ======
TOOLS = [
    {"type":"function","function":{"name":"web_search","description":"联网搜索最新信息。当主人问新闻、查资料、搜索信息时调用这个工具","parameters":{"type":"object","properties":{"query":{"type":"string","description":"搜索关键词"}},"required":["query"]}}},
    {"type":"function","function":{"name":"get_time","description":"获取当前日期和时间","parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"generate_file","description":"生成一个文件（代码、笔记、列表等），保存后会告诉主人编号，主人可以去网页查看和下载","parameters":{"type":"object","properties":{"filename":{"type":"string","description":"文件名，如 code.py / notes.md / list.txt"},"content":{"type":"string","description":"文件内容"}},"required":["filename","content"]}}},
    {"type":"function","function":{"name":"call_mcp","description":"调用MCP服务器上的工具。当需要控制智能设备、查询传感器数据或其他MCP服务器提供的功能时调用","parameters":{"type":"object","properties":{"server_index":{"type":"integer","description":"MCP服务器编号，从0开始"},"tool_name":{"type":"string","description":"要调用的工具名称"},"tool_args":{"type":"object","description":"工具参数"}},"required":["server_index","tool_name","tool_args"]}}},
]

# 文件存储
FILES_DIR = os.path.join(os.path.dirname(__file__), "generated_files")
os.makedirs(FILES_DIR, exist_ok=True)
file_counter = [0]
generated_files = []

async def call_llm(messages, providers=None):
    """递归调用LLM，支持function calling。工具执行结果自动回喂LLM"""
    if not providers: providers = CFG.get("llm_providers", DEFAULT_PROVIDERS)
    active = [p for p in providers if p.get("enabled") and p.get("api_key")]
    active.sort(key=lambda x: x.get("priority", 99))
    if not active: return None
    for p in active:
        try:
            name, url, key, model = p.get("name",""), p.get("api_url","").rstrip("/"), p.get("api_key",""), p.get("selected","")
            hdrs = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
            if name == "Claude":
                try: extra = json.loads(p.get("headers","{}"))
                except: extra = {}
                hdrs.update(extra); hdrs["x-api-key"] = key
                payload = {"model": model, "max_tokens": 2048, "messages": messages, "stream": True}
            else:
                payload = {"model": model, "messages": messages, "tools": TOOLS, "stream": True}
            api_url = f"{url}/chat/completions" if not url.endswith("/chat/completions") else url
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.post(api_url, json=payload, headers=hdrs)
                if r.status_code != 200: continue
                full, tool_calls = "", []
                async for l in r.aiter_lines():
                    if l.startswith("data: ") and l[6:] != "[DONE]":
                        try:
                            d = json.loads(l[6:])
                            delta = d["choices"][0]["delta"]
                            if delta.get("content"): full += delta["content"]
                            tc = delta.get("tool_calls")
                            if tc:
                                for t in tc:
                                    if t.get("id"):
                                        tool_calls.append({"id": t["id"], "type": "function", "function": {"name": t.get("function",{}).get("name",""), "arguments": t.get("function",{}).get("arguments","")}})
                                    else:
                                        for existing in tool_calls:
                                            if existing.get("index") == t.get("index"):
                                                existing["function"]["arguments"] += t.get("function",{}).get("arguments","")
                        except: pass
                if not tool_calls: return full if full else None
                # 执行工具
                tool_msgs = list(messages)
                tool_msgs.append({"role": "assistant", "content": None, "tool_calls": tool_calls})
                for tc in tool_calls:
                    fn_name = tc["function"]["name"]
                    try: args = json.loads(tc["function"]["arguments"]) if tc["function"].get("arguments") else {}
                    except: args = {}
                    result = "执行失败"
                    if fn_name == "web_search":
                        result = await web_search(args.get("query",""))
                    elif fn_name == "get_time":
                        now = datetime.now(); wd = ['一','二','三','四','五','六','日'][now.weekday()]
                        result = f"{now.year}年{now.month}月{now.day}日 {now.hour}:{now.minute:02d} 星期{wd}"
                    elif fn_name == "generate_file":
                        filename = args.get("filename","file.txt")
                        content = args.get("content","")
                        file_counter[0] += 1; fid = file_counter[0]
                        filepath = os.path.join(FILES_DIR, f"{fid}_{filename}")
                        with open(filepath, "w", encoding="utf-8") as f: f.write(content)
                        generated_files.append({"id":fid, "filename":filename, "path":f"{fid}_{filename}", "time":datetime.now().strftime("%H:%M")})
                        result = f"文件已生成，编号 #{fid}，去 /files 下载"
                    elif fn_name == "call_mcp":
                        result = await call_mcp_tool(args.get("server_index",0), args.get("tool_name",""), args.get("tool_args",{}))
                    tool_msgs.append({"role": "tool", "tool_call_id": tc["id"], "content": str(result)})
                final = await call_llm(tool_msgs, providers)
                return final
        except Exception as e: log.error(f"LLM {p.get('name','?')}: {e}"); continue
    return None

async def web_search(query: str):
    """AnySearch 搜索"""
    try:
        key = CFG.get("search_api_key","")
        headers = {"Content-Type": "application/json"}
        if key: headers["Authorization"] = f"Bearer {key}"
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post("https://api.anysearch.com/mcp", json={"jsonrpc":"2.0","method":"tools/call","params":{"name":"search","arguments":{"query":query,"max_results":5}},"id":"1"}, headers=headers)
            if r.status_code != 200: return f"搜索失败 {r.status_code}"
            texts = []
            for item in r.json().get("result",{}).get("content",[]):
                if isinstance(item,dict): texts.append(item.get("text",""))
                elif isinstance(item,str): texts.append(item)
            return "\n".join(texts[:3]) if texts else "无结果"
    except Exception as e: return f"搜索出错：{e}"

async def call_mcp_tool(server_index: int, tool_name: str, tool_args: dict):
    """调用MCP服务器上的工具。真正的MCP协议通信。"""
    servers = CFG.get("mcp_servers", [])
    if server_index < 0 or server_index >= len(servers):
        return f"MCP服务器 #{server_index} 不存在"
    srv = servers[server_index]
    url = srv.get("url","")
    token = srv.get("token","")
    if not url: return "MCP地址为空"
    try:
        # MCP采用JSON-RPC 2.0 over WebSocket
        hdrs = {}
        if token: hdrs["Authorization"] = f"Bearer {token}"
        async with websockets.connect(url, extra_headers=hdrs, open_timeout=5) as ws:
            req_id = uuid.uuid4().hex[:8]
            await ws.send(json.dumps({"jsonrpc":"2.0","method":"tools/call","params":{"name":tool_name,"arguments":tool_args},"id":req_id}))
            try:
                resp = await asyncio.wait_for(ws.recv(), timeout=10)
                data = json.loads(resp) if isinstance(resp,str) else json.loads(resp.decode())
                result = data.get("result", data.get("error", "无返回"))
                return json.dumps(result, ensure_ascii=False)[:500]
            except asyncio.TimeoutError:
                return "MCP调用超时"
    except Exception as e:
        return f"MCP出错：{str(e)[:100]}"

async def get_sys_msg(s)->list:
    now = datetime.now()
    tone = CFG.get("personality_tone","温柔")
    style = CFG.get("conversation_style","简洁")
    formal = CFG.get("formality","朋友")
    flen = "回复简洁" if style=="简洁" else "详细展开" if style=="详细" else "话痨模式"
    fmap = {"朋友":"朋友间随意","礼貌":"礼貌尊重","亲密":"亲密语气","官方":"正式专业"}
    # 列出MCP工具
    mcp_desc = ""
    for i, srv in enumerate(CFG.get("mcp_servers",[])):
        if srv.get("enabled") and srv.get("url"):
            mcp_desc += f"\n- 通过call_mcp(server_index={i}) 控制 {srv['name']}"
    msgs = [{"role":"system","content":f"""{CFG['sys_prompt']}

[当前]
名字:{CFG['bot_name']} | 主人:{CFG['master_name']}
时间:{now.strftime('%Y年%m月%d日 %H:%M')} 星期{['一','二','三','四','五','六','日'][now.weekday()]}
语气:{tone}|{fmap.get(formal,'朋友')}
风格:{flen}

你有以下工具可用：
- web_search: 联网搜索
- get_time: 获取时间日期
- generate_file: 生成文件供下载
- call_mcp(server_index, tool_name, tool_args): 调用MCP服务器{mcp_desc}
"""}]
    if CFG.get("keep_history")=="true":
        for h in s.history[-int(CFG.get("max_history","20")):]: msgs.append(h)
    return msgs

async def asr(s):
    h = {"Authorization": f"Bearer; {VOLC_AT}"}
    async with websockets.connect("wss://openspeech.bytedance.com/api/v2/asr", extra_headers=h) as a:
        await a.send(json.dumps({"app":{"appid":VOLC_APPID,"cluster":"volcengine_input_common"},"user":{"uid":s.id},"audio":{"format":"opus","rate":16000}}))
        async def sa():
            while True:
                d = await s.q.get()
                if d is None: break
                await a.send(d)
        t = asyncio.create_task(sa())
        try:
            async for m in a:
                if isinstance(m,str):
                    d = json.loads(m)
                    if d.get("type")=="final_result":
                        tx = "".join(r.get("text","") for r in d.get("result",[]) if r.get("text"))
                        if tx:
                            s.last_active = time.time(); s.msg_count += 1
                            s.history.append({"role":"user","content":tx})
                            await s.ws.send(json.dumps({"type":"stt","text":tx}))
                            asyncio.create_task(llm(s,tx))
                        break
        finally: t.cancel()

async def llm(s,text):
    await s.ws.send(json.dumps({"type":"llm","emotion":"thinking"}))
    try:
        msgs = await get_sys_msg(s)
        reply = await call_llm(msgs)
        if reply:
            emotion = detect_emotion(reply)
            await s.ws.send(json.dumps({"type":"llm","emotion":emotion,"text":reply}))
            s.history.append({"role":"assistant","content":reply})
            s.tts_task = asyncio.create_task(tts(s,reply))
    except Exception as e:
        log.error(f"LLM:{e}")

async def tts(s,text):
    await s.ws.send(json.dumps({"type":"tts","state":"start"}))
    try:
        com = edge_tts.Communicate(text, CFG["tts_voice"], rate=CFG["tts_speed"])
        async for c in com.stream():
            if c["type"]=="audio": await s.ws.send(c["data"])
    except:
        try:
            com = edge_tts.Communicate(text, "zh-CN-XiaoxiaoNeural")
            async for c in com.stream():
                if c["type"]=="audio": await s.ws.send(c["data"])
        except: pass
    await s.ws.send(json.dumps({"type":"tts","state":"stop"}))

async def hdl(ws):
    s = Session(ws); sessions[s.id] = s
    try:
        async for m in ws:
            if isinstance(m,str):
                d = json.loads(m); tp = d.get("type")
                if tp == "hello":
                    await ws.send(json.dumps({"type":"hello","transport":"websocket","session_id":s.id,"audio_params":{"format":"opus","sample_rate":24000}}))
                    log.info(f"上线[{s.id}]"); s.st = "idle"
                    if CFG.get("auto_greet")=="true":
                        await asyncio.sleep(0.5)
                        await ws.send(json.dumps({"type":"llm","emotion":"happy","text":CFG["welcome_msg"]}))
                        s.tts_task = asyncio.create_task(tts(s,CFG["welcome_msg"]))
                elif tp == "listening":
                    if d.get("state")=="start": s.st = "listen"; s.asr_task = asyncio.create_task(asr(s))
                    else: s.st = "idle"; await s.q.put(None)
                elif tp == "abort":
                    s.st = "idle"; await s.q.put(None)
                    if s.tts_task: s.tts_task.cancel()
            elif s.st == "listen": await s.q.put(m)
    except: pass
    finally:
        await s.q.put(None); sessions.pop(s.id,None)
        log.info(f"离线[{s.id}] 共{s.msg_count}次")

app = FastAPI()
start_time = time.time()

@app.get("/")
async def root(): return {"status":"ok","name":"QinYi","ver":"5.1","online":len(sessions)}

@app.get("/api/config")
async def gc():
    pub = dict(CFG)
    for k in ["llm_providers","mcp_servers"]:
        pub[k]=[]
        for item in CFG.get(k,[]):
            cp = dict(item)
            for sk in ["api_key","token"]:
                if cp.get(sk): cp[sk] = "••••••"
            pub[k].append(cp)
    return pub

@app.post("/api/config")
async def sc(d:dict):
    for k in d:
        if k in CFG: CFG[k]=d[k]
    return {"status":"ok"}

@app.get("/api/stats")
async def stats(): return {"online_devices":len(sessions),"uptime":time.time()-start_time,"version":"5.1","active_sessions":[{"id":s.id,"msg_count":s.msg_count} for s in sessions.values()],"files_count":len(generated_files)}

@app.get("/files")
async def files_page():
    rows = "".join(f'<tr><td>#{f["id"]}</td><td>{f["filename"]}</td><td>{f["time"]}</td><td><a href="/api/files/{f["id"]}" download>⬇</a></td></tr>' for f in reversed(generated_files[-50:]))
    chat_rows = ""
    for sid, s in list(sessions.items())[:5]:
        chat_rows += f"<tr><td>{sid[:6]}..</td><td>{s.msg_count}条</td><td>{(time.time()-s.created)//60:.0f}分钟</td></tr>"
        for h in s.history[-5:]:
            r = "👤" if h["role"]=="user" else "🤖"
            chat_rows += f'<tr><td></td><td colspan=3 style="color:#888;font-size:11px">{r} {h.get("content","")[:80]}</td></tr>'
    return responses.HTMLResponse(f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>琴一 · 记录</title>
<style>body{{font-family:sans-serif;background:#0f0c29;color:#e0e0e0;padding:40px;max-width:800px;margin:auto}}h1{{background:linear-gradient(90deg,#00d2ff,#928dab);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}table{{width:100%;border-collapse:collapse;margin-bottom:30px}}th,td{{padding:10px;text-align:left;border-bottom:1px solid rgba(255,255,255,0.06);font-size:13px}}th{{color:#888;font-size:11px;letter-spacing:1px}}a{{color:#00d2ff}}</style></head><body><a href="/config" style="color:#00d2ff;font-size:13px;text-decoration:none">← 返回配置</a><h1>🤖 记录与文件</h1>
<h2>💬 对话</h2><table>{"<tr><td colspan=4 style=color:#666>暂无</td></tr>" if not sessions else chat_rows}</table>
<h2>📁 文件 <a href="/api/files/clear" style="font-size:12px;font-weight:normal" onclick="return confirm('清空所有文件？')">清空</a></h2>
<table><tr><th>#</th><th>文件名</th><th>时间</th><th>操作</th></tr>{"<tr><td colspan=4 style=color:#666>暂无</td></tr>" if not generated_files else rows}</table><script>setInterval(()=>location.reload(),10000)</script></body></html>""")

@app.get("/api/files/{file_id}")
async def download_file(file_id:int):
    for f in generated_files:
        if f["id"]==file_id:
            fp = os.path.join(FILES_DIR, f["path"])
            if os.path.exists(fp): return responses.FileResponse(fp, filename=f["filename"])
    return responses.HTMLResponse("文件不存在", status_code=404)

@app.get("/api/files/clear")
async def clear_files():
    generated_files.clear(); file_counter[0]=0
    return responses.RedirectResponse("/files")

@app.get("/config")
async def cfg(request:Request):
    pwd = request.query_params.get("pwd",""); pwd2 = request.cookies.get("config_pwd","")
    correct = CFG.get("config_password","songziyan")
    if pwd != correct and pwd2 != correct:
        return responses.HTMLResponse(f"""<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>🔒 验证</title><style>body{{font-family:sans-serif;background:linear-gradient(135deg,#0f0c29,#302b63,#24243e);min-height:100vh;display:flex;align-items:center;justify-content:center;color:#e0e0e0;padding:20px}}.card{{background:rgba(255,255,255,0.06);border-radius:16px;padding:28px 24px;width:280px;text-align:center}}.card h1{{font-size:22px;background:linear-gradient(90deg,#00d2ff,#928dab);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}input{{width:100%;padding:10px;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.12);border-radius:8px;font-size:14px;color:#e0e0e0;text-align:center;margin-bottom:8px;box-sizing:border-box}}input:focus{{outline:none;border-color:#00d2ff}}.btn{{width:100%;padding:10px;border:none;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer;background:linear-gradient(90deg,#00d2ff,#928dab);color:#fff;box-sizing:border-box}}.hint{{color:#666;font-size:12px;margin-top:12px}}</style></head><body><div class="card"><h1>🤖 琴一</h1><p style="color:#888;font-size:13px">配置管理需要验证</p><input type="password" id="pwd" placeholder="密码" onkeydown="if(event.key==='Enter')go()" autofocus><button class="btn" onclick="go()">解锁</button><div class="hint">提示：主人的名字</div></div><script>function go(){{window.location.href='/config?pwd='+encodeURIComponent(document.getElementById('pwd').value)}}</script></body></html>""")
    resp = responses.HTMLResponse(render_config_html())
    resp.set_cookie(key="config_pwd",value=correct,httponly=True,samesite="strict")
    return resp

def render_config_html():
    return r"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>琴一</title>
<style>
body{background:#0f0c29;color:#e0e0e0;font-family:sans-serif;padding:20px;max-width:600px;margin:auto}
h1{background:linear-gradient(90deg,#00d2ff,#928dab);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.card{background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.08);border-radius:12px;padding:20px;margin-bottom:12px}
.card:hover{background:rgba(255,255,255,0.08)}
.btn{width:100%;padding:12px;border:none;border-radius:8px;font-size:14px;cursor:pointer;background:linear-gradient(90deg,#00d2ff,#928dab);color:#fff;margin-top:12px}
a{color:#00d2ff;text-decoration:none}
#app{margin-top:12px}
label{display:block;color:#888;font-size:12px;margin-top:10px}
input,textarea,select{width:100%;padding:10px;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.1);border-radius:8px;font-size:13px;color:#e0e0e0;margin-bottom:6px;box-sizing:border-box}
select option{background:#1a1a2e;color:#e0e0e0}
textarea{min-height:80px;resize:vertical}
.gr{display:grid;grid-template-columns:1fr 1fr;gap:10px}
</style></head>
<body>
<div id="app"></div>
<script>
var C={};
function g(u,cb){var x=new XMLHttpRequest();x.open('GET',u,true);x.onload=function(){cb(JSON.parse(x.responseText))};x.send()}
function p(u,d,cb){var x=new XMLHttpRequest();x.open('POST',u,true);x.setRequestHeader('Content-Type','application/json');x.onload=function(){cb(x.status)};x.send(JSON.stringify(d))}

function main(){
  g('/api/config',function(d){C=d;showMain()})
}

function showMain(){
  var a=0;if(C.llm_providers){for(var i=0;i<C.llm_providers.length;i++){if(C.llm_providers[i].enabled&&C.llm_providers[i].api_key)a++}}
  var h='<h1>&#x1F916; 琴一 控制台</h1>';
  h+='<div class="card"><b>&#x1F9E0; 人格设定</b><p style="color:#888;font-size:12px">性格·语气·提示词</p><button class="btn" onclick="page(\'personality\')">修改</button></div>';
  h+='<div class="card"><b>API 模型</b><p style="color:#888;font-size:12px">'+a+'个活跃供应商</p><button class="btn" onclick="page(\'api\')">管理</button></div>';
  h+='<div class="card"><b>对话记录</b><p style="color:#888;font-size:12px">实时对话及文件下载</p><button class="btn" onclick="window.open(\'/files\')">打开</button></div>';
  h+='<button class="btn" onclick="save()">保存全部配置</button>';
  document.getElementById('app').innerHTML=h
}

function save(){
  p('/api/config',C,function(s){if(s==200)alert('已保存');else alert('失败')})
}

function page(n){
  g('/api/config',function(d){C=d;
    var h='<a href="#" onclick="showMain()" style="display:inline-block;margin-bottom:12px;color:#00d2ff">&larr; 返回</a>';
    if(n=='personality'){
      h+='<div class="card">';
      h+=mkSelect('personality_tone','语气',[{v:'温柔',l:'温柔'},{v:'活泼',l:'活泼'},{v:'幽默',l:'幽默'}]);
      h+=mkArea('sys_prompt','系统提示词');
      h+='</div>';
    }else if(n=='api'){
      h+='<p style="color:#888">添加多个LLM供应商，按优先级自动切换</p>';
      if(C.llm_providers){for(var i=0;i<C.llm_providers.length;i++){var p=C.llm_providers[i];
        h+='<div class="card"><b>'+(p.name||'?')+'</b>';
        h+=mkInp('llm_'+i+'_name','名称',p.name,function(v,i){C.llm_providers[i].name=v}.bind(null,i));
        h+=mkInp('llm_'+i+'_url','API地址',p.api_url,function(v,i){C.llm_providers[i].api_url=v}.bind(null,i));
        h+=mkInp('llm_'+i+'_key','Key',p.api_key&&p.api_key!=''?'***':'',function(v,i){C.llm_providers[i].api_key=v}.bind(null,i));
        h+='</div>'
      }}
    }
    h+='<button class="btn" onclick="save()">保存</button>';
    document.getElementById('app').innerHTML=h
  })
}

function mkSelect(k,l,ops){
  var h='<label>'+l+'</label><select onchange="C[\''+k+'\']=this.value">';
  for(var i=0;i<ops.length;i++){h+='<option'+(C[k]==ops[i].v?' selected':'')+' value="'+ops[i].v+'">'+ops[i].l+'</option>'}
  h+='</select>';return h
}
function mkArea(k,l){return'<label>'+l+'</label><textarea onchange="C[\''+k+'\']=this.value">'+(C[k]||'')+'</textarea>'}
function mkInp(id,l,v,cb){return'<label>'+l+'</label><input value="'+(v||'')+'" onchange="cb(this.value,'+0+')">'}

main()
</script>
</body>
</html>"""

@app.on_event("startup")
async def su(): asyncio.create_task(wss())
async def wss():
    async def h(w): await hdl(w)
    async with websockets.serve(h, "0.0.0.0", 8001):
        log.info(f"✅ 琴一 v5.1 | WS:8001 | HTTP:8000")
        await asyncio.Future()
if __name__ == "__main__":
    start_time = time.time()
    uvicorn.run(app, host="0.0.0.0", port=8000)
