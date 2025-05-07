import React, { useEffect, useRef, useState } from "react";

function App() {
  const ws = useRef(null);
  const audioContextRef = useRef(null);
  const sourceNodeRef = useRef(null);
  const processorNodeRef = useRef(null);
  const mediaStreamRef = useRef(null);
  const playbackQueueRef = useRef([]); 
  const isPlayingRef = useRef(false); 
  
  
  const [status, setStatus] = useState("Idle");
  const [sessionId, setSessionId] = useState(null);
  const [connected, setConnected] = useState(false);
  const [recording, setRecording] = useState(false);


  const endSession = async () => {
    if (!sessionId) return;
    try {
      const res = await fetch(`http://localhost:8000/force-stop/${sessionId}`, {
        method: "POST",
      });
      const data = await res.json();
      alert(data.status || "Session forcefully ended");
    } catch (e) {
      alert("Failed to end session");
    }
  };

  const startRecording = async () => {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    mediaStreamRef.current = stream;

    
    audioContextRef.current = new AudioContext({ sampleRate: 16000 });
    const sourceNode = audioContextRef.current.createMediaStreamSource(stream);
    const processorNode = audioContextRef.current.createScriptProcessor(4096, 1, 1);
    
    processorNode.onaudioprocess = (event) => {
      const float32 = event.inputBuffer.getChannelData(0);
      if (ws.current && ws.current.readyState === WebSocket.OPEN) {
        ws.current.send(JSON.stringify({ audio: Array.from(float32) }));
        console.log("[Frontend] Sent chunk:", typeof(JSON.stringify({ audio: Array.from(float32) })));
      }
    };
    
    sourceNode.connect(processorNode);
    processorNode.connect(audioContextRef.current.destination);
    setStatus("Listening...");
    setRecording(true);
    console.log("[Frontend] Recording started");
  };

  const stopRecording = () => {
    processorNodeRef.current?.disconnect();
    sourceNodeRef.current?.disconnect();
    audioContextRef.current?.close();
    mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
    setStatus("Idle");
    setRecording(false);
    console.log("[Frontend] Recording stopped");
  };

  const playPCMBase64Chunk = async (base64Audio) => {
    if (!base64Audio || base64Audio.length < 10) return;

    const audioContext = audioContextRef.current || new AudioContext({ sampleRate: 16000 });
    audioContextRef.current = audioContext;

    await audioContext.resume();

    const binary = atob(base64Audio);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
      bytes[i] = binary.charCodeAt(i);
    }

    const view = new DataView(bytes.buffer);
    const float32Array = new Float32Array(bytes.length / 2);
    for (let i = 0; i < float32Array.length; i++) {
      const int16 = view.getInt16(i * 2, true); // little-endian
      float32Array[i] = int16 / 32768;
    }

    const buffer = audioContext.createBuffer(1, float32Array.length, 16000);
    buffer.copyToChannel(float32Array, 0, 0);

    playbackQueueRef.current.push(buffer);

    if (!isPlayingRef.current) {
      playNextChunk();
    }
  };

  const playNextChunk = () => {
    if (playbackQueueRef.current.length === 0) {
      isPlayingRef.current = false;
      return;
    }

    isPlayingRef.current = true;

    const buffer = playbackQueueRef.current.shift();
    const source = audioContextRef.current.createBufferSource();
    source.buffer = buffer;
    source.connect(audioContextRef.current.destination);

    source.start();
    source.onended = () => {
      playNextChunk(); 
      if (playbackQueueRef.current.length === 0) {
        setStatus("Idle");
      }
    };
  };

  const connectWebSocket = () => {
    ws.current = new WebSocket("ws://localhost:8000/ws/audio");

    ws.current.onopen = () => {
      console.log("[Frontend] WebSocket connected");
      setConnected(true);
    };

    ws.current.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === "session_id") {
          setSessionId(data.session_id);
          return;
        }

        if (data.type === "session_end") {
          alert("The session has ended.");
          stopRecording(); 
          return;
        }
        if (data.type === "audio_chunk" && data.audio) {
          setStatus("Responding...");
          playPCMBase64Chunk(data.audio);
        }
      } catch (err) {
        console.error("[Frontend] Error parsing or handling audio chunk:", err);
      }
    };

    ws.current.onclose = () => {
      console.log("[Frontend] WebSocket closed");
      setConnected(false);
      setRecording(false);
    };
  };

  useEffect(() => {
    connectWebSocket();
    return () => {
      ws.current?.close();
    };
  }, []);

  return (
    <div style={{ padding: 20 }}>
      <h1>🎙️ Voice-to-Voice Test</h1>
      <h2>Status: {status}</h2>
      {!recording ? (
        <button onClick={startRecording} disabled={!connected}>
          Start Recording
        </button>
      ) : (
        <button onClick={stopRecording}>
          Stop Recording
        </button>
      )}

      {sessionId && (
        <button onClick={endSession} style={{ marginLeft: 10 }}>
          End Session
        </button>
      )}
    </div>
  );
}

export default App;
