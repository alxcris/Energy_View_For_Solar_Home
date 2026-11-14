from fastapi import FastAPI

app = FastAPI(title = "Solar Energy API") # Init

@app.get("/health") # Verifica daca functioneaza API-ul
def health():
    return {"status": "ok"} # rasp JSON ca e ok