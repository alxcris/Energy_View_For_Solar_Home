from fastapi import FastAPI
from app.routes import router as energy_router
from fastapi.middleware.cors import CORSMiddleware
from app.db.database import init_db

init_db()
app = FastAPI(title="Solar Energy API")
app.include_router(energy_router)

# Cu ce hosts e compatibil site-ul:
origins = [ 
    "http://localhost",
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:8080",
    "http://localhost:8501",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins = origins,
    allow_credentials = True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health") # Verifica daca functioneaza API-ul
def health():
    return {"status": "ok"} # rasp JSON ca e ok

