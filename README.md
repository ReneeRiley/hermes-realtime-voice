# Hermes Realtime Voice

**Real-time two-way voice conversation for Hermes Agent.**

Goal: build a voice interface that's better than Jarvis — streaming, interruptible, low-latency, conversational.

## Architecture

```
┌─────────────────┐     ┌──────────────┐     ┌───────────┐     ┌────────────┐
│  ESP32/HA Voice │────▶│ faster-whisper│────▶│  Groq API │────▶│ ElevenLabs │
│  PE (mic input) │     │  (STT - CPU) │     │  (LLM)    │     │ (TTS)      │
└─────────────────┘     └──────────────┘     └───────────┘     └────────────┘
                                                                      │
                                                                      ▼
                                                              ┌──────────────┐
                                                              │  Echo Dot /  │
                                                              │  Speaker     │
                                                              └──────────────┘
                        All orchestrated by
                     ┌──────────────────────┐
                     │  Pipecat 1.3.0       │
                     │  (streaming pipeline) │
                     └──────────────────────┘
```

## Latency Budget (Measured)

| Component            | Time          | Status |
|---------------------|---------------|--------|
| STT (faster-whisper base) | ~830ms (5s audio) | ✅ |
| LLM (Groq llama-3.1-8b)  | 310ms TTFT    | ✅ |
| TTS (ElevenLabs Flash)   | 442ms TTFA    | ✅ |
| **Total E2E**            | **~1.6s**     | ✅ |

## Status

**Phase 1: Prototyping** — cloud LLM path active. Local GPU (Tesla P4) planned for Phase 2.

- [x] Architecture research & Council deliberation
- [x] Framework selection (Pipecat 1.3.0)
- [x] Groq API configured (310ms TTFT)
- [x] ElevenLabs streaming TTS (442ms TTFA)
- [x] Hardware plan (ESP32 / HA Voice PE)
- [ ] Voice pipeline prototype
- [ ] Audio hardware deployment

## Hardware Requirements

- **Microphone:** ESP32-S3 DIY ($15-20) or Home Assistant Voice PE ($30-50)
- **Speaker:** Amazon Echo Dot (existing) or wired speaker
- **Server:** Linux host running Hermes Agent + Pipecat
- **Future GPU:** NVIDIA Tesla P4 ($70-100) for local LLM inference

## Known Limitations

- Streaming TTS requires ElevenLabs (cloud) — Edge TTS is batch-only (6s for 50 words)
- iPhone cannot do continuous background mic streaming — dedicated hardware required
- No sound card on current Hermes host
- Local LLM path unvalidated until Tesla P4 GPU acquired

## License

MIT
