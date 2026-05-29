"""
Hermes Real-Time Voice Pipeline with Twilio PSTN.

Twilio Media Streams → Pipecat → Groq STT → Hermes LLM → ElevenLabs TTS → Twilio

Usage:
    python pipecat_pipeline.py          # uses .env config
    python pipecat_pipeline.py --dev    # ngrok-friendly, verbose logging
"""

import os
import sys
import asyncio
import argparse
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

load_dotenv()

# ── Configuration ────────────────────────────────────────────────

HOST = os.getenv("PIPECAT_HOST", "localhost")
PORT = int(os.getenv("PIPECAT_PORT", "8080"))
VAD_SILENCE_MS = int(os.getenv("VAD_SILENCE_MS", "500"))
VAD_THRESHOLD = float(os.getenv("VAD_THRESHOLD", "0.5"))
ALLOWED_CALLER = os.getenv("ALLOWED_CALLER", "")

# API keys
TWILIO_SID = os.getenv("TWILIO_SID")
TWILIO_TOKEN = os.getenv("TWILIO_TOKEN")
TWILIO_NUMBER = os.getenv("TWILIO_NUMBER")
GROQ_KEY = os.getenv("GROQ_KEY")
ELEVENLABS_KEY = os.getenv("ELEVENLABS_KEY")
ELEVENLABS_VOICE = os.getenv("ELEVENLABS_VOICE", "K9DhA3x8BzZ1PmR6sTfW")
ELEVENLABS_MODEL = os.getenv("ELEVENLABS_MODEL", "eleven_turbo_v2_5")
OPENROUTER_KEY = os.getenv("OPENROUTER_KEY")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-v4-pro")


def validate_config():
    """Check all required env vars are set."""
    required = {
        "TWILIO_SID": TWILIO_SID,
        "TWILIO_TOKEN": TWILIO_TOKEN,
        "TWILIO_NUMBER": TWILIO_NUMBER,
        "GROQ_KEY": GROQ_KEY,
        "ELEVENLABS_KEY": ELEVENLABS_KEY,
        "OPENROUTER_KEY": OPENROUTER_KEY,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        logger.error(f"Missing env vars: {', '.join(missing)}")
        logger.error("Copy .env.example to .env and fill in your keys.")
        sys.exit(1)

    logger.info("Configuration validated.")
    logger.info(f"  Twilio number: {TWILIO_NUMBER}")
    logger.info(f"  ElevenLabs voice: {ELEVENLABS_VOICE}")
    logger.info(f"  LLM model: {OPENROUTER_MODEL}")
    if ALLOWED_CALLER:
        logger.info(f"  Caller filter: only {ALLOWED_CALLER}")


# ── Pipecat Pipeline ─────────────────────────────────────────────

async def build_pipeline():
    """Build the Pipecat pipeline with Twilio transport."""

    try:
        from pipecat.audio.vad.silero import SileroVADAnalyzer
        from pipecat.pipeline.pipeline import Pipeline
        from pipecat.pipeline.runner import PipelineRunner
        from pipecat.pipeline.task import PipelineParams, PipelineTask
        from pipecat.services.groq import GroqSTTService
        from pipecat.services.elevenlabs import ElevenLabsTTSService
        from pipecat.services.openai import OpenAILLMService
        from pipecat.transports.network.fastapi_websocket import (
            FastAPIWebsocketTransport,
            FastAPIWebsocketParams,
        )
        from pipecat.processors.frameworks.rtvi import RTVIObserver, RTVIConfig
        from pipecat.serializers.twilio import TwilioFrameSerializer
    except ImportError as e:
        logger.error(f"Missing Pipecat dependency: {e}")
        logger.error("Install: pip install 'pipecat-ai[twilio]'")
        sys.exit(1)

    # ── Transport: Twilio WebSocket ──────────────────────────
    transport = FastAPIWebsocketTransport(
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            vad_analyzer=SileroVADAnalyzer(
                params=VADParams(
                    stop_secs=VAD_SILENCE_MS / 1000.0,
                    confidence=VAD_THRESHOLD,
                )
            ),
            serializer=TwilioFrameSerializer(
                stream_sid=None,  # Set per-call from Twilio start event
            ),
        )
    )

    # ── STT: Groq streaming ──────────────────────────────────
    stt = GroqSTTService(
        api_key=GROQ_KEY,
        model="whisper-large-v3-turbo",
    )

    # ── LLM: DeepSeek via OpenRouter ─────────────────────────
    llm = OpenAILLMService(
        api_key=OPENROUTER_KEY,
        base_url="https://openrouter.ai/api/v1",
        model=OPENROUTER_MODEL,
    )

    # ── TTS: ElevenLabs streaming ────────────────────────────
    tts = ElevenLabsTTSService(
        api_key=ELEVENLABS_KEY,
        voice_id=ELEVENLABS_VOICE,
        model=ELEVENLABS_MODEL,
    )

    # ── Pipeline assembly ────────────────────────────────────
    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            llm,
            tts,
            transport.output(),
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            allow_interruptions=True,
            enable_metrics=True,
        ),
    )

    return task


# ── FastAPI Server ────────────────────────────────────────────────

async def run_server(dev_mode: bool = False):
    """Start the FastAPI server with Pipecat Twilio endpoint."""

    from fastapi import FastAPI, Request
    from fastapi.responses import HTMLResponse
    import uvicorn

    app = FastAPI(title="Hermes Voice Pipeline")

    @app.get("/", response_class=HTMLResponse)
    async def root():
        return """
        <html>
            <body><h1>Hermes Voice Pipeline</h1><p>Running.</p></body>
        </html>
        """

    @app.post("/twilio/ws")
    async def twilio_webhook(request: Request):
        """Twilio calls this when a call comes in. Upgrades to WebSocket."""

        # Optional: caller filtering
        if ALLOWED_CALLER:
            form = await request.form()
            caller = form.get("From", "")
            if caller != ALLOWED_CALLER:
                logger.warning(f"Rejected call from {caller}")
                return HTMLResponse(
                    content="""
                    <?xml version="1.0" encoding="UTF-8"?>
                    <Response><Reject reason="busy"/></Response>
                    """,
                    media_type="application/xml",
                    status_code=200,
                )

        # Return TwiML that bridges to WebSocket
        # Use Cloudflare Tunnel domain for production (voice.reneetoufee.com)
        host = os.getenv("PIPECAT_PUBLIC_HOST", "voice.reneetoufee.com")
        twiml = f"""
        <?xml version="1.0" encoding="UTF-8"?>
        <Response>
            <Connect>
                <Stream url="wss://{host}/twilio-media">
                    <Parameter name="caller" value="{ALLOWED_CALLER}" />
                </Stream>
            </Connect>
        </Response>
        """
        return HTMLResponse(content=twiml, media_type="application/xml")

    @app.websocket("/twilio-media")
    async def twilio_media(websocket):
        """Raw audio WebSocket from Twilio."""
        task = await build_pipeline()
        await task.run(websocket)

    logger.info(f"Starting Hermes Voice Pipeline on {HOST}:{PORT}")
    config = uvicorn.Config(app, host=HOST, port=PORT, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


# ── Entrypoint ────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Hermes Voice Pipeline")
    parser.add_argument("--dev", action="store_true", help="Development mode")
    args = parser.parse_args()

    if args.dev:
        logger.info("DEVELOPMENT MODE — verbose logging, use with ngrok")

    validate_config()

    try:
        asyncio.run(run_server(dev_mode=args.dev))
    except KeyboardInterrupt:
        logger.info("Shutting down.")
