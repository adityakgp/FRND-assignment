import os
import json
import base64
import asyncio
import struct
import threading
import uuid
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from websocket import create_connection

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

active_sessions = {}  
SESSION_TIMEOUT_SECONDS = 60


def float32_to_pcm16(float32_array):
    clipped = [max(-1.0, min(1.0, x)) for x in float32_array]
    pcm16 = b''.join(struct.pack('<h', int(x * 32767)) for x in clipped)
    return pcm16

def base64_encode_audio(float32_array):
    pcm_bytes = float32_to_pcm16(float32_array)
    return base64.b64encode(pcm_bytes).decode("ascii")

def ensure_openai_ws_connection(openai_ws, url, headers):
    if openai_ws.connected:
        return openai_ws
    else:
        print("[Backend] Reconnecting to OpenAI WebSocket...")
        openai_ws = create_connection(url, header=headers)
        print("[Backend] Reconnected to OpenAI WebSocket")
        return openai_ws


@app.websocket("/ws/audio")
async def audio_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("[Backend] Browser WebSocket connected")

    session_id = str(uuid.uuid4())
    await websocket.send_text(json.dumps({"type": "session_id", "session_id": session_id}))
    print(f"[Backend] Assigned Session ID: {session_id}")

    url = "wss://api.openai.com/v1/realtime?model=gpt-4o-mini-realtime-preview"
    headers = [
        "Authorization: Bearer " + OPENAI_API_KEY,
        "OpenAI-Beta: realtime=v1"
    ]

    openai_ws = create_connection(url, header=headers)


    active_sessions[session_id] = {
        "websocket": websocket,
        "openai_ws": openai_ws,
        "last_activity": asyncio.get_event_loop().time()
    }


    session_update = {
        "type": "session.update",
        "session": {
            "turn_detection": {
                "type": "semantic_vad",
                "eagerness": "low",
                "create_response": True,
                "interrupt_response": True
            }
        }
    }
    openai_ws.send(json.dumps(session_update))

    audio_queue = asyncio.Queue()
    loop = asyncio.get_event_loop()

    def openai_listener(loop):

        async def monitor_timeout():
            while True:
                await asyncio.sleep(5)
                now = asyncio.get_event_loop().time()
                if session_id not in active_sessions:
                    break
                last_active = active_sessions[session_id]["last_activity"]
                if now - last_active > SESSION_TIMEOUT_SECONDS:
                    print(f"[Backend] Session {session_id} timed out")
                    try:
                        await websocket.send_text(json.dumps({"type": "session_end"}))
                        await websocket.close()
                        openai_ws.send(json.dumps({"type": "control.stop"}))
                        openai_ws.close()
                    except:
                        pass
                    active_sessions.pop(session_id, None)
                    break

        asyncio.run_coroutine_threadsafe(monitor_timeout(), loop)  

        try:
            while session_id in active_sessions:
                try:
                    while openai_ws.connected:
                        response = openai_ws.recv()
                        data = json.loads(response)
                        # print("[OpenAI] Response Event:", json.dumps(data, indent=2))

                        if data.get("type") == "response.audio.delta":
                            # print("[[[[[1-------> here]]]]]")
                            # delta = json.dumps({"type": "audio_chunk", "audio": data["delta"]})
                            # print("data.get(delta) ", type(data.get("delta")))
                            delta = {"type": "audio_chunk", "audio": data.get("delta")}
                            if delta:
                                asyncio.run_coroutine_threadsafe(audio_queue.put(delta), loop)
                except Exception as e:
                    print("[OpenAI] Listener error during recv:", e)
                    break
        except Exception as e:
            print("[OpenAI] Listener outer error:", e)

    threading.Thread(target=openai_listener, args=(loop,), daemon=True).start()

    try:
        while True:
            done, pending = await asyncio.wait(
                [
                    asyncio.create_task(websocket.receive_text()),
                    asyncio.create_task(audio_queue.get())
                ],
                return_when=asyncio.FIRST_COMPLETED
            )

            for task in done:
                result = task.result()
                # print("[Result type]", type(result))

                if isinstance(result, str):
                    try:
                        data = json.loads(result)
                        # print("here 1------------->]]]]")
                        if "audio" in data:
                            active_sessions[session_id]["last_activity"] = asyncio.get_event_loop().time()
                            float_array = data["audio"]
                            encoded = base64_encode_audio(float_array)
                            event = {
                                "type": "input_audio_buffer.append",
                                "audio": encoded
                            }
                            openai_ws = ensure_openai_ws_connection(openai_ws, url, headers)
                            openai_ws.send(json.dumps(event))
                            # print("[Backend] Sent audio chunk to OpenAI")

                    except Exception as e:
                        print(f"[Backend] Error processing frontend audio: {e}")

                elif isinstance(result, dict) and result.get("type") == "audio_chunk":
                    # print("[here 2-------> sending audio_chunk to frontend]")
                    active_sessions[session_id]["last_activity"] = asyncio.get_event_loop().time()
                    await websocket.send_text(json.dumps(result))
                    # print("[Backend] Sent audio_chunk to frontend")

            for task in pending:
                task.cancel()

    except WebSocketDisconnect:
        print(f"[Backend] Session {session_id} disconnected")
        # print("[Backend] Browser WebSocket disconnected")
    finally:
        
        try:
            openai_ws.send(json.dumps({"type": "control.stop"}))
            openai_ws.close()
            
        except:
            pass
        active_sessions.pop(session_id, None)
        try:
            await websocket.close()
        except:
            pass
        print(f"[Backend] Session {session_id} closed")


@app.post("/force-stop/{session_id}")
async def force_stop(session_id: str):
    session = active_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        
        await session["websocket"].send_text(json.dumps({"type": "session_end"}))
        await session["websocket"].close()
        session["openai_ws"].send(json.dumps({"type": "control.stop"}))
        session["openai_ws"].close()
        print(f"[Backend] Force-stopped session {session_id}")
        del active_sessions[session_id]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "Session forcefully stopped"}

