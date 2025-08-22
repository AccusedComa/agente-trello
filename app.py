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
