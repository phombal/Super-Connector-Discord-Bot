import os
import asyncio
import uvicorn
from fastapi import FastAPI, BackgroundTasks
from dotenv import load_dotenv

from app.services.discord_bot import start_bot
from app.routers import discord_commands

# Load environment variables
load_dotenv()

# Create FastAPI app
app = FastAPI(
    title="Discord Super Connector Bot",
    description="A Discord bot that connects users based on their profiles and needs",
    version="1.0.0",
)

# Include routers
app.include_router(discord_commands.router)

@app.on_event("startup")
async def startup_event():
    """Start the Discord bot when the FastAPI app starts."""
    asyncio.create_task(start_bot())

@app.get("/")
async def root():
    """Root endpoint to check if the API is running."""
    return {"message": "Discord Super Connector Bot API is running"}

if __name__ == "__main__":
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))
    uvicorn.run("app.main:app", host=host, port=port, reload=True) 