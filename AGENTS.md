# AGENTS.md — Hermes Realtime Voice

Instructions for AI coding assistants working on this project.

## Stack

- **Orchestration:** Pipecat 1.3.0 (Python streaming pipeline framework)
- **STT:** faster-whisper base model (CPU, RTF 0.17x)
- **LLM:** Groq API (llama-3.1-8b-instant, 310ms TTFT)
- **TTS:** ElevenLabs streaming (eleven_flash_v2_5, 442ms TTFA)
- **Transport:** Pipecat WebSocket or LiveKit (TBD based on client)
- **Mic input:** ESP32-S3 via ESPHome voice_assistant → HA → Pipecat
- **Speaker:** Amazon Echo Dot via notify.alexa_media_renee_s_echo_dot
- **Future:** NVIDIA Tesla P4 GPU for local Ollama inference ($70-100)

## Key Commands

```bash
# Activate venv
source /home/renee/.hermes/hermes-agent/venv/bin/activate

# Run pipeline
python voice_pipeline.py

# Test components individually
python -m tools.test_stt
python -m tools.test_llm
python -m tools.test_tts
```

## Environment Variables

All API keys in `/home/renee/.hermes/.env`:
- `GROQ_API_KEY` (line 24)
- `ELEVENLABS_API_KEY` (line 23)

## File Structure

```
hermes-realtime-voice/
├── README.md
├── AGENTS.md
├── voice_pipeline.py       # Main Pipecat pipeline
├── tools/
│   ├── test_stt.py         # STT benchmark
│   ├── test_llm.py         # LLM latency test
│   └── test_tts.py         # TTS streaming test
└── docs/
    └── architecture.md     # Full architecture decision record
```

## Code Standards

- All async where Pipecat requires it
- Type hints on public functions
- Logging instead of print for pipeline components
- Graceful fallback to turn-based mode on any component failure