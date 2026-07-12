from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_docker_ollama_profile_uses_tradingagents_env_name():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    lines = [line.strip() for line in compose.splitlines()]

    assert "TRADINGAGENTS_LLM_PROVIDER=ollama" in compose
    assert "- LLM_PROVIDER=ollama" not in lines


def test_env_example_documents_ollama_operating_profile():
    example = (ROOT / ".env.example").read_text(encoding="utf-8")

    for name in (
        "tradingagents-qwen3-30b-a3b-instruct-2507-q4-4k",
        "TRADINGAGENTS_OLLAMA_TEMPERATURE",
        "TRADINGAGENTS_OLLAMA_MAX_COMPLETION_TOKENS",
        "TRADINGAGENTS_OLLAMA_TOP_P",
        "TRADINGAGENTS_OLLAMA_PRESENCE_PENALTY",
        "TRADINGAGENTS_OLLAMA_EXTRA_BODY_JSON",
        "TRADINGAGENTS_LLM_TIMEOUT_SECONDS",
        "TRADINGAGENTS_LLM_MAX_RETRIES",
        "TRADINGAGENTS_LLM_MAX_OUTPUT_TOKENS",
    ):
        assert name in example


def test_readme_recommends_eval_selected_qwen3_instruct_for_local_ollama():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "hf.co/unsloth/Qwen3-30B-A3B-Instruct-2507-GGUF:Q4_K_M" in readme
    assert "tradingagents-qwen3-30b-a3b-instruct-2507-q4-4k" in readme
    assert "hf.co/Qwen/Qwen3-32B-GGUF:Q6_K" not in readme
    assert "hf.co/Qwen/Qwen3-30B-A3B-GGUF:Q4_K_M" not in readme
