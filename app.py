from fastapi import FastAPI
import requests
import os

app = FastAPI()

TRELLO_KEY = os.getenv("TRELLO_KEY")
TRELLO_TOKEN = os.getenv("TRELLO_TOKEN")
BASE_URL = "https://api.trello.com/1"

@app.get("/")
def home():
    return {"status": "Agente Trello online!"}

@app.post("/criar_card")
def criar_card(board_id: str, list_id: str, nome: str, desc: str = "", due: str = None):
    url = f"{BASE_URL}/cards"
    query = {
        'idList': list_id,
        'name': nome,
        'desc': desc,
        'key': TRELLO_KEY,
        'token': TRELLO_TOKEN
    }
    if due:
        query['due'] = due
    r = requests.post(url, params=query)
    return r.json()
