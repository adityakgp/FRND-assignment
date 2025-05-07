# Voice-to-Voice Application - README

This document outlines the setup instructions, session flow, and key security considerations for the Voice-to-Voice application. This application allows real-time audio communication with an AI backend.

## Table of Contents

1.  Setup
    * Backend Setup
    * Frontend Setup
2.  Session Flow
    * Initiation
    * Audio Streaming
    * AI Response
    * Session End
3.  Key Security Steps

## 1. Setup

### Backend Setup

1.  **Prerequisites:**
    * Python 3.x installed.
    * pip (Python package installer) installed.

2.  **Clone the repository:**
    ```bash
    git clone <your_repository_url>
    cd backend
    ```

3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
    

4.  **Environment Variables:**
    * Create a `.env` file in the `backend` directory.
    * Add your OpenAI API key to the `.env` file:
        ```
        OPENAI_API_KEY=YOUR_OPENAI_API_KEY
        ```
        

5.  **Run the backend:**
    ```bash
    uvicorn main:app --reload
    ```
    
    The backend server will start at `http://localhost:8000`.

### Frontend Setup

1.  **Prerequisites:**
    * Node.js and npm (Node Package Manager) installed.

2.  **Navigate to the frontend directory:**
    ```bash
    cd frontend
    ```

3.  **Install dependencies:**
    ```bash
    npm install
    ```

4.  **Run the frontend:**
    ```bash
    npm start
    ```
    The frontend will attempt to connect to the backend WebSocket at `ws://localhost:8000/ws/audio`.

## 2. Session Flow

### Initiation

1.  When the frontend application loads, it establishes a WebSocket connection with the backend at the `/ws/audio` endpoint.
2.  The backend receives the WebSocket connection and assigns a unique `session_id` to this connection using `uuid.uuid4()`.
3.  The backend sends a JSON message to the frontend containing the `session_id`:
    ```json
    {"type": "session_id", "session_id": "<unique_session_id>"}
    ```
4.  The frontend stores this `session_id`.
5.  The backend then establishes a WebSocket connection with the OpenAI API using the provided API key

### Audio Streaming

1.  When the user clicks the "Start Recording" button on the frontend:
    * The browser requests access to the user's microphone using `navigator.mediaDevices.getUserMedia()`.
    * An `AudioContext` and a `ScriptProcessorNode` are created to capture and process the audio data in chunks.
    * The `onaudioprocess` event of the `ScriptProcessorNode` is triggered periodically.
    * Inside this event handler, the audio data (as a `Float32Array`) is converted to a regular JavaScript array and sent to the backend as a JSON message over the WebSocket:
        
    * The frontend logs each sent chunk to the console.

2.  The backend receives the audio data:
    * It updates the `last_activity` timestamp for the session.
    * The `Float32Array` is converted to PCM 16-bit format and then base64 encoded.
    * This base64 encoded audio is sent to the OpenAI WebSocket endpoint
        ```json
        {
            "type": "input_audio_buffer.append",
            "audio": "<base64_encoded_audio>"
        }
        ```

### AI Response

1.  The OpenAI API processes the incoming audio and sends back real-time audio responses via the WebSocket as `response.audio.delta` events.
2.  The backend's `openai_listener` thread continuously listens for messages from the OpenAI WebSocket.
3.  When a `response.audio.delta` event is received:
    * The audio delta (which is base64 encoded) is extracted.
    * A new JSON message with the `type` as `audio_chunk` and the base64 encoded audio is put into an asynchronous queue (`audio_queue`).
4.  The backend's main WebSocket handler concurrently waits for either new audio from the frontend or a new audio chunk from the OpenAI listener.
5.  When an `audio_chunk` is retrieved from the queue, the backend sends it to the connected frontend WebSocket:
    ```json
    {"type": "audio_chunk", "audio": "<base64_encoded_audio_delta>"}
    ```
6.  The frontend receives the `audio_chunk`:
    * It updates the status to "Responding...".
    * The base64 encoded audio is decoded, converted to a `Float32Array`, and played back using the Web Audio API.
    * The audio chunks are queued and played sequentially to provide a continuous audio output.
    * Once the playback queue is empty, the status is set back to "Idle".

### Session End

1.  **Automatic Timeout:**
    * The backend has a session timeout mechanism (`SESSION_TIMEOUT_SECONDS = 60`).
    * A background task (`monitor_timeout`) checks for inactivity in each session.
    * If no audio is received from the frontend for more than the timeout period, the backend:
        * Sends a `{"type": "session_end"}` message to the frontend.
        * Closes the frontend WebSocket connection.
        * Sends a `{"type": "control.stop"}` message to the OpenAI WebSocket and closes that connection.
        * Removes the session from the `active_sessions` dictionary.
    * The frontend, upon receiving the `session_end` message, displays an alert and stops any ongoing recording.

2.  **Manual End (Frontend):**
    * The frontend provides an "End Session" button.
    * Clicking this button triggers an HTTP POST request to the backend's `/force-stop/{sessionId}` endpoint.
    * The backend, upon receiving this request:
        * Retrieves the session information from `active_sessions`.
        * Sends a `{"type": "session_end"}` message to the frontend WebSocket.
        * Closes the frontend WebSocket connection.
        * Sends a `{"type": "control.stop"}` message to the OpenAI WebSocket and closes that connection.
        * Removes the session from `active_sessions`.
        * Returns a JSON response indicating the session has been stopped.
    * The frontend displays an alert confirming the session ended.


## 3. Key Security Steps

1.  **Secure Handling of OpenAI API Key:**
    * The OpenAI API key is loaded from an environment variable (`.env` file).


3.  **Session Management:**
    * The backend uses a unique `session_id` for each connection.
    * The session timeout helps to automatically terminate inactive sessions.

4.  **CORS Configuration:**
    * The backend uses `fastapi.middleware.cors.CORSMiddleware`.

5.  **Error Handling:**
    * The backend includes error handling for WebSocket disconnections and OpenAI API interactions.