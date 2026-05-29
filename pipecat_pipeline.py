"""
Hermes Real-Time Voice Pipeline with Twilio PSTN.

Twilio Media Streams → Pipecat → Groq STT → Hermes LLM → ElevenLabs TTS → Twilio

Usage:
    python pipecat_pipeline.py          # uses .env + ~/.hermes/.env
    python pipecat_pipeline.py --dev    # verbose logging
"""

import os
import sys
import asyncio
import argparse
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

load_dotenv()
# Also load from Hermes home .env for shared keys
hermes_env = Path.home() / ".hermes" / ".env"
if hermes_env.exists():
    load_dotenv(hermes_env, override=False)

# ── Configuration ────────────────────────────────────────────────

HOST = os.getenv("PIPECAT_HOST", "localhost")
PORT = int(os.getenv("PIPECAT_PORT", "8080"))
PIPECAT_PUBLIC_HOST = os.getenv("PIPECAT_PUBLIC_HOST", "voice.reneetoufee.com")
VAD_SILENCE_MS = int(os.getenv("VAD_SILENCE_MS", "500"))
VAD_THRESHOLD = float(os.getenv("VAD_THRESHOLD", "0.5"))
ALLOWED_CALLER = os.getenv("ALLOWED_CALLER", "")

# API keys
TWILIO_SID = os.getenv("TWILIO_SID")
TWILIO_TOKEN = os.getenv("TWILIO_TOKEN")
TWILIO_NUMBER = os.getenv("TWILIO_NUMBER")
GROQ_KEY = os.getenv("GROQ_API_KEY") or os.getenv("GROQ_KEY")
ELEVENLABS_KEY = os.getenv("ELEVENLABS_API_KEY") or os.getenv("ELEVENLABS_KEY")
ELEVENLABS_VOICE = os.getenv("ELEVENLABS_VOICE", "K9DhA3x8BzZ1PmR6sTfW")
ELEVENLABS_MODEL = os.getenv("ELEVENLABS_MODEL", "eleven_turbo_v2_5")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENROUTER_KEY")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-v4-pro")


def validate_config():
    required = {
        "TWILIO_SID": TWILIO_SID,
        "TWILIO_TOKEN": TWILIO_TOKEN,
        "TWILIO_NUMBER": TWILIO_NUMBER,
        "GROQ_API_KEY": GROQ_KEY,
        "ELEVENLABS_API_KEY": ELEVENLABS_KEY,
        "OPENROUTER_API_KEY": OPENROUTER_KEY,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        logger.error(f"Missing env vars: {', '.join(missing)}")
        sys.exit(1)
    logger.info(f"Twilio: {TWILIO_NUMBER} | Voice: {ELEVENLABS_VOICE} | LLM: {OPENROUTER_MODEL}")


# ── Pipecat Pipeline (1.3.0 API) ─────────────────────────────────

def build_pipeline(websocket, stream_sid: str = ""):
    """Build a Pipecat pipeline for a given Twilio WebSocket connection."""
    from pipecat.audio.vad.silero import SileroVADAnalyzer
    from pipecat.audio.vad.vad_analyzer import VADParams
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.task import PipelineParams, PipelineTask
    from pipecat.pipeline.runner import PipelineRunner
    from pipecat.services.groq.stt import GroqSTTService
    from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
    from pipecat.services.openai.llm import OpenAILLMService
    from pipecat.transports.websocket.fastapi import (
        FastAPIWebsocketTransport,
        FastAPIWebsocketParams,
    )
    from pipecat.serializers.twilio import TwilioFrameSerializer

    # VAD: silence detection for turn-taking
    vad = SileroVADAnalyzer(
        params=VADParams(
            stop_secs=VAD_SILENCE_MS / 1000.0,
            confidence=VAD_THRESHOLD,
        )
    )

    # Transport: Twilio WebSocket ↔ Pipecat audio frames
    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_in_sample_rate=8000,
            audio_out_sample_rate=8000,
            vad_analyzer=vad,
            serializer=TwilioFrameSerializer(
                stream_sid=stream_sid,
                account_sid=TWILIO_SID,
                auth_token=TWILIO_TOKEN,
            ),
        ),
    )

    # STT: Groq Whisper
    stt = GroqSTTService(
        api_key=GROQ_KEY,
        model="whisper-large-v3-turbo",
    )

    # LLM: DeepSeek via OpenRouter
    llm = OpenAILLMService(
        api_key=OPENROUTER_KEY,
        base_url="https://openrouter.ai/api/v1",
        model=OPENROUTER_MODEL,
    )

    # TTS: ElevenLabs streaming
    tts = ElevenLabsTTSService(
        api_key=ELEVENLABS_KEY,
        voice_id=ELEVENLABS_VOICE,
        model=ELEVENLABS_MODEL,
    )

    # Pipeline: input → STT → LLM → TTS → output
    pipeline = Pipeline([
        transport.input(),
        stt,
        llm,
        tts,
        transport.output(),
    ])

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            allow_interruptions=True,
        ),
    )

    runner = PipelineRunner()
    runner.add_workers([task])

    return runner, task


# ── FastAPI Server ────────────────────────────────────────────────

async def run_server(dev_mode: bool = False):
    from fastapi import FastAPI, Request, WebSocket
    from fastapi.responses import HTMLResponse
    import uvicorn

    app = FastAPI(title="Hermes Voice Pipeline")

    @app.get("/")
    async def root():
        return HTMLResponse("<h1>Hermes Voice Pipeline</h1><p>Running.</p>")

    @app.post("/twilio/voice")
    async def twilio_voice_webhook(request: Request):
        """Twilio calls this when a call comes in. Returns TwiML."""
        form = await request.form()
        caller = form.get("From", "")

        if ALLOWED_CALLER and caller != ALLOWED_CALLER:
            logger.warning(f"Rejected call from {caller}")
            return HTMLResponse(
                '<?xml version="1.0" encoding="UTF-8"?><Response><Reject reason="busy"/></Response>',
                media_type="application/xml",
            )

        logger.info(f"Incoming call from {caller}")

        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="wss://{PIPECAT_PUBLIC_HOST}/twilio-media"/>
    </Connect>
</Response>"""
        return HTMLResponse(twiml, media_type="application/xml")

    @app.websocket("/twilio-media")
    async def twilio_media_stream(ws: WebSocket):
        """Raw audio WebSocket from Twilio Media Streams."""
        await ws.accept()
        logger.info("Twilio media stream connected")

        runner, task = build_pipeline(websocket=ws)

        try:
            await runner.run()
        except Exception as e:
            logger.error(f"Pipeline error: {e}")
        finally:
            logger.info("Pipeline ended, closing WebSocket")
            try:
                await ws.close()
            except Exception:
                pass

    logger.info(f"Starting on {HOST}:{PORT}")
    config = uvicorn.Config(app, host=HOST, port=PORT, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


# ── Entrypoint ────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Hermes Voice Pipeline")
    parser.add_argument("--dev", action="store_true", help="Development mode")
    args = parser.parse_args()

    if args.dev:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")

    validate_config()

    try:
        asyncio.run(run_server(dev_mode=args.dev))
    except KeyboardInterrupt:
        logger.info("Shutting down.")