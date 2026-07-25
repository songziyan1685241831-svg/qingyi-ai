import asyncio,json,uuid,logging,websockets
from fastapi import FastAPI, responses
import uvicorn,httpx,edge_tts

# ====== 配置：在这里填入你的密钥 ======
VOLC_APPID = "你的火山引擎AppID"
VOLC_AT = "你的火山引擎AccessToken"
DS_KEY = "你的DeepSeek API Key"

logging.basicConfig(level=logging.INFO);log=logging.getLogger("Bot")

# 运行时配置（网页可改）
CFG={
    "sys_prompt":"你是我的AI助手，你叫琴一，你说话温柔可爱，回答简洁明了，不超过50字。",
    "tts_voice":"zh-CN-XiaoxiaoNeural",
    "tts_speed":"1.0",
    "bot_name":"琴一",
}

class Session:
    def __init__(s,w):s.ws=w;s.id=uuid.uuid4().hex[:8];s.st="idle";s.q=asyncio.Queue()

# ====== 火山引擎 ASR（语音→文字）======
async def asr(s):
    h={"Authorization":f"Bearer; {VOLC_AT}"}
    async with websockets.connect("wss://openspeech.bytedance.com/api/v2/asr",extra_headers=h) as a:
        await a.send(json.dumps({"app":{"appid":VOLC_APPID,"cluster":"volcengine_input_common"},"user":{"uid":s.id},"audio":{"format":"opus","rate":16000}}))
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
                        tx="".join(r.get("text","") for r in d.get("result",[]) if r.get("text"))
                        if tx:await s.ws.send(json.dumps({"type":"stt","text":tx}));asyncio.create_task(llm(s,tx))
                        break
        finally:t.cancel()

# ====== DeepSeek LLM（大脑）======
async def llm(s,t):
    await s.ws.send(json.dumps({"type":"llm","emotion":"thinking","text":"🤔"}))
    async with httpx.AsyncClient(timeout=30) as c:
        r=await c.post("https://api.deepseek.com/chat/completions",json={"model":"deepseek-chat","messages":[{"role":"system","content":CFG["sys_prompt"]},{"role":"user","content":t}],"stream":True},headers={"Authorization":f"Bearer {DS_KEY}"})
        f=""
        async for l in r.aiter_lines():
            if l.startswith("data: ") and l[6:]!="[DONE]":
                try:f+=json.loads(l[6:])["choices"][0]["delta"].get("content","")
                except:pass
        if f:await s.ws.send(json.dumps({"type":"llm","emotion":"happy","text":f}));asyncio.create_task(tts(s,f))

# ====== Edge TTS（文字→语音）======
async def tts(s,t):
    await s.ws.send(json.dumps({"type":"tts","state":"start"}))
    try:
        com=edge_tts.Communicate(t,CFG["tts_voice"],rate=CFG["tts_speed"])
        async for c in com.stream():
            if c["type"]=="audio":await s.ws.send(c["data"])
    except:
        com=edge_tts.Communicate(t,"zh-CN-XiaoxiaoNeural")
        async for c in com.stream():
            if c["type"]=="audio":await s.ws.send(c["data"])
    await s.ws.send(json.dumps({"type":"tts","state":"stop"}))

# ====== WebSocket 主处理（ESP32连这里）======
async def hdl(ws):
    s=Session(ws)
    try:
        async for m in ws:
            if isinstance(m,str):
                d=json.loads(m);tp=d.get("type")
                if tp=="hello":
                    await ws.send(json.dumps({"type":"hello","transport":"websocket","session_id":s.id,"audio_params":{"format":"opus","sample_rate":24000}}))
                    log.info(f"设备上线: {s.id}")
                elif tp=="listen":
                    if d.get("state")=="start":s.st="listen";asyncio.create_task(asr(s))
                    else:s.st="idle";await s.q.put(None)
                elif tp=="abort":s.st="idle";await s.q.put(None)
            elif s.st=="listen":await s.q.put(m)
    except:pass
    finally:await s.q.put(None)

app=FastAPI()

@app.get("/")
async def root():return{"status":"ok","name":"AI-Bot","server":"your_server_ip:8001","config_url":"/config"}

@app.get("/api/config")
async def gc():return CFG

@app.post("/api/config")
async def sc(d:dict):
    for k in d:
        if k in CFG:CFG[k]=d[k]
    return{"status":"ok"}

# ====== 网页配置页面 ======
@app.get("/config")
async def cfg():
    return responses.HTMLResponse("""
<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>🤖 琴一配置</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,sans-serif;background:linear-gradient(135deg,#667eea,#764ba2);min-height:100vh;padding:20px}
.container{max-width:640px;margin:0 auto}
.header{text-align:center;padding:30px 0;color:#fff}
.header h1{font-size:28px;margin-bottom:8px}
.header p{opacity:0.9;font-size:14px}
.card{background:rgba(255,255,255,0.95);border-radius:16px;padding:24px;margin-bottom:16px}
.card h2{font-size:16px;color:#333;margin-bottom:16px;display:flex;align-items:center;gap:8px}
label{display:block;font-size:13px;color:#666;margin-bottom:4px;margin-top:12px}
input,textarea,select{width:100%;padding:10px 14px;border:2px solid #e5e7eb;border-radius:10px;font-size:14px}
input:focus,textarea:focus,select:focus{outline:none;border-color:#667eea}
textarea{min-height:120px;resize:vertical}
select{appearance:none;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%23666' d='M6 8L1 3h10z'/%3E%3C/svg%3E");background-repeat:no-repeat;background-position:right 12px center}
.btn{width:100%;padding:12px;border:none;border-radius:10px;font-size:15px;font-weight:600;cursor:pointer;background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;margin-top:20px}
.btn:active{transform:scale(0.98)}
.msg{display:none;padding:10px;border-radius:10px;margin-top:12px;font-size:13px;text-align:center}
.msg-s{background:#d1fae5;color:#065f46;display:block}
.msg-e{background:#fee2e2;color:#991b1b;display:block}
</style></head>
<body>
<div class="container">
<div class="header"><h1>🤖 琴一</h1><p>你的AI陪伴机器人 · 配置中心</p></div>
<div class="card">
<h2>🧠 角色设定</h2>
<label>机器人名字</label>
<input id="bot_name" placeholder="如：琴一">
<label>系统提示词（决定性格和说话风格）</label>
<textarea id="sys_prompt" placeholder="例如：你是我的AI助手，你叫琴一..."></textarea>
</div>
<div class="card">
<h2>🎤 语音设置</h2>
<label>TTS音色</label>
<select id="tts_voice">
<optgroup label="中文女声">
<option value="zh-CN-XiaoxiaoNeural">晓晓（温柔女声）</option>
<option value="zh-CN-XiaoyiNeural">晓伊（活泼女声）</option>
<option value="zh-CN-liaoning-XiaobeiNeural">晓北（东北女声）</option>
<option value="zh-CN-shaanxi-XiaoniNeural">晓妮（陕西女声）</option>
</optgroup>
<optgroup label="中文男声">
<option value="zh-CN-YunxiNeural">云希（阳光男声）</option>
<option value="zh-CN-YunjianNeural">云健（成熟男声）</option>
<option value="zh-CN-YunyangNeural">云扬（新闻男声）</option>
</optgroup>
<optgroup label="方言/特色">
<option value="zh-CN-YunjieNeural">云杰（广东话）</option>
<option value="zh-TW-HsiaoChenNeural">晓臻（台湾女声）</option>
</optgroup>
</select>
<label>语速</label>
<select id="tts_speed">
<option value="0.8">慢速</option>
<option value="1.0" selected>正常</option>
<option value="1.2">稍快</option>
<option value="1.5">快速</option>
</select>
</div>
<div class="card">
<h2>📊 服务状态</h2>
<div style="display:flex;justify-content:space-between"><div><div style="font-size:14px">运行中</div><div style="font-size:12px;color:#999">8000 / 8001</div></div><div><span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#10b981;margin-right:6px"></span>在线</div></div>
<div style="margin-top:12px;padding:12px;background:#f3f4f6;border-radius:8px;font-size:12px;color:#666">
ESP32地址: <code style="background:#e5e7eb;padding:2px 6px;border-radius:4px">ws://你的服务器IP:8001</code><br>
配置页面: <code style="background:#e5e7eb;padding:2px 6px;border-radius:4px">http://你的服务器IP:8000/config</code>
</div>
</div>
<button class="btn" onclick="save()">💾 保存配置</button>
<div id="msg" class="msg"></div>
</div>
<script>
async function load(){
    const r=await(await fetch('/api/config')).json();
    document.getElementById('sys_prompt').value=r.sys_prompt||'';
    document.getElementById('tts_voice').value=r.tts_voice||'zh-CN-XiaoxiaoNeural';
    document.getElementById('tts_speed').value=r.tts_speed||'1.0';
    document.getElementById('bot_name').value=r.bot_name||'琴一';
}
async function save(){
    const data={sys_prompt:document.getElementById('sys_prompt').value,tts_voice:document.getElementById('tts_voice').value,tts_speed:document.getElementById('tts_speed').value,bot_name:document.getElementById('bot_name').value};
    const r=await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
    const el=document.getElementById('msg');
    if(r.ok){el.textContent='✅ 已保存！下次对话生效';el.className='msg msg-s'}
    else{el.textContent='❌ 保存失败';el.className='msg msg-e'}
    setTimeout(()=>el.style.display='none',3000);
}
load();
</script></body></html>""")

@app.on_event("startup")
async def su():asyncio.create_task(wss())
async def wss():
    async def h(w):await hdl(w)
    async with websockets.serve(h,"0.0.0.0",8001):
        log.info("WS:8001")
        await asyncio.Future()
if __name__=="__main__":
    uvicorn.run(app,host="0.0.0.0",port=8000)
