from fastapi import FastAPI, HTTPException, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse
import os, re, requests
from datetime import datetime

app = FastAPI(title="Agente Trello")

# --- Config (somente lidas quando necessário) ---
def trello_env_ok():
    return bool(os.getenv("TRELLO_KEY") and os.getenv("TRELLO_TOKEN"))

def tget(path, **params):
    key, token = os.getenv("TRELLO_KEY"), os.getenv("TRELLO_TOKEN")
    if not key or not token:
        raise HTTPException(400, "Defina TRELLO_KEY e TRELLO_TOKEN nas variáveis de ambiente.")
    params.update({"key": key, "token": token})
    r = requests.get("https://api.trello.com/1" + path, params=params, timeout=30)
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text)
    return r.json()

def tpost(path, **params):
    key, token = os.getenv("TRELLO_KEY"), os.getenv("TRELLO_TOKEN")
    if not key or not token:
        raise HTTPException(400, "Defina TRELLO_KEY e TRELLO_TOKEN nas variáveis de ambiente.")
    params.update({"key": key, "token": token})
    r = requests.post("https://api.trello.com/1" + path, params=params, timeout=30)
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text)
    return r.json()

def tput(path, **params):
    key, token = os.getenv("TRELLO_KEY"), os.getenv("TRELLO_TOKEN")
    if not key or not token:
        raise HTTPException(400, "Defina TRELLO_KEY e TRELLO_TOKEN nas variáveis de ambiente.")
    params.update({"key": key, "token": token})
    r = requests.put("https://api.trello.com/1" + path, params=params, timeout=30)
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text)
    return r.json()

def due_br_to_iso(due_br: str | None) -> str | None:
    if not due_br:
        return None
    digits = re.sub(r"\D", "", due_br)
    if len(digits) == 8:
        due_br = f"{digits[:2]}/{digits[2:4]}/{digits[4:]}"
    try:
        return datetime.strptime(due_br, "%d/%m/%Y").strftime("%Y-%m-%dT12:00:00Z")
    except ValueError:
        raise HTTPException(400, "Data inválida. Use DD/MM/AAAA ou DDMMAAAA.")

# --- Root & health (nunca quebram) ---
@app.get("/", response_class=HTMLResponse)
def root():
    env_ok = "ok ✅" if trello_env_ok() else "faltando ⚠️"
    return f"""
    <h1>Agente Trello</h1>
    <p>Status: online.</p>
    <p>Trello env: {env_ok}</p>
    <ul>
      <li><a href="/docs">/docs</a> (Swagger)</li>
      <li><a href="/health">/health</a></li>
    </ul>
    """

@app.get("/health")
def health():
    return {"status": "ok", "trello_env": trello_env_ok()}

# --- Endpoints Trello (só falham se env ausente) ---
@app.get("/api/boards")
def boards():
    return [b for b in tget("/members/me/boards", fields="id,name,closed") if not b["closed"]]

@app.get("/api/lists")
def lists(board: str):
    bid = tget(f"/boards/{board}", fields="id")["id"]
    return [l for l in tget(f"/boards/{bid}/lists", fields="id,name,closed") if not l["closed"]]

@app.post("/api/create_list")
def create_list(board: str = Form(...), name: str = Form(...)):
    bid = tget(f"/boards/{board}", fields="id")["id"]
    new_list = tpost("/lists", idBoard=bid, name=name)
    return new_list

@app.post("/api/create_card")
def create_card(
    board: str = Form(...),
    list_name_or_id: str = Form(...),
    title: str = Form(...),
    desc: str = Form(""),
    due: str = Form(""),
    checklist: str = Form("")
):
    bid = tget(f"/boards/{board}", fields="id")["id"]
    # resolve list id (accepts id or name)
    if re.fullmatch(r"[0-9a-f]{24}", list_name_or_id, re.I):
        lid = list_name_or_id
    else:
        lists_ = [l for l in tget(f"/boards/{bid}/lists", fields="id,name,closed") if not l["closed"]]
        match = next((l for l in lists_ if l["name"].strip().lower() == list_name_or_id.strip().lower()), None)
        if not match:
            raise HTTPException(404, f"Lista '{list_name_or_id}' não encontrada.")
        lid = match["id"]

    due_iso = due_br_to_iso(due) if due else None
    card = tpost("/cards", idList=lid, name=title, desc=desc, due=due_iso)

    if checklist.strip():
        items = [x.strip() for x in checklist.split(",") if x.strip()]
        cl = tpost(f"/cards/{card['id']}/checklists", name="Checklist")
        for it in items:
            tpost(f"/checklists/{cl['id']}/checkItems", name=it)

    return {"ok": True, "card": card}

@app.post("/api/check_items")
def check_items(
    board: str = Form(...),
    list_name_or_id: str = Form(...),
    card_name: str = Form(...),
    items: str = Form(...)
):
    bid = tget(f"/boards/{board}", fields="id")["id"]

    if re.fullmatch(r"[0-9a-f]{24}", list_name_or_id, re.I):
        lid = list_name_or_id
    else:
        lists_ = [l for l in tget(f"/boards/{bid}/lists", fields="id,name,closed") if not l["closed"]]
        match = next((l for l in lists_ if l["name"].strip().lower() == list_name_or_id.strip().lower()), None)
        if not match:
            raise HTTPException(404, f"Lista '{list_name_or_id}' não encontrada.")
        lid = match["id"]

    cards = tget(f"/lists/{lid}/cards", fields="id,name,shortUrl")
    card = next((c for c in cards if c["name"].strip().lower() == card_name.strip().lower()), None)
    if not card:
        raise HTTPException(404, "Card não encontrado.")

    wanted = {x.strip().lower() for x in items.split(",") if x.strip()}
    marked = []
    for cl in tget(f"/cards/{card['id']}/checklists"):
        for it in cl["checkItems"]:
            if it["name"].strip().lower() in wanted and it.get("state") != "complete":
                tput(f"/cards/{card['id']}/checkItem/{it['id']}", state="complete")
                marked.append(it["name"])

    return {"ok": True, "marcados": marked, "card": card.get("shortUrl")}
    
# --- Handler global de exceções (para respostas limpas) ---
@app.exception_handler(HTTPException)
def http_exc_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"ok": False, "error": exc.detail})
# --- Test Next part ---
from fastapi import FastAPI
import os

app = FastAPI()

@app.get("/")
def root():
    return {"status": "Agente Trello online!"}

@app.get("/health")
def health():
    trello_key = os.getenv("TRELLO_KEY") is not None
    trello_token = os.getenv("TRELLO_TOKEN") is not None
    return {
        "status": "ok",
        "trello_key": trello_key,
        "trello_token": trello_token
    }
