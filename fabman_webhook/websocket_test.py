from fastapi import FastAPI, WebSocket
import uvicorn

app = FastAPI()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Einfache WebSocket-Verbindung, die Nachrichten empfängt und zurücksendet."""
    await websocket.accept()
    await websocket.send_text("WebSocket-Verbindung hergestellt!")
    
    try:
        while True:
            message = await websocket.receive_text()
            await websocket.send_text(f"Echo: {message}")
    except Exception as e:
        print(f"WebSocket-Fehler: {e}")

if __name__ == "__main__":
    uvicorn.run("websocket_test:app", host="0.0.0.0", port=8000, reload=True)
