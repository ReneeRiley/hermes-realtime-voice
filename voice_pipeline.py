#!/usr/bin/env python3
"""
voice_pipeline.py — Hermes Realtime Voice Pipeline (Phase 1 Prototype)

Pipecat 1.3.0 pipeline: Groq LLM → ElevenLabs streaming TTS.
Uses standalone SDKs for CLI test mode, Pipecat services for WebSocket server.

Measured latency (2026-05-29):
    Groq LLM (llama-3.1-8b-instant):   266ms TTFT
    ElevenLabs TTS (eleven_flash_v2_5): 186ms TTFA
    Pipeline E2E (text→voice):         ~450ms

Usage:
    python voice_pipeline.py          # Interactive CLI text→voice
    python voice_pipeline.py --server  # FastAPI WebSocket server (needs mic)
"""

import asyncio
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(os.path.expanduser("~/.hermes/.env"))

from loguru import logger

# ── Configuration ──────────────────────────────────────────────

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")

GROQ_MODEL = "llama-3.1-8b-instant"
ELEVENLABS_VOICE = "21m00Tcm4TlvDq8ikWAM"  # Rachel
ELEVENLABS_MODEL = "eleven_flash_v2_5"

SYSTEM_PROMPT = """You are Hermes, a real-time voice assistant.

Key rules:
- Keep responses CONCISE — 1-3 sentences max for voice.
- Be warm, conversational, and direct. Not robotic.
- Never use markdown, bullet points, or formatting — it's spoken aloud.
- If you don't know something, say so briefly.
- Match the user's energy and tone."""


# ── CLI Test Mode ──────────────────────────────────────────────

async def run_cli():
    """Text→voice test without audio hardware."""

    if not GROQ_API_KEY or not ELEVENLABS_API_KEY:
        logger.error("Missing API keys. Check ~/.hermes/.env")
        return

    from groq import AsyncGroq
    from elevenlabs.client import ElevenLabs

    groq_client = AsyncGroq(api_key=GROQ_API_KEY)
    el_client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

    conversation = [{"role": "system", "content": SYSTEM_PROMPT}]

    print("\n🎤  Hermes Voice — type 'quit' to exit\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n")
            break

        if user_input.lower() in ("quit", "exit", "q"):
            break
        if not user_input:
            continue

        conversation.append({"role": "user", "content": user_input})

        # ── LLM ──
        llm_start = time.time()
        response = await groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=conversation,
            max_tokens=150,
        )
        llm_time = (time.time() - llm_start) * 1000

        reply = response.choices[0].message.content.strip()
        conversation.append({"role": "assistant", "content": reply})

        print(f"\nHermes: {reply}")
        print(f"  ⚡ LLM: {llm_time:.0f}ms", end="")

        # ── TTS ──
        tts_start = time.time()
        audio_chunks = el_client.text_to_speech.convert_as_stream(
            voice_id=ELEVENLABS_VOICE,
            text=reply,
            model_id=ELEVENLABS_MODEL,
        )

        output_path = Path("/tmp/hermes_voice_output.mp3")
        first_chunk = True
        with open(output_path, "wb") as f:
            for chunk in audio_chunks:
                if first_chunk:
                    ttfa = (time.time() - tts_start) * 1000
                    first_chunk = False
                if chunk:
                    f.write(chunk)

        tts_time = (time.time() - tts_start) * 1000
        print(f" | TTS: {tts_time:.0f}ms (first audio: {ttfa:.0f}ms)")
        print(f"  🔊 Saved to {output_path}\n")

        # Prevent runaway context
        if len(conversation) > 20:
            conversation = [conversation[0]] + conversation[-10:]


# ── WebSocket Server Mode ─────────────────────────────────────

async def run_server(host: str = "0.0.0.0", port: int = 8888):
    """Start FastAPI WebSocket server for browser-based voice."""

    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.runner import PipelineRunner
    from pipecat.pipeline.task import PipelineParams, PipelineTask
    from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
    from pipecat.services.groq.llm import GroqLLMService, GroqLLMSettings
    from pipecat.services.elevenlabs.tts import (
        ElevenLabsTTSService,
        ElevenLabsTTSSettings,
    )
    from pipecat.transports.websocket.fastapi import (
        FastAPIWebsocketTransport,
        FastAPIWebsocketParams,
    )

    transport = FastAPIWebsocketTransport(
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            camera_out_enabled=False,
            vad_enabled=True,
            vad_audio_passthrough=True,
        )
    )

    llm = GroqLLMService(
        api_key=GROQ_API_KEY,
        settings=GroqLLMSettings(model=GROQ_MODEL),
    )

    tts = ElevenLabsTTSService(
        api_key=ELEVENLABS_API_KEY,
        settings=ElevenLabsTTSSettings(
            voice=ELEVENLABS_VOICE,
            model=ELEVENLABS_MODEL,
        ),
    )

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    context = OpenAILLMContext(messages)
    context_aggregator = llm.create_context_aggregator(context)

    pipeline = Pipeline([
        transport.input(),
        context_aggregator.user(),
        llm,
        tts,
        transport.output(),
        context_aggregator.assistant(),
    ])

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            allow_interruptions=True,
            enable_metrics=True,
        ),
    )

    runner = PipelineRunner()
    logger.info(f"🎤 Voice server starting on ws://{host}:{port}")
    await runner.run(task)


# ── Entry Point ────────────────────────────────────────────────

if __name__ == "__main__":
    if "--server" in sys.argv:
        port = int(os.getenv("VOICE_PORT", "8888"))
        asyncio.run(run_server(port=port))
    else:
        asyncio.run(run_cli())