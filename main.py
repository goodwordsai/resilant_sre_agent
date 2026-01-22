from fastapi import FastAPI

from webhook_server import router as webhook_router

app = FastAPI(
    title="Resilient SRE Agent",
    description="AI-powered SRE agent with Sentry integration for automated error investigation",
    version="0.1.0",
)

# Include webhook routes
app.include_router(webhook_router)


@app.get("/")
def hello_world():
    return {"message": "Hello, World!"}


@app.get("/health")
def health_check():
    return {"status": "healthy"}
