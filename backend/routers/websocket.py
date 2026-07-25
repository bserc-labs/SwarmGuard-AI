from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from services.ws_manager import ws_manager
from services.auth_service import decode_access_token

router = APIRouter(prefix="/ws", tags=["websocket"])

@router.websocket("/telemetry")
async def websocket_endpoint(websocket: WebSocket, token: str = None):
    if not token:
        await websocket.close(code=1008, reason="Missing token")
        return
        
    payload = decode_access_token(token)
    if not payload:
        await websocket.close(code=1008, reason="Invalid token")
        return
        
    await ws_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
