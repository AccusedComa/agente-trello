# app.py — Agente Trello “conversacional”
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import os, re, requests

APP_TITLE = "Agente Trello"
app = FastAPI(title=APP_TITLE)

# ---- Config / Defaults ----
TRELLO_KEY   = os.getenv("TRELLO_KEY")
TRELLO_TOKEN = os.getenv("TRELLO_TOKEN")

# defaults p/ testes (pode mudar por env: DEFAULT_BOARD/DEFAULT_LIST)
DEFAULT_BOARD = os.getenv("DEFAULT_BOARD", "yeIqLYtE")
DEFAULT_LIST  = os.getenv("DEFAULT_LIST",  "Tarefas")

BASE = "https://api.trello.com/1"

def _need_env():
    if not TRELLO_KEY or not TRELLO_TOKEN:
        raise HTTPException(400, "Defina TRELLO_KEY e TRELLO_TOKEN nas variáveis de ambiente.")

def tget(path, **params):
    _need_env(); params.update({"key": TRELLO_KEY, "token": TRELLO_TOKEN})
    r = requests.get(BASE + path, params=params, timeout=30); r.raise_for_status(); return r.json()

def tpost(path, **params):
    _need_env(); params.update({"key": TRELLO_KEY, "token": TRELLO_TOKEN})
    r = requests.post(BASE + path, params=params, timeout=30); r.raise_for_status(); return r.json()

def tput(path, **params):
    _need_env(); params.update({"key": TRELLO_KEY, "token": TRELLO_TOKEN})
    r = requests.put(BASE + path, params=params, timeout=30); r.raise_for_status(); return r.json()

def due_to_iso(due: Optional[str]) -> Optional[str]:
    """Aceita: DD/MM/AAAA, DDMMAAAA, YYYY-MM-DD ou ISO; retorna ISO com T12:00:00Z."""
    if not due: return None
    s = due.strip()
    # só dígitos? vira DD/MM/AAAA
    digits = re.sub(r"\D", "", s)
    if len(digits) == 8 and digits == s:
        s = f"{digits[:2]}/{digits[2:4]}/{digits[4:]}"
    # DD/MM/AAAA
    try:
        return datetime.strptime(s, "%d/%m/%Y").strftime("%Y-%m-%dT12:00:00Z")
    except ValueError:
        pass
    # YYYY-MM-DD
    try:
        return datetime.strptime(s, "%Y-%m-%d").strftime("%Y-%m-%dT12:00:00Z")
    except ValueError:
        pass
    # já é ISO?
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}([T ].+)?", s):
        # se não tiver hora, crava 12:00Z
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}$", s):
            return s + "T12:00:00Z"
        return s
    raise HTTPException(400, "Data inválida. Use DD/MM/AAAA, DDMMAAAA, YYYY-MM-DD ou ISO.")

# ---------- Schemas ----------
class CreateCardBody(BaseModel):
    board: Optional[str] = None          # id/shortlink ou nome
    list_name_or_id: Optional[str] = None
    title: Optional[str] = None
    desc: Optional[str] = ""
    due: Optional[str] = None            # BR/ISO; será normalizado
    checklist: Optional[List[str] | str] = []  # lista de strings OU string “a, b, c”

class CheckItemsBody(BaseModel):
    board: Optional[str] = None
    list_name_or_id: Optional[str] = None
    card_name: Optional[str] = None
    items: Optional[List[str] | str] = None

# ---------- Rotas “seguras” ----------
@app.get("/")
def root():
    return {"status": "online", "app": APP_TITLE, "trello_env": bool(TRELLO_KEY and TRELLO_TOKEN)}

@app.get("/health")
def health():
    return {"status": "ok", "trello_env": bool(TRELLO_KEY and TRELLO_TOKEN)}

# ---------- Utilidades ----------
def resolve_board_id(board_hint: str) -> str:
    """Aceita id/shortlink OU nome do board."""
    # tenta direto
    try:
        return tget(f"/boards/{board_hint}", fields="id")["id"]
    except Exception:
        pass
    # por nome
    boards = [b for b in tget("/members/me/boards", fields="id,name,closed") if not b["closed"]]
    m = next((b for b in boards if b["name"].strip().lower() == board_hint.strip().lower()), None)
    if not m:
        raise HTTPException(404, f"Board '{board_hint}' não encontrado.")
    return m["id"]

def resolve_list_id(board_id: str, list_hint: str) -> str:
    if re.fullmatch(r"[0-9a-f]{24}", list_hint or "", re.I):
        return list_hint
    lists_ = [l for l in tget(f"/boards/{board_id}/lists", fields="id,name,closed") if not l["closed"]]
    m = next((l for l in lists_ if l["name"].strip().lower() == (list_hint or "").strip().lower()), None)
    if not m:
        raise HTTPException(404, f"Lista '{list_hint}' não encontrada.")
    return m["id"]

def find_card(list_id: str, name: str):
    cards = tget(f"/lists/{list_id}/cards", fields="id,name,shortUrl")
    return next((c for c in cards if c["name"].strip().lower() == name.strip().lower()), None)

def ensure_checklist(card_id: str) -> str:
    cls = tget(f"/cards/{card_id}/checklists")
    if cls: return cls[0]["id"]
    return tpost(f"/cards/{card_id}/checklists", name="Checklist")["id"]

def normalize_items(v) -> List[str]:
    if v is None: return []
    if isinstance(v, list): return [x.strip() for x in v if str(x).strip()]
    # string “a, b, c”
    return [x.strip() for x in str(v).split(",") if x.strip()]

# ---------- Listagem ----------
@app.get("/api/boards")
def api_boards():
    return [b for b in tget("/members/me/boards", fields="id,name,closed") if not b["closed"]]

@app.get("/api/lists")
def api_lists(board: str):
    bid = resolve_board_id(board)
    return [l for l in tget(f"/boards/{bid}/lists", fields="id,name,closed") if not l["closed"]]

# ---------- Conversacional: criar card ----------
@app.post("/api/create_card")
def api_create_card(body: CreateCardBody):
    # defaults para agilizar teste
    board = body.board or DEFAULT_BOARD
    list_hint = body.list_name_or_id or DEFAULT_LIST

    asks = []
    if not body.board and not DEFAULT_BOARD:
        asks.append("Qual board você quer usar? (envie em 'board')")
    if not body.list_name_or_id and not DEFAULT_LIST:
        asks.append("Qual lista você quer usar? (envie em 'list_name_or_id')")
    if not body.title:
        asks.append("Qual o título do card? (envie em 'title')")

    if asks:
        return JSONResponse({"ask": True, "perguntas": asks, "defaults": {"board": DEFAULT_BOARD, "list": DEFAULT_LIST}})

    bid = resolve_board_id(board)
    lid = resolve_list_id(bid, list_hint)

    due_iso = due_to_iso(body.due) if body.due else None
    card = tpost("/cards", idList=lid, name=body.title, desc=body.desc or "", due=due_iso)

    items = normalize_items(body.checklist)
    if items:
        clid = ensure_checklist(card["id"])
        for it in items:
            tpost(f"/checklists/{clid}/checkItems", name=it)

    return {"ok": True, "card": {"id": card["id"], "name": card["name"], "url": card.get("shortUrl")}}

# ---------- Conversacional: marcar itens ----------
@app.post("/api/check_items")
def api_check_items(body: CheckItemsBody):
    board = body.board or DEFAULT_BOARD
    list_hint = body.list_name_or_id or DEFAULT_LIST

    asks = []
    if not body.board and not DEFAULT_BOARD:
        asks.append("Qual board? (envie em 'board')")
    if not body.list_name_or_id and not DEFAULT_LIST:
        asks.append("Qual lista? (envie em 'list_name_or_id')")
    if not body.card_name:
        asks.append("Qual o nome exato do card? (envie em 'card_name')")
    if not body.items:
        asks.append("Quais itens deseja marcar? (envie em 'items' — pode ser lista ou 'a, b, c')")
    if asks:
        return JSONResponse({"ask": True, "perguntas": asks, "defaults": {"board": DEFAULT_BOARD, "list": DEFAULT_LIST}})

    bid = resolve_board_id(board)
    lid = resolve_list_id(bid, list_hint)
    card = find_card(lid, body.card_name)
    if not card:
        raise HTTPException(404, "Card não encontrado.")

    wanted = {x.lower() for x in normalize_items(body.items)}
    marked = []
    for cl in tget(f"/cards/{card['id']}/checklists"):
        for it in cl["checkItems"]:
            if it["name"].strip().lower() in wanted and it.get("state") != "complete":
                tput(f"/cards/{card['id']}/checkItem/{it['id']}", state="complete")
                marked.append(it["name"])

    return {"ok": True, "marcados": marked, "card": card.get("shortUrl")}

# ---------- Erros limpos ----------
@app.exception_handler(HTTPException)
def http_exc_handler(_, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"ok": False, "error": exc.detail})
