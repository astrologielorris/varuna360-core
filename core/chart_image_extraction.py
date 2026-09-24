"""Shared Add Chart screenshot extraction; no Pro AI feature imports."""
from __future__ import annotations
import base64
import json

VISION_PROVIDERS = (
    {"name":"GPT-5.6 Luna","key":"OPENAI_API_KEY","model":"gpt-5.6-luna","url":"https://api.openai.com/v1/chat/completions","kind":"openai","reasoning":True},
    {"name":"GPT-5.6 Terra","key":"OPENAI_API_KEY","model":"gpt-5.6-terra","url":"https://api.openai.com/v1/chat/completions","kind":"openai","reasoning":True},
    {"name":"GPT-5.6 Sol","key":"OPENAI_API_KEY","model":"gpt-5.6-sol","url":"https://api.openai.com/v1/chat/completions","kind":"openai","reasoning":True},
    {"name":"Kimi K3","key":"KIMI_API_KEY","model":"kimi-k3","url":"https://api.moonshot.ai/v1/chat/completions","kind":"openai","reasoning":False},
    {"name":"Mistral Large","key":"MISTRAL_API_KEY","model":"mistral-small-latest","url":"https://api.mistral.ai/v1/chat/completions","kind":"openai","reasoning":False},
    {"name":"Anthropic API","key":"ANTHROPIC_API_KEY","model":"claude-haiku-4-5","url":None,"kind":"anthropic","reasoning":False},
    # Subscription CLIs: no API key, the installed Claude Code / Codex login pays.
    {"name":"Claude Code Sonnet 5","key":None,"model":"claude-sonnet-5","url":None,"kind":"claude_cli","reasoning":False},
    {"name":"Claude Code Opus 5","key":None,"model":"claude-opus-5","url":None,"kind":"claude_cli","reasoning":False},
    {"name":"Codex GPT-5.6 Luna","key":None,"model":"gpt-5.6-luna","url":None,"kind":"codex_cli","reasoning":True},
    {"name":"Codex GPT-5.6 Terra","key":None,"model":"gpt-5.6-terra","url":None,"kind":"codex_cli","reasoning":True},
    {"name":"Codex GPT-5.6 Sol","key":None,"model":"gpt-5.6-sol","url":None,"kind":"codex_cli","reasoning":True},
)
CLI_TIMEOUT = 240
_IMAGE_EXT = {"image/png":".png","image/jpeg":".jpg","image/jpg":".jpg","image/webp":".webp","image/gif":".gif"}
DEFAULT_VISION_PROVIDER = "GPT-5.6 Luna"
LEGACY_VISION_NAMES = {"GPT-5.4 Mini":"GPT-5.6 Luna","Kimi K2.6":"Kimi K3"}
PROMPT = '''Extract EVERY astrological chart in this image. Reply with ONLY JSON:
{"charts":[{"name":"...","date":"YYYY-MM-DD","time":"HH:MM","place":"City, Country","tz_hint":"...","kind":"birth|transit|event|return|unknown"}],"confidence":0.0,"ambiguous":false,"notes":"..."}
Return charts in visual order; a dual wheel is two charts. Each chart requires a date. Never invent optional data. Dates are ISO and times are 24-hour.'''

def vision_provider_configs():
    return [dict(x) for x in VISION_PROVIDERS]

def _fail(error, unavailable=False, provider="", model=""):
    return {"ok":False,"error":error,"provider_unavailable":unavailable,"charts":[],"confidence":0.0,"ambiguous":False,"notes":"","provider":provider,"model":model}

def _parse(text):
    text = str(text or "").strip()
    if text.startswith("```"):
        text = text.split("\n",1)[-1].rsplit("```",1)[0].strip()
    try:
        out = json.loads(text)
    except (TypeError, ValueError):
        start, end = text.find("{"), text.rfind("}")
        try:
            out = json.loads(text[start:end+1])
        except (TypeError, ValueError):
            return None
    return out if isinstance(out, dict) else None

def _normalize(payload):
    out=[]
    for item in payload.get("charts",[]) if isinstance(payload,dict) else []:
        if not isinstance(item,dict) or not str(item.get("date") or "").strip():
            continue
        row={"date":str(item["date"]).strip()}
        for key in ("name","time","place","tz_hint","kind"):
            if str(item.get(key) or "").strip():
                row[key]=str(item[key]).strip()
        out.append(row)
    return out

def _looks_logged_out(text):
    low=str(text or "").lower()
    return any(w in low for w in ("login","log in","logged out","not logged","authenticat","/login","api key"))

def _claude_cli_reply(path, model, data, media_type, workdir):
    from core.session_cli import run_cli
    message={"type":"user","message":{"role":"user","content":[{"type":"image","source":{"type":"base64","media_type":media_type,"data":base64.b64encode(data).decode("ascii")}},{"type":"text","text":"Extract every chart."}]}}
    proc=run_cli(path,["-p","--input-format","stream-json","--output-format","stream-json","--verbose","--model",model,"--tools","","--setting-sources","","--strict-mcp-config","--no-session-persistence","--system-prompt",PROMPT],CLI_TIMEOUT,input_text=json.dumps(message)+"\n",cwd=workdir)
    result=None
    for line in (proc.stdout or "").splitlines():
        try:
            event=json.loads(line)
        except ValueError:
            continue
        if isinstance(event,dict) and event.get("type")=="result":
            result=event
    if result is None or result.get("is_error") or proc.returncode!=0:
        detail=str((result or {}).get("result") or proc.stderr or proc.stdout or "").strip()[-300:]
        return None,detail
    return str(result.get("result") or ""),""

def _codex_cli_reply(path, model, data, media_type, workdir, effort):
    import os
    from core.session_cli import run_cli
    image=os.path.join(workdir,"chart"+_IMAGE_EXT.get(str(media_type).lower(),".png"))
    out=os.path.join(workdir,"reply.txt")
    with open(image,"wb") as fh:
        fh.write(data)
    args=["exec","--skip-git-repo-check","--ephemeral","-s","read-only","-m",model]
    if effort:
        args+=["-c",f'model_reasoning_effort="{effort}"']
    args+=["-i",image,"--output-last-message",out,PROMPT+"\n\nExtract every chart in the attached image."]
    proc=run_cli(path,args,CLI_TIMEOUT,cwd=workdir)
    reply=""
    if os.path.exists(out):
        with open(out,encoding="utf-8",errors="replace") as fh:
            reply=fh.read()
    if proc.returncode!=0 or not reply.strip():
        return None,str(proc.stderr or proc.stdout or "").strip()[-300:]
    return reply,""

def _cli_extract(cfg, model, data, media_type, effort):
    """Read the image through the installed Claude Code / Codex CLI, on the
    user's subscription. Returns (reply, failure_dict)."""
    import subprocess
    import tempfile
    from core.session_cli import find_cli
    binary="claude" if cfg["kind"]=="claude_cli" else "codex"
    label="Claude Code" if binary=="claude" else "Codex"
    path=find_cli(binary)
    if not path:
        return None,_fail(f"{cfg['name']} needs the {label} app installed and signed in. Install it, or choose another vision model in Settings > AI Providers.",True,cfg["name"],model)
    try:
        with tempfile.TemporaryDirectory(prefix="v360_vision_") as workdir:
            if binary=="claude":
                reply,detail=_claude_cli_reply(path,model,data,media_type,workdir)
            else:
                reply,detail=_codex_cli_reply(path,model,data,media_type,workdir,effort)
    except subprocess.TimeoutExpired:
        return None,_fail(f"{cfg['name']} did not answer within {CLI_TIMEOUT} seconds.",False,cfg["name"],model)
    except OSError as exc:
        return None,_fail(f"Could not start {label}: {exc}",True,cfg["name"],model)
    if reply is None:
        if _looks_logged_out(detail):
            login="claude auth login" if binary=="claude" else "codex login"
            return None,_fail(f"{label} is not signed in. Run `{login}` in a terminal, then try again.",True,cfg["name"],model)
        return None,_fail(f"AI vision call failed ({cfg['name']}): {detail or 'no answer'}",False,cfg["name"],model)
    return reply,None

def extract_charts_from_image(data: bytes, media_type: str):
    if not data or not str(media_type).startswith("image/"):
        return _fail("The pasted content is not a readable image.")
    from managers.settings_manager import get_settings
    settings=get_settings()
    selected=settings.get("vision.provider",DEFAULT_VISION_PROVIDER)
    selected=LEGACY_VISION_NAMES.get(selected,selected)
    cfg=next((x for x in VISION_PROVIDERS if x["name"]==selected),None)
    if not cfg:
        return _fail(f"Vision provider {selected!r} is unavailable. Choose one in Settings > AI Providers.",True,str(selected))
    model=settings.get("vision.model","") or cfg["model"]
    if cfg["kind"] in ("claude_cli","codex_cli"):
        reply,failure=_cli_extract(cfg,model,data,media_type,settings.get("vision.effort","medium"))
        if failure:
            return failure
        return _finish(reply,cfg,model)
    key=settings.get_api_key(cfg["key"])
    if not key:
        return _fail(f"Reading images via {cfg['name']} needs {cfg['key']} in Settings > AI Providers.",True,cfg["name"],model)
    try:
        encoded=base64.b64encode(data).decode("ascii")
        if cfg["kind"]=="anthropic":
            from anthropic import Anthropic
            response=Anthropic(api_key=key).messages.create(model=model,max_tokens=2048,system=PROMPT,messages=[{"role":"user","content":[{"type":"image","source":{"type":"base64","media_type":media_type,"data":encoded}},{"type":"text","text":"Extract every chart."}]}])
            reply="".join(getattr(b,"text","") or "" for b in response.content if getattr(b,"type",None)=="text")
        else:
            import requests
            body={"model":model,"messages":[{"role":"system","content":PROMPT},{"role":"user","content":[{"type":"image_url","image_url":{"url":f"data:{media_type};base64,{encoded}"}},{"type":"text","text":"Extract every chart."}]}],"stream":False}
            body.update({"reasoning_effort":settings.get("vision.effort","medium"),"max_completion_tokens":4096} if cfg["reasoning"] else {"max_tokens":2048})
            response=requests.post(cfg["url"],headers={"Content-Type":"application/json","Authorization":f"Bearer {key}"},json=body,timeout=(10,120))
            if response.status_code!=200:
                return _fail(f"AI vision call failed ({cfg['name']}): API error {response.status_code}.",False,cfg["name"],model)
            reply=((response.json().get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            if isinstance(reply,list):
                reply="".join(x.get("text","") for x in reply if isinstance(x,dict))
    except ImportError as exc:
        return _fail(f"Image extraction dependency is missing: {exc.name}.",True,cfg["name"],model)
    except Exception as exc:
        return _fail(f"AI vision call failed ({cfg['name']}): {type(exc).__name__}: {exc}",False,cfg["name"],model)
    return _finish(reply,cfg,model)

def _finish(reply, cfg, model):
    payload=_parse(reply) or {}
    charts=_normalize(payload)
    if not charts:
        return _fail("No chart data with a date was found in that image.",False,cfg["name"],model)
    try:
        confidence=min(1.0,max(0.0,float(payload.get("confidence",0.0))))
    except (TypeError,ValueError):
        confidence=0.0
    return {"ok":True,"error":"","provider_unavailable":False,"charts":charts,"confidence":confidence,"ambiguous":payload.get("ambiguous") is True,"notes":str(payload.get("notes") or ""),"provider":cfg["name"],"model":model}
