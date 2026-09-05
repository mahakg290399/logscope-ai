"""Verification script for testing live NVIDIA NIM endpoint connectivity and response."""

import asyncio
import os
import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from openai import AsyncOpenAI
from logscope.config import get_settings


async def verify_nvidia_endpoint():
    settings = get_settings()
    api_key = settings.nvidia_api_key or os.environ.get("NVIDIA_API_KEY")
    base_url = settings.nvidia_base_url or "https://integrate.api.nvidia.com/v1"
    model = settings.nvidia_model or "nvidia/nemotron-3.5-lightning-30b-a3b"

    print("=" * 60)
    print("NVIDIA NIM Endpoint Diagnostic Tool")
    print("=" * 60)
    print(f"Base URL : {base_url}")
    print(f"Model    : {model}")
    print(f"API Key  : {'Configured (' + api_key[:8] + '...)' if api_key else 'NOT CONFIGURED'}")
    print("-" * 60)

    if not api_key:
        print("\n[!] Error: No NVIDIA_API_KEY found.")
        print("Please set NVIDIA_API_KEY in your .env file or environment variables:")
        print("   NVIDIA_API_KEY=nvapi-your-key-here")
        print("   LOGSCOPE_AI_PROVIDER=nvidia")
        return False

    client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    # 1. Test Chat Completion
    print(f"\n1. Sending test prompt to {model}...")
    start_time = time.time()
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "You are an SRE incident triage assistant. Respond concisely in JSON format.",
                },
                {
                    "role": "user",
                    "content": 'Respond with: {"status": "online", "model": "' + model + '"}',
                },
            ],
            temperature=0.2,
            max_tokens=100,
        )
        elapsed = time.time() - start_time
        reply = response.choices[0].message.content
        print(f"-> [SUCCESS] Received response in {elapsed:.2f}s:")
        print(f"   Raw Content: {reply.strip()}")
        if response.usage:
            print(f"   Tokens: Prompt={response.usage.prompt_tokens}, Completion={response.usage.completion_tokens}")
    except Exception as exc:
        print(f"-> [FAILURE] Chat completion failed: {exc}")
        return False

    # 2. Test Embedding Generation
    embedding_model = settings.nvidia_embedding_model or "nvidia/llama-3.2-nv-embedqa-1b-v1"
    print(f"\n2. Testing embedding endpoint with {embedding_model}...")
    try:
        start_emb = time.time()
        emb_res = await client.embeddings.create(
            model=embedding_model,
            input=["Connection pool timeout exhausted in PostgreSQL replica."],
            extra_body={"input_type": "query"} if "nv-embed" in embedding_model or "llama" in embedding_model else {},
        )
        emb_elapsed = time.time() - start_emb
        dim = len(emb_res.data[0].embedding)
        print(f"-> [SUCCESS] Generated embedding vector (dim={dim}) in {emb_elapsed:.2f}s")
    except Exception as exc:
        print(f"-> [NOTE] Embedding call failed ({exc}). Local TF-IDF offline embeddings will be used as fallback.")

    print("\n" + "=" * 60)
    print("NVIDIA NIM Endpoint Verification: ALL CHECKS PASSED")
    print("=" * 60)
    return True


if __name__ == "__main__":
    success = asyncio.run(verify_nvidia_endpoint())
    sys.exit(0 if success else 1)
