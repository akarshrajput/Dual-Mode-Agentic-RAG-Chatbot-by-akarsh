from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

try:
    from agent import run_agent_loop
except ImportError:
    from backend.agent import run_agent_loop

app = FastAPI(title="EMB Global Assessment RAG Chatbot")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    message: str

@app.post("/chat")
def chat(request: ChatRequest):
    def event_generator():
        for line in run_agent_loop(request.message):
            yield {"data": line.strip()}
            
    return EventSourceResponse(event_generator())

@app.get("/health")
def health():
    return {"status": "ok"}
