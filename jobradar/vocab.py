"""Technology vocabulary used to find what a posting asks for.

A posting's demands are only knowable through a fixed vocabulary: anything
not listed here is invisible to gap detection, which is the safe direction
to fail in (a missed gap costs a slightly over-optimistic score; a phantom
gap would push a good job down). Add terms as they show up.
"""

from __future__ import annotations

import re

from .text import term_regex

# canonical -> extra aliases (case-insensitive, word-bounded)
TECH: dict[str, list[str]] = {
    "Python": [], "TypeScript": [], "JavaScript": [], "Golang": ["go lang"], "Rust": [], "Java": [],
    "Kotlin": [], "Scala": [], "C++": [], "C#": [], "Ruby": [], "Ruby on Rails": ["rails"], "PHP": [],
    "Elixir": [], "Swift": [], "SQL": [], "React": ["react.js", "reactjs"], "Next.js": ["nextjs"],
    "Vue": ["vue.js"], "Angular": [], "Svelte": [], "Node.js": ["nodejs", "node"], "Django": [],
    "Flask": [], "FastAPI": [], "Spring": ["spring boot"], ".NET": ["dotnet"], "GraphQL": [], "gRPC": [],
    "REST APIs": ["rest api", "restful"], "PostgreSQL": ["postgres"], "MySQL": [], "MongoDB": [],
    "Redis": [], "Elasticsearch": ["opensearch"], "Kafka": [], "Spark": ["pyspark"], "Airflow": [],
    "dbt": [], "Snowflake": [], "BigQuery": [], "Databricks": [], "AWS": ["amazon web services"],
    "GCP": ["google cloud"], "Azure": [], "Kubernetes": ["k8s"], "Docker": ["containers"],
    "Terraform": [], "Linux": [], "CI/CD": ["github actions"], "PyTorch": [], "TensorFlow": [],
    "JAX": [], "scikit-learn": ["sklearn"], "pandas": [], "NumPy": [], "Hugging Face": ["huggingface", "transformers"],
    "LangChain": [], "LangGraph": [], "LlamaIndex": [], "OpenAI API": ["openai"], "Anthropic Claude": ["anthropic", "claude"],
    "Gemini": [], "LLMs": ["llm", "large language model", "large language models"], "RAG": ["retrieval-augmented", "retrieval augmented"],
    "Vector databases": ["vector database", "vector db", "pinecone", "weaviate", "qdrant", "milvus", "chroma", "faiss", "pgvector"],
    "Embeddings": ["embedding"], "Fine-tuning": ["fine tuning", "finetuning", "lora", "sft"], "RLHF": ["reinforcement learning from human feedback"],
    "Evaluation": ["evals", "llm evaluation", "evaluation framework", "benchmarking"], "MCP": ["model context protocol"],
    "AI agents": ["agentic", "agents", "tool calling", "function calling", "tool use"], "Prompt engineering": ["prompting"],
    "Computer vision": ["opencv"], "NLP": ["natural language processing"], "MLOps": ["model deployment", "model serving"],
    "SageMaker": [], "Vertex AI": [], "Ray": [], "CUDA": [], "WebGL": ["glsl", "shaders"], "Three.js": ["threejs", "react three fiber"],
    "Tailwind": ["tailwindcss"], "Microservices": [], "Distributed systems": [], "Unity": [], "Solidity": [],
    "Salesforce": [], "Figma": [], "Playwright": [], "Selenium": [], "Pytest": [], "WordPress": [],
    "Streamlit": [], "Pydantic": [], "SQLite": [], "Webhooks": ["webhook"], "Stripe": [], "Supabase": [],
    "Firebase": [], "Vercel": [], "Cloudflare": [], "Observability": ["opentelemetry", "datadog", "grafana", "prometheus"],
    "Speech / voice AI": ["speech-to-text", "text-to-speech", "tts", "asr", "voice ai", "webrtc"],
}

_PATTERNS: list[tuple[str, list[re.Pattern]]] = [
    (canon, [term_regex(t) for t in [canon, *aliases]]) for canon, aliases in TECH.items()
]
# "Go" is too common an English word to match case-insensitively.
_GO = re.compile(r"(?<![A-Za-z])Go(?=[ ,/).;]|$)(?! (to|ahead|live|beyond|further|through))")


def tech_in(text: str) -> set[str]:
    found = {canon for canon, pats in _PATTERNS if any(p.search(text) for p in pats)}
    if "Golang" not in found and _GO.search(text or ""):
        found.add("Golang")
    return found
