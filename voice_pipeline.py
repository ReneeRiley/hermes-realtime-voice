#!/usr/bin/env python3
"""
voice_pipeline.py — Hermes Realtime Voice Pipeline (Phase 1 Prototype)

Pipecat 1.3.0 pipeline: Groq LLM → ElevenLabs streaming TTS.
Text-in, voice-out for now. Audio-in via WebSocket once hardware arrives.

Usage:
    python voice_pipeline.py          # Interactive CLI mode
    python voice_pipeline.py --server  # Start FastAPI WebSocket server
"""

import asyncio
import os
import sys
from typing import Optional

from dotenv import load_dotenv
load_dotenv(os.path.expanduser("~/.hermes/.env"))

from loguru import logger

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.services.groq.llm import GroqLLMService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketTransport,
    FastAPIWebsocketParams,
)

# ── Configuration ──────────────────────────────────────────────

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")

GROQ_MODEL = "llama-3.1-8b-instant"  # 310ms TTFT measured
ELEVENLABS_VOICE = "21m00Tcm4TlvDq8ikWAM"  # Rachel
ELEVENLABS_MODEL = "eleven_flash_v2_5"  # Fastest model

SYSTEM_PROMPT = """You are Hermes, a real-time voice assistant. 

Key rules:
- Keep responses CONCISE — 1-3 sentences max for voice.
- Be warm and conversational, not robotic.
- Never use markdown, bullet points, or formatting — it's spoken aloud.
- If you don't know something, say so briefly.
- Match the user's energy and tone."""


# ── WebSocket Server Mode ──────────────────────────────────────

async def run_websocket_server(
    host: str = "0.0.0.0",
    port: int = 8888,
):
    """Start a FastAPI WebSocket server for browser-based voice chat."""

    transport = FastAPIWebsocketTransport(
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            camera_out_enabled=False,
            vad_enabled=True,
            vad_analyzer=None,  # Uses Silero by default
            vad_audio_passthrough=True,
        )
    )

    # LLM service
    llm = GroqLLMService(
        api_key=GROQ_API_KEY,
        model=GROQ_MODEL,
    )

    # Streaming TTS
    tts = ElevenLabsTTSService(
        api_key=ELEVENLABS_API_KEY,
        voice_id=ELEVENLABS_VOICE,
        model=ELEVENLABS_MODEL,
    )

    # Build context with system prompt
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
    ]
    context = OpenAILLMContext(messages)
    context_aggregator = llm.create_context_aggregator(context)

    # Assemble pipeline
    pipeline = Pipeline(
        [
            transport.input(),
            context_aggregator.user(),
            llm,
            tts,
            transport.output(),
            context_aggregator.assistant(),
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            allow_interruptions=True,
            enable_metrics=True,
        ),
    )

    runner = PipelineRunner()

    logger.info(f"🎤 Voice pipeline starting on ws://{host}:{port}")
    await runner.run(task)


# ── CLI Test Mode ────────────────────────────────────────────

async def run_cli_test():
    """Simple text→voice test without audio input hardware."""

    if not GROQ_API_KEY or not ELEVENLABS_API_KEY:
        logger.error("Missing API keys. Check ~/.hermes/.env")
        return

    # LLM
    llm = GroqLLMService(
        api_key=GROQ_API_KEY,
        model=GROQ_MODEL,
    )

    # TTS
    tts = ElevenLabsTTSService(
        api_key=ELEVENLABS_API_KEY,
        voice_id=ELEVENLABS_VOICE,
        model=ELEVENLABS_MODEL,
    )

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    context = OpenAILLMContext(messages)

    print("\n🎤 Hermes Voice CLI — type 'quit' to exit\n")

    while True:
        user_input = input("You: ").strip()
        if user_input.lower() in ("quit", "exit", "q"):
            break
        if not user_input:
            continue

        # Get LLM response
        context.add_message({"role": "user", "content": user_input})
        
        print("Hermes: ", end="", flush=True)
        
        llm_start = asyncio.get_event_loop().time()
        response_text = ""
        async for chunk in llm.process_frame_async(context):
            if hasattr(chunk, "text"):
                response_text += chunk.text
                print(chunk.text, end="", flush=True)
        llm_time = asyncio.get_event_loop().time() - llm_start
        
        print(f"\n  [LLM: {llm_time*1000:.0f}ms]")

        # Generate speech
        t0 = asyncio.get_event_loop().time()
        audio_file = "/tmp/hermes_voice_output.mp3"
        await tts.say(response_text, output_path=audio_file)
        tts_time = asyncio.get_event_loop().time() - t0
        
        print(f"  [TTS: {tts_time*1000:.0f}ms, saved to {audio_file}]")
        print()


# ── Entry Point ────────────────────────────────────────────────

if __name__ == "__main__":
    if "--server" in sys.argv:
        port = int(os.getenv("VOICE_PORT", "8888"))
        asyncio.run(run_websocket_server(port=port))
    else:
        asyncio.run(run_cli_test())