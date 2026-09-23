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
)
DEFAULT_VISION_PROVIDER = "GPT-5.6 Luna"
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

def extract_charts_from_image(data: bytes, media_type: str):
    if not data or not str(media_type).startswith("image/"):
        return _fail("The pasted content is not a readable image.")
    from managers.settings_manager import get_settings
    settings=get_settings()
    selected=settings.get("vision.provider",DEFAULT_VISION_PROVIDER)
    selected={"GPT-5.4 Mini":"GPT-5.6 Luna","Kimi K2.6":"Kimi K3"}.get(selected,selected)
    cfg=next((x for x in VISION_PROVIDERS if x["name"]==selected),None)
    if not cfg:
        return _fail(f"Vision provider {selected!r} is unavailable. Choose one in Settings > AI Providers.",True,str(selected))
    model=settings.get("vision.model","") or cfg["model"]
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
    payload=_parse(reply) or {}
    charts=_normalize(payload)
    if not charts:
        return _fail("No chart data with a date was found in that image.",False,cfg["name"],model)
    try:
        confidence=min(1.0,max(0.0,float(payload.get("confidence",0.0))))
    except (TypeError,ValueError):
        confidence=0.0
    return {"ok":True,"error":"","provider_unavailable":False,"charts":charts,"confidence":confidence,"ambiguous":payload.get("ambiguous") is True,"notes":str(payload.get("notes") or ""),"provider":cfg["name"],"model":model}
