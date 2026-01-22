from fastapi import FastAPI
from fastapi import Request
from webhook_server import router as webhook_router

app = FastAPI(
    title="Resilient SRE Agent",
    description="AI-powered SRE agent with Sentry integration for automated error investigation",
    version="0.1.0",
)

# Include webhook routes with /sre prefix
app.include_router(webhook_router, prefix="/sre")


@app.get("/sre")
def hello_world():
    return {"message": "Hello, World from SRE Agent!"}


@app.get("/sre/health")
def health_check():
    return {"status": "healthy"}

@app.post("/sre/webhook/sentry")
async def sentry_webhook(request: Request):
    body = await request.body()
    print(body)
    return {"message": "Sentry webhook received at simple endpoint"}