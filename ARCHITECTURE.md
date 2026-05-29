# Architecture: Twilio to Pipecat to Hermes Voice Pipeline

## End-to-End Flow

```
YOUR PHONE (anywhere)
  Dials +1-xxx-xxx-xxxx
       │ PSTN (G.711 mu-law, 8 kHz)
       ▼
TWILIO CLOUD
  Phone Number (+$1/mo)
  "A Call Comes In" webhook fires
  TwiML connects audio to WebSocket
  Media Streams:
    Inbound:  raw PCM 8kHz mono 16-bit
    Outbound: raw PCM 8kHz mono 16-bit
    Events:   media, start, stop, mark
       │ WSS (encrypted)
       ▼
CLOUDFLARE TUNNEL (cloudflared)
  voice.hermes.local → localhost:8080
  TLS termination, no open firewall ports
  Already running on Dell R760xd
       │ localhost:8080
       ▼
PIPECAT PIPELINE (pipecat_pipeline.py)

  TwilioTransport  ← WebSocket + mu-law ↔ PCM
       │ raw audio frames
       ▼
  TwilioFrame Serializer  ← Audio resampling if needed
       │
     ┌─┴──┐
     ▼    ▼
  STT    User Speaking Frame  ← Voice Activity Detection
  (Groq)   (turns mic on/off)
  286ms
     │ partial + final transcripts
     ▼
  LLM Response Processor  ← Hermes Agent (DeepSeek v4-pro)
       │ full response text
       ▼
  TTS (ElevenLabs)  ← Turbo v2.5 streaming, 182ms first audio
       │ raw audio frames
       ▼
  TwilioTransport (outbound) → Back to Twilio → PSTN → Your phone
```

## Timing Budget

| Step | Latency | Cumulative |
|------|---------|------------|
| PSTN + Twilio | ~40ms | 40ms |
| Audio buffering | ~20ms | 60ms |
| Groq STT (first word) | ~100ms | 160ms |
| Groq STT (end of utterance) | ~286ms | 346ms |
| LLM reasoning | ~500-2000ms | 846-2346ms |
| ElevenLabs (first audio chunk) | ~182ms | 1028-2528ms |
| PSTN return | ~40ms | 1068-2568ms |

User-perceived gap between last word and first response: 0.5-2.5 seconds.
Human conversation gap: ~200ms. Acceptable for a thinking assistant experience.

## Turn Management

Pipecat handles these natively:

- End of turn: silence > 500ms allows sending transcript to LLM
- Interruption (barge-in): user speaks while Hermes is talking means flush TTS, process new input
- VAD: Voice Activity Detection filters background noise (car, office, etc.)

## Security

- WebSocket is WSS (TLS via Cloudflare to localhost, no plaintext exposed)
- Twilio validates origin via Account SID + Auth Token
- API keys never leave the homelab, only response audio streams out
- No recording storage unless explicitly enabled (Pipecat can save transcripts)
- Twilio caller ID filtering can restrict to your phone number only

## Tunneling Strategy

Production: Cloudflare Tunnel (cloudflared)
- Already running on Dell R760xd
- voice.hermes.local mapped to localhost:8080
- Zero open ports, automatic TLS
- If cloudflared is down, calls fail gracefully (Twilio gets 502, you get busy signal)

Development: ngrok
- ngrok http 8080
- Returns https://abc123.ngrok.io mapped to localhost:8080
- Set Twilio webhook to wss://abc123.ngrok.io/twilio/ws

## Failure Modes

| Failure | User Experience | Recovery |
|---------|----------------|----------|
| Pipecat crash | Call drops immediately | systemd restarts |
| STT timeout | "I didn't catch that" then retry | Automatic retry |
| LLM timeout | "Hmm, one sec" then retry | Automatic retry |
| TTS fail | Hermes text echoed back, no audio | Fallback message |
| Internet outage | Busy signal | Wait for connection |
| Twilio outage | Busy signal | Wait for Twilio