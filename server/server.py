import asyncio,json,uuid,logging,websockets,random,time,os,hashlib
from fastapi import FastAPI, responses, Request
from fastapi import Body
from datetime import datetime
import uvicorn,httpx,edge_tts

logging.basicConfig(level=logging.INFO);log=logging.getLogger("QinYi")

DEFAULT_PROVIDERS = [
    {"name":"DeepSeek","api_url":"https://api.deepseek.com","api_key":"","models":"deepseek-chat,deepseek-reasoner","selected":"deepseek-chat","priority":1,"enabled":True},
    {"name":"Claude","api_url":"https://api.anthropic.com","api_key":"","models":"claude-opus-4-8-20250514,claude-sonnet-5-20250601","selected":"claude-sonnet-5-20250601","priority":2,"enabled":False,"headers":"{\"anthropic-version\":\"2023-06-01\"}"},
    {"name":"OpenAI","api_url":"https://api.openai.com","api_key":"","models":"gpt-4o,gpt-4o-mini","selected":"gpt-4o","priority":3,"enabled":False},
]
DEFAULT_MCP = [
    {"name":"示例MCP","url":"ws://localhost:8080/mcp","token":"","enabled":False}
]

CFG={
    "config_password":"songziyan",
    "bot_name":"琴一","master_name":"主人",
    "volc_appid":"","volc_at":"",
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
    "web_search_enabled":"true","search_api_key":"","search_api_provider":"anysearch",
    "enable_debug":"false","timezone":"Asia/Shanghai",
    "llm_providers":DEFAULT_PROVIDERS,
    "mcp_servers":DEFAULT_MCP,
    "custom_emojis":{},
}

EMOJI_MAP={"happy":"😊","sad":"😢","angry":"😠","surprised":"😮","sleepy":"😴","thinking":"🤔","neutral":"😐","laughing":"😂","love":"🥰","confused":"😕","singing":"🎵"}
EMOJI_LABELS={"happy":"开心","sad":"难过","angry":"生气","surprised":"惊讶","sleepy":"困了","thinking":"思考","neutral":"平静","laughing":"大笑","love":"爱你","confused":"疑惑","singing":"唱歌"}

def get_emoji(emotion_key):
    """获取表情符号，优先使用自定义映射"""
    custom = CFG.get("custom_emojis",{})
    if isinstance(custom,dict) and emotion_key in custom:
        return custom[emotion_key]
    return EMOJI_MAP.get(emotion_key,"😐")

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

# ====== 工具定义 (Function Calling) ======
TOOLS = [
    {"type":"function","function":{"name":"web_search","description":"联网搜索最新信息。当主人问新闻、查资料、搜索信息时调用这个工具","parameters":{"type":"object","properties":{"query":{"type":"string","description":"搜索关键词"}},"required":["query"]}}},
    {"type":"function","function":{"name":"get_time","description":"获取当前日期和时间","parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"generate_file","description":"生成一个文件（代码、笔记、列表等），保存后会告诉主人编号，主人可以去网页查看和下载","parameters":{"type":"object","properties":{"filename":{"type":"string","description":"文件名，如 code.py / notes.md / list.txt"},"content":{"type":"string","description":"文件内容"}},"required":["filename","content"]}}},
    {"type":"function","function":{"name":"call_mcp","description":"调用MCP服务器上的工具。当需要控制智能设备、查询传感器数据或其他MCP服务器提供的功能时调用","parameters":{"type":"object","properties":{"server_index":{"type":"integer","description":"MCP服务器编号，从0开始"},"tool_name":{"type":"string","description":"要调用的工具名称"},"tool_args":{"type":"object","description":"工具参数"}},"required":["server_index","tool_name","tool_args"]}}},
]

# ====== 文件存储 ======
FILES_DIR = os.path.join(os.path.dirname(__file__), "generated_files")
os.makedirs(FILES_DIR, exist_ok=True)
file_counter = [0]
generated_files = []

# ====== Edge TTS 参数格式转换 ======
def tts_rate(v):
    """1.0 -> +0%, 0.5 -> -50%, 1.5 -> +50%"""
    try: pct = int((float(v) - 1.0) * 100); return f"{pct:+d}%"
    except: return "+0%"
def tts_pitch(v):
    """0 -> +0Hz, -10 -> -10Hz, 10 -> +10Hz"""
    try: return f"{int(float(v)):+d}Hz"
    except: return "+0Hz"
def tts_volume(v):
    """1.0 -> +0%, 0.5 -> -50%, 1.5 -> +50%"""
    try: pct = int((float(v) - 1.0) * 100); return f"{pct:+d}%"
    except: return "+0%"

# ====== 工具实现 ======
async def web_search(query: str):
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
    servers = CFG.get("mcp_servers", [])
    if server_index < 0 or server_index >= len(servers):
        return f"MCP服务器 #{server_index} 不存在"
    srv = servers[server_index]
    url = srv.get("url",""); token = srv.get("token","")
    if not url: return "MCP地址为空"
    try:
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
            except asyncio.TimeoutError: return "MCP调用超时"
    except Exception as e: return f"MCP出错：{str(e)[:100]}"

# ====== LLM 调用（支持 Function Calling） ======
async def call_llm(messages, providers=None):
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
                # 执行工具并递归回喂
                tool_msgs = list(messages)
                tool_msgs.append({"role": "assistant", "content": None, "tool_calls": tool_calls})
                for tc in tool_calls:
                    fn_name = tc["function"]["name"]
                    try: args = json.loads(tc["function"]["arguments"]) if tc["function"].get("arguments") else {}
                    except: args = {}
                    result = "执行失败"
                    if fn_name == "web_search": result = await web_search(args.get("query",""))
                    elif fn_name == "get_time":
                        now = datetime.now(); wd = ['一','二','三','四','五','六','日'][now.weekday()]
                        result = f"{now.year}年{now.month}月{now.day}日 {now.hour}:{now.minute:02d} 星期{wd}"
                    elif fn_name == "generate_file":
                        filename = args.get("filename","file.txt"); content = args.get("content","")
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

# ====== 系统消息 ======
async def get_sys_msg(s)->list:
    now=datetime.now()
    tone=CFG.get("personality_tone","温柔")
    style=CFG.get("conversation_style","简洁")
    formal=CFG.get("formality","朋友")
    flen="""
- 回复简洁，不超过50字""" if style=="简洁" else"""
- 可以详细展开说明""" if style=="详细" else"""
- 多说一些，像朋友聊天一样""" if style=="话痨" else"""
- 只回答问题，不延伸"""
    fmap={"朋友":"朋友间随意语气","礼貌":"礼貌尊重的语气","亲密":"亲密的语气","官方":"正式专业语气"}
    # 列出MCP工具
    mcp_desc = ""
    for i, srv in enumerate(CFG.get("mcp_servers",[])):
        if srv.get("enabled") and srv.get("url"):
            mcp_desc += f"\n- 通过call_mcp(server_index={i}) 控制 {srv['name']}"
    msgs=[{"role":"system","content":f"""{CFG['sys_prompt']}

【当前信息】
- 名字:{CFG['bot_name']} | 主人:{CFG['master_name']}
- 时间:{now.strftime('%Y年%m月%d日 %H:%M')} 星期{['一','二','三','四','五','六','日'][now.weekday()]}
- 语气:{tone}|{fmap.get(formal,'朋友')}
{flen}

【可用工具】
- web_search: 联网搜索最新信息
- get_time: 获取当前时间
- generate_file: 生成文件供下载
- call_mcp(server_index, tool_name, tool_args): 调用MCP服务器{mcp_desc}

需要用到工具时，请调用对应的function。
"""}]
    if CFG.get("keep_history")=="true":
        for h in s.history[-int(CFG.get("max_history","20")):]:msgs.append(h)
    return msgs

# ====== 核心流程 ======
async def asr(s):
    h={"Authorization":f"Bearer; {CFG.get('volc_at','')}"}
    async with websockets.connect("wss://openspeech.bytedance.com/api/v2/asr",extra_headers=h)as a:
        await a.send(json.dumps({"app":{"appid":CFG.get('volc_appid',''),"cluster":"volcengine_input_common"},"user":{"uid":s.id},"audio":{"format":"opus","rate":16000}}))
        async def sa():
            while True:
                d=await s.q.get()
                if d is None:break
                await a.send(d)
        t=asyncio.create_task(sa())
        try:
            async for m in a:
                if isinstance(m,str):
                    d=json.loads(m)
                    if d.get("type")=="final_result":
                        tx="".join(r.get("text","")for r in d.get("result",[])if r.get("text"))
                        if tx:
                            s.last_active=time.time();s.msg_count+=1
                            s.history.append({"role":"user","content":tx})
                            await s.ws.send(json.dumps({"type":"stt","text":tx}))
                            asyncio.create_task(llm(s,tx))
                        break
        finally:t.cancel()

async def llm(s,text):
    await s.ws.send(json.dumps({"type":"llm","emotion":"thinking"}))
    try:
        msgs=await get_sys_msg(s)
        reply=await call_llm(msgs)
        if reply:
            emotion=detect_emotion(reply)
            if CFG.get("emotion_style")=="fixed":
                fe=CFG.get("fixed_emotion","")
                if fe:emotion=fe
            await s.ws.send(json.dumps({"type":"llm","emotion":emotion,"text":reply}))
            s.history.append({"role":"assistant","content":reply})
            s.tts_task=asyncio.create_task(tts(s,reply))
    except Exception as e:
        log.error(f"LLM:{e}")
        await s.ws.send(json.dumps({"type":"llm","emotion":"sad","text":"唔…我卡住了，再说一遍好不好？"}))

async def tts(s,text):
    await s.ws.send(json.dumps({"type":"tts","state":"start"}))
    try:
        rate=tts_rate(CFG.get("tts_speed","1.0"))
        pitch=tts_pitch(CFG.get("tts_pitch","0"))
        volume=tts_volume(CFG.get("tts_volume","1.0"))
        com=edge_tts.Communicate(text,CFG["tts_voice"],rate=rate,pitch=pitch,volume=volume)
        async for c in com.stream():
            if c["type"]=="audio":await s.ws.send(c["data"])
    except:
        try:
            com=edge_tts.Communicate(text,"zh-CN-XiaoxiaoNeural",rate="+0%")
            async for c in com.stream():
                if c["type"]=="audio":await s.ws.send(c["data"])
        except:pass
    await s.ws.send(json.dumps({"type":"tts","state":"stop"}))

async def hdl(ws):
    s=Session(ws);sessions[s.id]=s
    try:
        async for m in ws:
            if isinstance(m,str):
                d=json.loads(m);tp=d.get("type")
                if tp=="hello":
                    await ws.send(json.dumps({"type":"hello","transport":"websocket","session_id":s.id,"audio_params":{"format":"opus","sample_rate":24000}}))
                    log.info(f"✨上线[{s.id}]");s.st="idle"
                    if CFG.get("auto_greet")=="true":
                        await asyncio.sleep(0.5)
                        await ws.send(json.dumps({"type":"llm","emotion":"happy","text":CFG["welcome_msg"]}))
                        s.tts_task=asyncio.create_task(tts(s,CFG["welcome_msg"]))
                elif tp=="listening":
                    if d.get("state")=="start":s.st="listen";s.asr_task=asyncio.create_task(asr(s))
                    else:s.st="idle";await s.q.put(None)
                elif tp=="abort":
                    s.st="idle";await s.q.put(None)
                    if s.tts_task:s.tts_task.cancel()
                    log.info(f"⏹打断[{s.id}]")
            elif s.st=="listen":await s.q.put(m)
    except:pass
    finally:
        await s.q.put(None);sessions.pop(s.id,None)
        log.info(f"👋离线[{s.id}]共{s.msg_count}次")

# ====== FastAPI 应用 ======
app=FastAPI()
start_time=time.time()

@app.get("/")
async def root():return{"status":"ok","name":"QinYi","ver":"5.3","online":len(sessions)}

@app.get("/api/config")
async def gc():
    pub=dict(CFG)
    for k in ["llm_providers","mcp_servers"]:
        pub[k]=[]
        for item in CFG.get(k,[]):
            cp=dict(item)
            for sk in ["api_key","token"]:
                if cp.get(sk):cp[sk]="••••••"
            pub[k].append(cp)
    return pub

@app.post("/api/config")
async def sc(d: dict = Body(...)):
    for k in d:
        if k in CFG:CFG[k]=d[k]
    return{"status":"ok"}

@app.get("/api/stats")
async def stats():return{
    "online_devices":len(sessions),
    "uptime":time.time()-start_time,"version":"5.3",
    "active_sessions":[{"id":s.id,"msg_count":s.msg_count}for s in sessions.values()],
    "files_count":len(generated_files),
}

# ====== 文件管理页面 ======
@app.get("/files")
async def files_page():
    rows = "".join(f'<tr><td>#{f["id"]}</td><td>{f["filename"]}</td><td>{f["time"]}</td><td><a href="/api/files/{f["id"]}" download>⬇</div></td></tr>' for f in reversed(generated_files[-50:]))
    chat_rows = ""
    for sid, s in list(sessions.items())[:5]:
        chat_rows += f"<tr><td>{sid[:6]}..</td><td>{s.msg_count}条</td><td>{(time.time()-s.created)//60:.0f}分钟</td></tr>"
        for h in s.history[-5:]:
            r = "👤" if h["role"]=="user" else "🤖"
            chat_rows += f'<tr><td></td><td colspan=3 style="color:#888;font-size:11px">{r} {h.get("content","")[:80]}</td></tr>'
    no_data = '<tr><td colspan=4 style=color:#666>暂无</td></tr>'
    return responses.HTMLResponse(f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>琴一 · 记录</title>
<style>body{{font-family:sans-serif;background:#0f0c29;color:#e0e0e0;padding:40px;max-width:800px;margin:auto}}h1{{background:linear-gradient(90deg,#00d2ff,#928dab);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}table{{width:100%;border-collapse:collapse;margin-bottom:30px}}th,td{{padding:10px;text-align:left;border-bottom:1px solid rgba(255,255,255,0.06);font-size:13px}}th{{color:#888;font-size:11px;letter-spacing:1px}}a{{color:#00d2ff}}</style></head><body><a href="/config?pwd={CFG.get("config_password","songziyan")}" style="color:#00d2ff;font-size:13px;text-decoration:none">← 返回配置</a><h1>🤖 记录与文件</h1>
<h2>💬 对话</h2><table>{"<tr><td colspan=4 style=color:#666>暂无</td></tr>" if not sessions else chat_rows}</table>
<h2>📁 文件 <a href="/api/files/clear" style="font-size:12px;font-weight:normal" onclick="return confirm('清空所有文件？')">清空</a></h2>
<table><tr><th>#</th><th>文件名</th><th>时间</th><th>操作</th></tr>{no_data if not generated_files else rows}</table><script>
setInterval(()=>location.reload(),10000);
document.addEventListener('keydown',function(e){{if(e.key==='Escape'){{var bk=document.querySelector('a[href*="config"]');if(bk)bk.click()}}}});
</script></body></html>""")

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

# ====== 密码验证 + 配置页面 ======
@app.get("/config")
async def cfg(request:Request):
    pwd = request.query_params.get("pwd",""); pwd2 = request.cookies.get("config_pwd","")
    correct = CFG.get("config_password","songziyan")
    if pwd != correct and pwd2 != correct:
        return responses.HTMLResponse(f"""<!DOCTYPE html><html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>🔒 验证</title>
<style>body{{font-family:sans-serif;background:linear-gradient(135deg,#0f0c29,#302b63,#24243e);min-height:100vh;display:flex;align-items:center;justify-content:center;color:#e0e0e0;padding:20px}}.card{{background:rgba(255,255,255,0.06);border-radius:16px;padding:28px 24px;width:280px;text-align:center}}.card h1{{font-size:22px;background:linear-gradient(90deg,#00d2ff,#928dab);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}input{{width:100%;padding:10px;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.12);border-radius:8px;font-size:14px;color:#e0e0e0;text-align:center;margin-bottom:8px;box-sizing:border-box}}input:focus{{outline:none;border-color:#00d2ff}}.btn{{width:100%;padding:10px;border:none;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer;background:linear-gradient(90deg,#00d2ff,#928dab);color:#fff;box-sizing:border-box}}.hint{{color:#666;font-size:12px;margin-top:12px}}</style></head><body><div class="card"><h1>🤖 琴一</h1><p style="color:#888;font-size:13px">配置管理需要验证</p><input type="password" id="pwd" placeholder="密码" onkeydown="if(event.key==='Enter')go()" autofocus><button class="btn" onclick="go()">解锁</button><div class="hint">提示：主人的名字</div></div><script>function go(){{window.location.href='/config?pwd='+encodeURIComponent(document.getElementById('pwd').value)}}</script></body></html>""")
    resp = responses.HTMLResponse(config_html())
    resp.set_cookie(key="config_pwd",value=correct,httponly=True,samesite="strict")
    return resp

def config_html():
    return r"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>🤖 琴一 · 控制台</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:linear-gradient(135deg,#0f0c29,#302b63,#24243e);min-height:100vh;color:#e0e0e0}
#app{max-width:720px;margin:0 auto;padding:24px 20px}
.hdr{text-align:center;padding:20px 0 24px;position:relative}
.hdr h1{font-size:26px;background:linear-gradient(90deg,#00d2ff,#928dab);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.hdr p{color:#666;font-size:13px;margin-top:4px}
#badge{display:inline-block;font-size:11px;padding:3px 12px;border-radius:20px;background:rgba(16,185,129,0.12);color:#10b981;border:1px solid rgba(16,185,129,0.25);margin-top:6px}
.help-btn{position:absolute;top:20px;right:0;width:32px;height:32px;border-radius:50%;background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.1);color:#888;font-size:16px;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:all 0.15s}
.help-btn:hover{background:rgba(0,210,255,0.1);color:#00d2ff;border-color:rgba(0,210,255,0.3)}
.modal-overlay{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.6);z-index:100;justify-content:center;align-items:center}
.modal-overlay.show{display:flex}
.modal{background:#1a1a2e;border-radius:16px;padding:28px 24px;max-width:580px;width:90%;max-height:80vh;overflow-y:auto;border:1px solid rgba(255,255,255,0.1)}
.modal h2{font-size:18px;margin-bottom:16px;color:#e0e0e0}
.modal p,.modal li{font-size:13px;color:#aaa;line-height:1.8}
.modal code{background:rgba(255,255,255,0.06);padding:2px 6px;border-radius:4px;font-size:12px;color:#00d2ff}
.modal .step{background:rgba(255,255,255,0.03);border-radius:8px;padding:12px 14px;margin-bottom:8px}
.modal .step-num{display:inline-block;width:22px;height:22px;border-radius:50%;background:#00d2ff22;color:#00d2ff;text-align:center;line-height:22px;font-size:12px;font-weight:700;margin-right:8px}
.modal-close{width:100%;padding:10px;border:none;border-radius:8px;background:rgba(255,255,255,0.06);color:#aaa;font-size:13px;cursor:pointer;margin-top:12px}
.modal-close:hover{background:rgba(255,255,255,0.1)}
.card{background:rgba(255,255,255,0.05);backdrop-filter:blur(16px);border:1px solid rgba(255,255,255,0.08);border-radius:14px;padding:16px 20px;margin-bottom:10px;cursor:pointer;transition:all 0.15s}
.card:hover{background:rgba(255,255,255,0.08);border-color:rgba(0,210,255,0.2)}
.card:active{transform:scale(0.995)}
.card-row{display:flex;align-items:center;justify-content:space-between;gap:12px}
.card-left{flex:1}
.card-title{font-size:14px;font-weight:600;color:#e0e0e0}
.card-desc{font-size:11px;color:#777;margin-top:2px;line-height:1.4}
.card-right{color:#444;font-size:18px;flex-shrink:0}
.card .tag{font-size:9px;padding:1px 6px;border-radius:3px;margin-left:6px;vertical-align:middle}
.tag-new{background:#00d2ff22;color:#00d2ff;border:1px solid #00d2ff33}
.tag-hot{background:#ff444422;color:#ff6b6b;border:1px solid #ff444433}
.tag-ok{background:#10b98122;color:#10b981;border:1px solid #10b98133}
.mt12{margin-top:12px}
.btn{width:100%;padding:13px;border:none;border-radius:10px;font-size:14px;font-weight:600;cursor:pointer;background:linear-gradient(90deg,#00d2ff,#928dab);color:#fff;margin-top:8px}
.btn:hover{opacity:0.9}
.btn-s{background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.1);color:#aaa;padding:8px 14px;border-radius:8px;font-size:12px;cursor:pointer}
.btn-s:hover{background:rgba(255,255,255,0.1)}
.btn-d{background:rgba(255,68,68,0.15);border:1px solid rgba(255,68,68,0.3);color:#ff6b6b}
.btn-d:hover{background:rgba(255,68,68,0.25)}
.back{display:inline-flex;align-items:center;gap:4px;color:#888;font-size:12px;cursor:pointer;padding:6px 10px;margin-bottom:4px;border-radius:6px;width:fit-content;transition:all 0.15s}
.back:hover{color:#00d2ff;background:rgba(0,210,255,0.06)}
.msg{display:none;padding:10px 16px;border-radius:8px;margin-top:10px;font-size:12px;text-align:center}
.msg-s{background:#00d2ff22;color:#00d2ff;border:1px solid #00d2ff33;display:block}
.msg-e{background:#ff444422;color:#ff4444;border:1px solid #ff444433;display:block}
label{font-size:11px;color:#888;display:block;margin-bottom:3px;margin-top:10px}
input,textarea,select{width:100%;padding:10px 12px;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.1);border-radius:8px;font-size:13px;color:#e0e0e0}
input:focus,textarea:focus,select:focus{outline:none;border-color:#00d2ff}
select option{background:#1a1a2e;color:#e0e0e0}
textarea{min-height:120px;resize:vertical;font-family:inherit;line-height:1.7;font-size:12px}
.gr{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.gr3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px}
@media(max-width:550px){.gr,.gr3{grid-template-columns:1fr}}
.item-card{background:rgba(255,255,255,0.04);border-radius:10px;padding:14px;margin-bottom:10px;border:1px solid rgba(255,255,255,0.06)}
.item-hdr{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}
.item-name{font-size:13px;font-weight:600;color:#ccc}
.item-actions{display:flex;gap:6px}
.add-btn{width:100%;padding:10px;border:1px dashed rgba(255,255,255,0.15);background:transparent;border-radius:8px;color:#888;font-size:13px;cursor:pointer;text-align:center}
.add-btn:hover{background:rgba(255,255,255,0.04);border-color:rgba(0,210,255,0.3);color:#00d2ff}
.switch{position:relative;display:inline-block;width:36px;height:20px}
.switch input{opacity:0;width:0;height:0}
.sl{position:absolute;cursor:pointer;top:0;left:0;right:0;bottom:0;background:rgba(255,255,255,0.15);border-radius:20px;transition:0.2s}
.sl:before{position:absolute;content:"";height:14px;width:14px;left:3px;bottom:3px;background:#fff;border-radius:50%;transition:0.2s}
.switch input:checked+.sl{background:#00d2ff}
.switch input:checked+.sl:before{transform:translateX(16px)}
</style></head>
<body>
<div id="app"></div>
<script>
let CFG={};const UI={};

function show(msg,t){Object.values(UI.msg||{}).forEach(el=>{if(el){el.textContent=msg;el.className='msg msg-'+(t||'s')}})}
async function loadCfg(){const r=await(await fetch('/api/config')).json();CFG=r;return r}
async function saveCfg(data){const r=await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});return r.ok}

// ====== 主页面 ======
function renderMain(data){
    const activeLLM=(data.llm_providers||[]).filter(p=>p.enabled&&p.api_key&&p.api_key!=='••••••').length;
    const activeMCP=(data.mcp_servers||[]).filter(m=>m.enabled).length;
    return `
    <div class="hdr"><h1>🤖 琴一</h1><p>控制台 · 配置中心</p><div id="badge">● 运行中 · 0台设备</div>
<button class="help-btn" onclick="showHelp()" title="使用说明">?</button>
</div>
<div id="helpModal" class="modal-overlay" onclick="if(event.target===this)hideHelp()">
<div class="modal">
<h2>📖 琴一 · 使用说明</h2>
<div class="step"><span class="step-num">1</span><strong style="color:#ccc">烧录固件</strong><br><span style="color:#888;font-size:12px">收到开发板后 USB 连电脑，用 Flash Download Tool 刷入琴一固件。</span></div>
<div class="step"><span class="step-num">2</span><strong style="color:#ccc">配网</strong><br><span style="color:#888;font-size:12px">上电后屏幕显示二维码 → 手机扫码 → 选WiFi输密码 → 联网成功。</span></div>
<div class="step"><span class="step-num">3</span><strong style="color:#ccc">连接服务器</strong><br><span style="color:#888;font-size:12px">自动连接服务器端口，无需激活码或绑定，连上即用。</span></div>
<div class="step"><span class="step-num">4</span><strong style="color:#ccc">开始对话</strong><br><span style="color:#888;font-size:12px">说唤醒词唤醒 → 说话 → 琴一回答。</span></div>
<div style="margin-top:12px;padding:12px;background:rgba(255,255,255,0.03);border-radius:8px;font-size:12px;color:#666">⚠️ 此说明为预写版，板子到手后根据实际情况更新。</div>
<button class="modal-close" onclick="hideHelp()">知道了</button>
</div>
</div>
    <div class="card" onclick="showPage('basic')"><div class="card-row">
    <div class="card-left"><div class="card-title">🧠 基础信息</div><div class="card-desc">机器人名字 · 对你的称呼</div></div>
    <div class="card-right">›</div></div></div>
    <div class="card" onclick="showPage('personality')"><div class="card-row">
    <div class="card-left"><div class="card-title">🧠 人格设定</div><div class="card-desc">性格 · 语气 · 提示词</div></div>
    <div class="card-right">›</div></div></div>
    <div class="card" onclick="showPage('voice')"><div class="card-row">
    <div class="card-left"><div class="card-title">🎤 语音设置</div><div class="card-desc">音色 · 语速 · 音调 · 问候语</div></div>
    <div class="card-right">›</div></div></div>
    <div class="card" onclick="showPage('emotion')"><div class="card-row">
    <div class="card-left"><div class="card-title">😊 表情情绪</div><div class="card-desc">情绪识别开关 · 模式</div></div>
    <div class="card-right">›</div></div></div>
    <div class="card" onclick="showPage('conversation')"><div class="card-row">
    <div class="card-left"><div class="card-title">💬 对话记忆</div><div class="card-desc">记忆 · 闲聊 · 打断 · 超时</div></div>
    <div class="card-right">›</div></div></div>
    <div class="card" onclick="showPage('hardware')"><div class="card-row">
    <div class="card-left"><div class="card-title">💡 硬件控制</div><div class="card-desc">LED灯光 · 屏幕 · 唤醒词 · 按钮</div></div>
    <div class="card-right">›</div></div></div>
    <div class="card" onclick="showPage('api')"><div class="card-row">
    <div class="card-left"><div class="card-title">🔑 API密钥与模型</div>
    <div class="card-desc">${activeLLM}个活跃 · 支持DeepSeek/Claude/OpenAI · 自定URL</div></div>
    <div class="card-right">›</div></div></div>
    <div class="card" onclick="showPage('mcp')"><div class="card-row">
    <div class="card-left"><div class="card-title">🔌 MCP扩展</div>
    <div class="card-desc">${activeMCP}个活跃 · 智能家居/设备控制</div></div>
    <div class="card-right">›</div></div></div>
    <div class="card" onclick="showPage('network')"><div class="card-row">
    <div class="card-left"><div class="card-title">🌐 网络与高级</div><div class="card-desc">服务器地址 · OTA · 调试 · 时区</div></div>
    <div class="card-right">›</div></div></div>
    <div class="card" onclick="window.location.href='/files'"><div class="card-row">
    <div class="card-left"><div class="card-title">📁 记录与文件</div><div class="card-desc">对话记录 · 文件管理 · 下载</div></div>
    <div class="card-right">›</div></div></div>
    <button class="btn" onclick="saveAll()">💾 保存全部配置</button>
    <div id="msg-main" class="msg"></div>`;
}

function escapeHtml(s){
    if(!s)return '';
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#039;');
}
function updateProvider(i,k,v){CFG.llm_providers[i][k]=v}
function addProvider(){
    CFG.llm_providers.push({name:"新供应商",api_url:"https://",api_key:"",models:"model1,model2",selected:"model1",priority:(CFG.llm_providers.length+1),enabled:false,headers:""});
    render('api');
}
function removeProvider(i){
    CFG.llm_providers.splice(i,1);
    render('api');
}

// ====== MCP配置页 ======
function renderMcp(data){
    let html=`<div class="back" onclick="showPage('main')">←</div>
    <h2 style="font-size:18px;margin-bottom:12px">🔌 MCP 扩展配置</h2>
    <p style="font-size:12px;color:#888;margin-bottom:16px">添加多个MCP服务器，控制智能家居、PC等设备。</p>`;
    (data.mcp_servers||[]).forEach((m,i)=>{
        html+=`<div class="item-card">
        <div class="item-hdr">
            <div class="item-name">${m.name||'未命名'}</div>
            <div class="item-actions">
                <label class="switch"><input type="checkbox" ${m.enabled?'checked':''} onchange="updateMcp(${i},'enabled',this.checked)"><span class="sl"></span></label>
                <button class="btn-s btn-d" onclick="removeMcp(${i})">✕</button>
            </div>
        </div>
        <label>名称</label>
        <input value="${escapeHtml(m.name||'')}" placeholder="HomeAssistant" onchange="updateMcp(${i},'name',this.value)">
        <label>连接地址</label>
        <input value="${escapeHtml(m.url||'')}" placeholder="ws://192.168.1.100:8123/mcp" onchange="updateMcp(${i},'url',this.value)">
        <label>Token (可选)</label>
        <input value="${m.token||''}" placeholder="mcp-token-xxx" onchange="updateMcp(${i},'token',this.value)">
        <div style="font-size:10px;color:#555;margin-top:6px">确保你的MCP服务器支持WebSocket连接并已开启。</div>
        </div>`;
    });
    html+=`<button class="add-btn" onclick="addMcp()">+ 添加MCP服务器 <span style="color:#666;font-size:11px">支持HomeAssistant/自建等</span></button>`;
    html+=`<button class="btn" onclick="saveAll()">💾 保存</button><div id="msg-mcp" class="msg"></div>`;
    return html;
}
function updateMcp(i,k,v){CFG.mcp_servers[i][k]=v}
function addMcp(){
    CFG.mcp_servers.push({name:"新MCP服务器",url:"ws://",token:"",enabled:false});
    render('mcp');
}
function removeMcp(i){
    CFG.mcp_servers.splice(i,1);
    render('mcp');
}

// ====== 通用配置渲染页 ======
function renderField(id,label,type,opts){
    const v=CFG[id]||'';
    if(type==='select'){
        const ops=(opts||[]).map(o=>`<option ${v==o.value?'selected':''} value="${o.value}">${o.label}</option>`).join('');
        return `<label>${label}</label><select id="${id}" onchange="CFG['${id}']=this.value">${ops}</select>`;
    }
    if(type==='range')return `<label>${label}</label><input id="${id}" type="range" class="slider" value="${v}" oninput="CFG['${id}']=this.value"><span style="font-size:11px;color:#666">${v}</span>`;
    if(type==='color')return `<label>${label}</label><input id="${id}" type="color" class="color-picker" value="${v||'#00d2ff'}" onchange="CFG['${id}']=this.value">`;
    if(type==='textarea')return `<label>${label}</label><textarea id="${id}" onchange="CFG['${id}']=this.value">${v}</textarea>`;
    return `<label>${label}</label><input id="${id}" value="${v}" onchange="CFG['${id}']=this.value">`;
}

const PAGES={
main:(d)=>renderMain(d),
basic:(d)=>`
<div class="back" onclick="showPage('main')">←</div>
<div class="card" style="cursor:default"><h2 style="font-size:14px;margin-bottom:14px">🧠 基础信息</h2>
${renderField('bot_name','机器人名字')}
${renderField('master_name','对你的称呼')}
${renderField('language','界面语言','select',[{value:'zh-CN',label:'中文'},{value:'en',label:'English'}])}
</div><button class="btn" onclick="saveAll()">💾 保存</button><div id="msg-basic" class="msg"></div>`,
personality:(d)=>`
<div class="back" onclick="showPage('main')">←</div>
<div class="card" style="cursor:default"><h2 style="font-size:14px;margin-bottom:14px">🧠 人格设定</h2>
<div class="gr">
<div>${renderField('personality_tone','语气风格','select',[{value:'温柔',label:'温柔'},{value:'活泼',label:'活泼'},{value:'知性',label:'知性'},{value:'幽默',label:'幽默'},{value:'冷酷',label:'冷酷'}])}</div>
<div>${renderField('conversation_style','回复长度','select',[{value:'简洁',label:'简洁'},{value:'详细',label:'详细'},{value:'话痨',label:'话痨'},{value:'只回答问题',label:'只回答'}])}</div>
</div>
${renderField('formality','亲密程度','select',[{value:'朋友',label:'朋友'},{value:'礼貌',label:'礼貌'},{value:'亲密',label:'亲密'},{value:'官方',label:'官方'}])}
${renderField('sys_prompt','完整系统提示词','textarea')}
</div><button class="btn" onclick="saveAll()">💾 保存</button><div id="msg-personality" class="msg"></div>`,
voice:(d)=>`
<div class="back" onclick="showPage('main')">←</div>
<div class="card" style="cursor:default"><h2 style="font-size:14px;margin-bottom:14px">🎤 语音设置</h2>
<div class="gr">
<div>${renderField('tts_voice','TTS 音色','select',[{value:'zh-CN-XiaoxiaoNeural',label:'晓晓·温柔'},{value:'zh-CN-XiaoyiNeural',label:'晓伊·活泼'},{value:'zh-CN-XiaohanNeural',label:'晓涵·温婉'},{value:'zh-CN-XiaomoNeural',label:'晓墨·知性'},{value:'zh-CN-XiaoxuanNeural',label:'晓萱·可爱'},{value:'zh-CN-liaoning-XiaobeiNeural',label:'晓北·东北'},{value:'zh-CN-shaanxi-XiaoniNeural',label:'晓妮·陕西'},{value:'zh-CN-YunxiNeural',label:'云希·阳光'},{value:'zh-CN-YunjianNeural',label:'云健·成熟'},{value:'zh-CN-YunyangNeural',label:'云扬·新闻'},{value:'zh-CN-YunjieNeural',label:'云杰·粤语'},{value:'zh-TW-HsiaoChenNeural',label:'晓臻·台湾'},{value:'zh-HK-WanLungNeural',label:'云龙·香港'},{value:'en-US-JennyNeural',label:'Jenny·美式英语'},{value:'ja-JP-NanamiNeural',label:'Nanami·日语'}])}</div>
<div>${renderField('tts_speed','语速','select',[{value:'0.5',label:'极慢'},{value:'0.8',label:'慢速'},{value:'1.0',label:'正常'},{value:'1.2',label:'稍快'},{value:'1.5',label:'快速'},{value:'2.0',label:'极快'}])}</div>
</div>
<div class="gr">
<div>${renderField('tts_pitch','音调','select',[{value:'-10',label:'低沉'},{value:'-5',label:'偏低'},{value:'0',label:'正常'},{value:'5',label:'偏高'},{value:'10',label:'尖锐'}])}</div>
<div>${renderField('tts_volume','音量','select',[{value:'0.5',label:'50%'},{value:'0.7',label:'70%'},{value:'1.0',label:'100%'},{value:'1.5',label:'150%'}])}</div>
</div>
${renderField('welcome_msg','开机问候语')}
${renderField('goodbye_msg','告别语')}
</div><button class="btn" onclick="saveAll()">💾 保存</button><div id="msg-voice" class="msg"></div>`,
emotion:(d)=>`
<div class="back" onclick="showPage('main')">←</div>
<div class="card" style="cursor:default"><h2 style="font-size:14px;margin-bottom:14px">😊 表情与情绪</h2>
${renderField('emotion_enabled','表情开关','select',[{value:'true',label:'开启'},{value:'false',label:'关闭'}])}
${renderField('emotion_style','表情模式','select',[{value:'auto',label:'自动识别'},{value:'fixed',label:'固定表情'},{value:'random',label:'随机变换'}])}
</div>
<div class="card" style="cursor:default">
<h2 style="font-size:14px;margin-bottom:10px">🎯 固定表情选择</h2>
<p style="font-size:11px;color:#888;margin-bottom:8px">点击下方表情可设为固定显示：</p>
<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(60px,1fr));gap:8px" id="fixedEmojiGrid"></div>
<div style="margin-top:10px;padding:10px;background:rgba(255,255,255,0.03);border-radius:8px;text-align:center" id="fixedEmojiDisplay">加载中...</div>
</div>
<div class="card" style="cursor:default">
<h2 style="font-size:14px;margin-bottom:10px">✏️ 自定义表情符号</h2>
<p style="font-size:11px;color:#888;margin-bottom:8px">点击表情可替换：</p>
<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(60px,1fr));gap:8px" id="customEmojiGrid"></div>
</div>
<button class="btn" onclick="saveAll()">💾 保存</button><div id="msg-emotion" class="msg"></div><script>
(function(){if(!CFG.custom_emojis)CFG.custom_emojis={};
var EM={"happy":"😊","sad":"😢","angry":"😠","surprised":"😮","sleepy":"😴","thinking":"🤔","neutral":"😐","laughing":"😂","love":"🥰","confused":"😕","singing":"🎵"};
var EN={"happy":"开心","sad":"难过","angry":"生气","surprised":"惊讶","sleepy":"困了","thinking":"思考","neutral":"平静","laughing":"大笑","love":"爱你","confused":"疑惑","singing":"唱歌"};
var EP=["😊","😂","🥰","😢","😠","😮","😴","🤔","😐","😕","🎵","😎","🤩","🥳","😏","😭","😱","🤗","🤔","😈","👻","💀","👽","👍","❤️","🔥","✨","🎉","💯","💪","🫡","🤝","🐱","🐶","🐰","🦊","🐸","🐼","🌙","⭐","🌸","🌈","🍀","🎶","✅"];

function re(){var h1='',h2='',fe=CFG.fixed_emotion||'';
Object.keys(EM).forEach(function(k){var e=CFG.custom_emojis[k]||EM[k];
var a=fe===k?'border-color:#00d2ff;background:rgba(0,210,255,0.12)':'';
h1+='<div onclick="setFE(''+k+'')" style="text-align:center;padding:10px 0;background:rgba(255,255,255,0.03);border-radius:8px;cursor:pointer;border:1px solid '+(a?'#00d2ff':'rgba(255,255,255,0.08)')+'" title="固定: '+EN[k]+'"><div style="font-size:28px">'+e+'</div><div style="font-size:10px;color:#888">'+EN[k]+'</div></div>';
h2+='<div onclick="sp(''+k+'',''+e+'')" style="text-align:center;padding:10px 0;background:rgba(255,255,255,0.03);border-radius:8px;cursor:pointer;border:1px solid rgba(255,255,255,0.08)"><div style="font-size:28px" id="ce_'+k+'">'+e+'</div><div style="font-size:10px;color:#888">'+EN[k]+'</div></div>'});
document.getElementById('fixedEmojiGrid').innerHTML=h1;
document.getElementById('customEmojiGrid').innerHTML=h2;
document.getElementById('fixedEmojiDisplay').innerHTML=fe?'当前固定: <span style="font-size:24px">'+(CFG.custom_emojis[fe]||EM[fe])+'</span> '+EN[fe]:'尚未设置固定表情';}

function setFE(k){CFG.fixed_emotion=CFG.fixed_emotion===k?'':k;re();}

function sp(k,c){var d=document.createElement('div');
d.style.cssText='position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.6);z-index:200;display:flex;justify-content:center;align-items:center';
d.innerHTML='<div style="background:#1a1a2e;border-radius:16px;padding:20px;max-width:360px;width:90%;border:1px solid rgba(255,255,255,0.1)"><h3 style="font-size:14px;margin-bottom:12px;color:#e0e0e0">选择 '+EN[k]+'</h3><div style="display:grid;grid-template-columns:repeat(7,1fr);gap:6px">'+EP.map(function(e){return '<div onclick="pk(''+k+'',''+e+'',this)" style="text-align:center;padding:8px 0;border-radius:8px;cursor:pointer;font-size:26px;background:'+(e===c?'rgba(0,210,255,0.15)':'rgba(255,255,255,0.04)')+';border:1px solid '+(e===c?'#00d2ff':'transparent')+'">'+e+'</div>'}).join('')+'</div><button onclick="this.parentElement.parentElement.remove()" style="width:100%;padding:10px;margin-top:12px;border:none;border-radius:8px;background:rgba(255,255,255,0.06);color:#aaa;cursor:pointer">取消</button></div>';
document.body.appendChild(d);}

function pk(k,e,el){CFG.custom_emojis[k]=e;document.getElementById('ce_'+k).textContent=e;if(CFG.fixed_emotion===k)re();el.parentElement.parentElement.parentElement.remove();}
re();})();
' + '</script' + '>' + '`,conversation:(d)=>`
<div class="back" onclick="showPage('main')">←</div>
<div class="card" style="cursor:default"><h2 style="font-size:14px;margin-bottom:14px">💬 对话与记忆</h2>
<div class="gr">
<div>${renderField('keep_history','记忆开关','select',[{value:'true',label:'开启'},{value:'false',label:'关闭'}])}</div>
<div>${renderField('max_history','记忆轮数','select',[{value:'5',label:'5轮'},{value:'10',label:'10轮'},{value:'20',label:'20轮'},{value:'50',label:'50轮'},{value:'100',label:'100轮'}])}</div>
</div>
<div class="gr">
<div>${renderField('auto_greet','自动问候','select',[{value:'true',label:'开启'},{value:'false',label:'关闭'}])}</div>
<div>${renderField('enable_smalltalk','主动闲聊','select',[{value:'true',label:'开启'},{value:'false',label:'关闭'}])}</div>
</div>
<div class="gr">
<div>${renderField('smalltalk_interval','空闲多久主动说话','select',[{value:'60',label:'1分钟'},{value:'300',label:'5分钟'},{value:'600',label:'10分钟'},{value:'1800',label:'30分钟'}])}</div>
<div>${renderField('enable_interrupt','允许打断','select',[{value:'true',label:'开启'},{value:'false',label:'关闭'}])}</div>
</div>
${renderField('voice_timeout','不说话多久停止听','select',[{value:'3',label:'3秒'},{value:'5',label:'5秒'},{value:'10',label:'10秒'},{value:'15',label:'15秒'}])}
</div><button class="btn" onclick="saveAll()">💾 保存</button><div id="msg-conversation" class="msg"></div>`,
hardware:(d)=>`
<div class="back" onclick="showPage('main')">←</div>
<div class="card" style="cursor:default"><h2 style="font-size:14px;margin-bottom:14px">💡 灯光</h2>
<div class="gr">
<div>${renderField('led_enabled','灯光开关','select',[{value:'true',label:'开启'},{value:'false',label:'关闭'}])}</div>
<div>${renderField('led_breathing','呼吸灯','select',[{value:'true',label:'开启'},{value:'false',label:'关闭'}])}</div>
</div>
${renderField('led_brightness','亮度','range')}
${renderField('led_color','主色调','color')}
</div>
<div class="card" style="cursor:default"><h2 style="font-size:14px;margin-bottom:14px">📺 屏幕</h2>
<div class="gr">
<div>${renderField('screen_brightness','亮度','select',[{value:'60',label:'暗'},{value:'120',label:'适中'},{value:'180',label:'亮'},{value:'255',label:'最亮'}])}</div>
<div>${renderField('screen_saver','待机显示','select',[{value:'clock',label:'时钟'},{value:'animation',label:'动画'},{value:'off',label:'息屏'}])}</div>
</div>
<div class="gr3">
<div>${renderField('show_time','显示时间','select',[{value:'true',label:'显示'},{value:'false',label:'隐藏'}])}</div>
<div>${renderField('show_battery','显示电量','select',[{value:'true',label:'显示'},{value:'false',label:'隐藏'}])}</div>
<div>${renderField('screen_timeout','待机等待','select',[{value:'10',label:'10秒'},{value:'30',label:'30秒'},{value:'60',label:'60秒'},{value:'0',label:'永不'}])}</div>
</div></div>
<div class="card" style="cursor:default"><h2 style="font-size:14px;margin-bottom:14px">🗣️ 唤醒词与按钮</h2>
${renderField('wake_word','唤醒词')}
<div class="gr">
<div>${renderField('wake_sensitivity','唤醒灵敏度','select',[{value:'high',label:'高'},{value:'medium',label:'中'},{value:'low',label:'低'}])}</div>
<div>${renderField('listening_mode','对话模式','select',[{value:'auto',label:'自动模式'},{value:'manual',label:'手动模式'}])}</div>
</div>
${renderField('double_tap_action','双击按钮动作','select',[{value:'camera',label:'打开摄像头'},{value:'mode',label:'切换模式'},{value:'mute',label:'静音'},{value:'none',label:'无'}])}
</div><button class="btn" onclick="saveAll()">💾 保存</button><div id="msg-hardware" class="msg"></div>`,
network:(d)=>`
<div class="back" onclick="showPage('main')">←</div>
<div class="card" style="cursor:default"><h2 style="font-size:14px;margin-bottom:14px">🌐 网络与高级设置</h2>
${renderField('server_url','WebSocket服务器地址')}
${renderField('enable_ota','OTA自动升级','select',[{value:'true',label:'开启'},{value:'false',label:'关闭'}])}
${renderField('ota_url','OTA地址(可选)')}
${renderField('enable_debug','调试日志','select',[{value:'false',label:'关闭'},{value:'true',label:'开启'}])}
${renderField('timezone','时区','select',[{value:'Asia/Shanghai',label:'中国标准时间'},{value:'Asia/Tokyo',label:'日本'},{value:'America/New_York',label:'美东'},{value:'Europe/London',label:'伦敦'}])}
</div><button class="btn" onclick="saveAll()">💾 保存</button><div id="msg-network" class="msg"></div>`,
api:(d)=>renderApi(d),
mcp:(d)=>renderMcp(d),
};

function renderApi(data){
    let html=`<div class="back" onclick="showPage('main')">←</div>
    <h2 style="font-size:18px;margin-bottom:12px">🔑 API 密钥与模型配置</h2>
    <p style="font-size:12px;color:#888;margin-bottom:16px">可添加多个LLM供应商，按优先级自动切换。一个不行自动换下一个。</p>`;
    (data.llm_providers||[]).forEach((p,i)=>{
        html+=`<div class="item-card">
        <div class="item-hdr">
            <div class="item-name">${p.name||'未命名'}</div>
            <div class="item-actions">
                <label class="switch"><input type="checkbox" ${p.enabled?'checked':''} onchange="updateProvider(${i},'enabled',this.checked)"><span class="sl"></span></label>
                <button class="btn-s btn-d" onclick="removeProvider(${i})">✕</button>
            </div>
        </div>
        <label>显示名称</label>
        <input value="${escapeHtml(p.name||'')}" onchange="updateProvider(${i},'name',this.value)">
        <label>API 调用地址</label>
        <input value="${escapeHtml(p.api_url||'')}" placeholder="https://api.deepseek.com" onchange="updateProvider(${i},'api_url',this.value)">
        <label>API Key</label>
        <input value="${p.api_key||''}" ${p.api_key==='••••••'?'placeholder=已保存':''} onchange="updateProvider(${i},'api_key',this.value)" ${p.api_key!=='••••••'?'':'style=border-color:rgba(0,210,255,0.3)'}>
        <label>可用模型（逗号分隔）</label>
        <input value="${escapeHtml(p.models||'')}" placeholder="deepseek-chat,deepseek-reasoner" onchange="updateProvider(${i},'models',this.value)">
        <div class="gr">
        <div><label>当前选用</label><input value="${escapeHtml(p.selected||'')}" placeholder="deepseek-chat" onchange="updateProvider(${i},'selected',this.value)"></div>
        <div><label>优先级(1最高)</label><input type="number" value="${p.priority||99}" min="1" max="99" onchange="updateProvider(${i},'priority',parseInt(this.value)||99)"></div>
        </div>
        <label>额外请求头(JSON,Claude需要)</label>
        <input value="${escapeHtml(p.headers||'')}" placeholder='{"anthropic-version":"2023-06-01"}' onchange="updateProvider(${i},'headers',this.value)">
        </div>`;
    });
    html+=`<button class="add-btn" onclick="addProvider()">+ 添加供应商 (DeepSeek/Claude/OpenAI/自定义)</button>`;
    // 火山引擎 ASR 区块（跟 LLM 供应商卡片同款风格）
    const vAppid = data.volc_appid||'';
    const vAt = data.volc_at||'';
    html+=`<div class="item-card" style="margin-top:16px">
    <div class="item-hdr">
        <div class="item-name">🎙️ 火山引擎语音识别 (ASR)</div>
        <div class="item-actions">
            <span class="tag tag-ok" id="asr-badge">● 待配置</span>
        </div>
    </div>
    <label>App ID</label>
    <input value="${escapeHtml(vAppid)}" placeholder="你的火山引擎AppID" onchange="CFG.volc_appid=this.value;updateAsrBadge()">
    <label>Access Token</label>
    <input value="${vAt||''}" placeholder="你的火山引擎AccessToken" onchange="CFG.volc_at=this.value;updateAsrBadge()" ${vAt?'style=border-color:rgba(0,210,255,0.3)':''}>
    <div style="font-size:10px;color:#555;margin-top:6px">用于将你说的话转成文字。前往 <a href="https://console.volcengine.com/speech/app" target="_blank" style="color:#00d2ff">火山引擎控制台</a> 获取。</div>
    </div>`;
    html+=`<button class="btn" onclick="saveAll()">💾 保存</button><div id="msg-api" class="msg"></div>`;
    return html;
}
function updateAsrBadge(){
    const b=document.getElementById('asr-badge');
    if(b)b.textContent=CFG.volc_appid&&CFG.volc_at?'● 已配置':'● 待配置';
}

function render(page,data){
    data=data||CFG;
    const fn=PAGES[page]||PAGES.main;
    document.getElementById('app').innerHTML=fn(data);
    UI.msg={};document.querySelectorAll('[id^=msg-]').forEach(el=>{UI.msg[el.id]=el});
}

function showPage(page){
    render(page,CFG);
    window.scrollTo({top:0});
}
function showHelp(){document.getElementById('helpModal').classList.add('show')}
function hideHelp(){document.getElementById('helpModal').classList.remove('show')}
document.addEventListener('keydown',function(e){if(e.key==='Escape'){const cur=document.querySelector('.back');if(cur){cur.click()}}});

async function saveAll(){
    const data={};
    Object.keys(CFG).forEach(k=>{data[k]=CFG[k]});
    const ok=await saveCfg(data);
    show(ok?'✅ 全部配置已保存':'❌ 保存失败',ok?'s':'e');
    setTimeout(()=>{document.querySelectorAll('.msg').forEach(el=>el.style.display='none')},3000);
}

(async function(){
    await loadCfg();
    render('main');
    setInterval(async()=>{
        try{
            const s=await(await fetch('/api/stats')).json();
            const b=document.getElementById('badge');
            if(b)b.textContent='● 运行中 v'+s.version+' · '+s.online_devices+'台设备';
        }catch(e){}
    },5000);
})();
</script></body></html>"""

@app.on_event("startup")
async def su():
    # 如果用户之前在代码顶部填过老版 ds_key，兼容迁移：
    # 从 DEFAULT_PROVIDERS 中的 DeepSeek 读取 api_key 作为后备
    asyncio.create_task(wss())
async def wss():
    async def h(w):await hdl(w)
    async with websockets.serve(h,"0.0.0.0",8001):
        log.info("✅ 琴一 v5.3 | WS:8001 | HTTP:8000")
        await asyncio.Future()
if __name__=="__main__":
    start_time=time.time()
    uvicorn.run(app,host="0.0.0.0",port=8000)
