from fastapi import FastAPI

app = FastAPI(title="Maestro API")

@app.get("/")
async def root():
    return {"message": "Maestro API is running"}

@app.get("/health")
async def health():
    return {"status": "healthy"}
