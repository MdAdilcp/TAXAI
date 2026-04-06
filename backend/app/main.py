from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.api.tax_routes import router as tax_router

app = FastAPI(
    title="TaxAI",
    description="Standalone Indian Tax Computation Engine — no government API dependencies.",
    version="0.2.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
app.include_router(tax_router)


@app.get("/health")
def health():
    return {"status": "ok"}
