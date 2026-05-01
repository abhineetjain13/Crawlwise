import os
import time
from pathlib import Path

import boto3
from flask import Flask, Response, jsonify, request

app = Flask(__name__)


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip().strip('"').strip("'")
        os.environ[key] = value


def _bootstrap_env() -> None:
    root = Path(__file__).resolve().parent
    _load_env_file(root / ".env")
    _load_env_file(root / "backend" / ".env")


_bootstrap_env()

DEFAULT_MODEL_ID = os.environ.get(
    "BEDROCK_MODEL_ID",
    "global.anthropic.claude-opus-4-7",
)

MODEL_ALIASES = {
    "claude-4.7": DEFAULT_MODEL_ID,
    "claude 4.7": DEFAULT_MODEL_ID,
    "claude-opus-4-7": DEFAULT_MODEL_ID,
    "anthropic.claude-opus-4-7": DEFAULT_MODEL_ID,
    "us.anthropic.claude-opus-4-7": "us.anthropic.claude-opus-4-7",
    "global.anthropic.claude-opus-4-7": "global.anthropic.claude-opus-4-7",
}

EXPOSED_MODELS = [
    {
        "id": "zai.glm-5",
        "object": "model",
        "owned_by": "amazon-bedrock",
    },
    {
        "id": "moonshotai.kimi-k2.5",
        "object": "model",
        "owned_by": "amazon-bedrock",
    },
    {
        "id": "amazon.nova-lite-v1:0",
        "object": "model",
        "owned_by": "amazon-bedrock",
    },
    {
        "id": "global.anthropic.claude-opus-4-7",
        "object": "model",
        "owned_by": "amazon-bedrock",
    },
]


def _build_bedrock_client():
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
    api_key = os.environ.get("BEDROCK_API_KEY") or os.environ.get(
        "AWS_BEARER_TOKEN_BEDROCK"
    )
    if api_key:
        # Boto3 Bedrock runtime supports bearer token auth through this env var.
        os.environ["AWS_BEARER_TOKEN_BEDROCK"] = api_key

    client_kwargs = {
        "service_name": "bedrock-runtime",
        "region_name": region,
    }
    if not api_key and os.environ.get("AWS_ACCESS_KEY_ID"):
        client_kwargs["aws_access_key_id"] = os.environ["AWS_ACCESS_KEY_ID"]
    if not api_key and os.environ.get("AWS_SECRET_ACCESS_KEY"):
        client_kwargs["aws_secret_access_key"] = os.environ["AWS_SECRET_ACCESS_KEY"]
    if not api_key and os.environ.get("AWS_SESSION_TOKEN"):
        client_kwargs["aws_session_token"] = os.environ["AWS_SESSION_TOKEN"]
    return boto3.client(**client_kwargs)


def _get_bedrock_client():
    return _build_bedrock_client()


def _to_bedrock_messages(messages):
    bedrock_messages = []
    for msg in messages or []:
        role = str(msg.get("role") or "").strip().lower()
        if role not in {"user", "assistant"}:
            continue
        content = msg.get("content", "")
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text = str(item.get("text") or "").strip()
                    if text:
                        parts.append({"text": text})
            if parts:
                bedrock_messages.append({"role": role, "content": parts})
            continue
        text = str(content or "").strip()
        if text:
            bedrock_messages.append({"role": role, "content": [{"text": text}]})
    return bedrock_messages


def _supports_temperature(model_id: str) -> bool:
    normalized = str(model_id or "").strip().lower()
    return "claude-opus-4-7" not in normalized


def _resolve_model_id(requested_model: str | None) -> str:
    normalized = str(requested_model or "").strip()
    if not normalized:
        return DEFAULT_MODEL_ID
    return MODEL_ALIASES.get(normalized.lower(), normalized)


def _chunk_text(text: str, size: int = 64):
    normalized = str(text or "")
    if not normalized:
        return
    for idx in range(0, len(normalized), size):
        yield normalized[idx : idx + size]


def _stream_chat_response(*, completion_id: str, model_id: str, output: str):
    def _event(payload: dict) -> str:
        import json

        return f"data: {json.dumps(payload)}\n\n"

    yield _event(
        {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model_id,
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant"},
                    "finish_reason": None,
                }
            ],
        }
    )
    for piece in _chunk_text(output):
        yield _event(
            {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model_id,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": piece},
                        "finish_reason": None,
                    }
                ],
            }
        )
    yield _event(
        {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model_id,
            "choices": [
                {
                    "index": 0,
                    "delta": {},
                    "finish_reason": "stop",
                }
            ],
        }
    )
    yield "data: [DONE]\n\n"

@app.route('/v1/chat/completions', methods=['POST'])
def chat_completions():
    """OpenAI-compatible chat completions endpoint"""
    try:
        data = request.json or {}
        if not isinstance(data, dict):
            return jsonify({'error': 'Request body must be a JSON object'}), 400

        # Extract messages
        messages = data.get('messages', [])
        if not messages:
            return jsonify({'error': 'No messages provided'}), 400

        bedrock_messages = _to_bedrock_messages(messages)
        if not bedrock_messages:
            return jsonify({'error': 'No supported text messages found'}), 400

        model_id = _resolve_model_id(data.get('model'))

        # Call Bedrock
        inference_config = {
            'maxTokens': int(data.get('max_tokens') or 4096),
        }
        if (
            data.get('temperature') not in (None, "")
            and _supports_temperature(model_id)
        ):
            inference_config['temperature'] = float(data['temperature'])

        response = _get_bedrock_client().converse(
            modelId=model_id,
            messages=bedrock_messages,
            inferenceConfig=inference_config,
        )

        # Extract response text
        output_parts = response['output']['message']['content']
        output = "".join(
            part.get('text', '')
            for part in output_parts
            if isinstance(part, dict)
        )

        completion_id = 'bedrock-' + str(
            response.get('ResponseMetadata', {}).get('RequestId', '')
        )

        if bool(data.get("stream")):
            return Response(
                _stream_chat_response(
                    completion_id=completion_id,
                    model_id=model_id,
                    output=output,
                ),
                mimetype='text/event-stream',
                headers={
                    'Cache-Control': 'no-cache',
                    'Connection': 'keep-alive',
                    'X-Accel-Buffering': 'no',
                },
            )

        # Return OpenAI-compatible response
        return jsonify({
            'id': completion_id,
            'choices': [{
                'index': 0,
                'message': {
                    'role': 'assistant',
                    'content': output
                },
                'finish_reason': 'stop'
            }],
            'created': int(time.time()),
            'object': 'chat.completion',
            'model': model_id,
            'usage': {
                'prompt_tokens': response['usage'].get('inputTokens', 0),
                'completion_tokens': response['usage'].get('outputTokens', 0),
                'total_tokens': response['usage'].get('totalTokens', 0),
            }
        })

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        error_text = str(e)
        if "Could not load credentials from any providers" in error_text:
            error_text = (
                "Bedrock credentials missing. Set BEDROCK_API_KEY or AWS_BEARER_TOKEN_BEDROCK "
                "or standard AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY env vars."
            )
        elif "with on-demand throughput isn’t supported" in error_text:
            error_text = (
                "This Claude model needs a Bedrock inference profile id, not the raw model id. "
                f"Use one of: {DEFAULT_MODEL_ID}, us.anthropic.claude-opus-4-7, or global.anthropic.claude-opus-4-7."
            )
        return jsonify({'error': error_text}), 500

@app.route('/v1/models', methods=['GET'])
def list_models():
    """OpenAI-compatible models list endpoint"""
    return jsonify({
        'object': 'list',
        'data': EXPOSED_MODELS,
    })

@app.route('/health', methods=['GET'])
def health():
if __name__ == '__main__':
    print("Starting Bedrock proxy on port 4000...")
    print("OpenAI-compatible endpoint: http://localhost:4000/v1/chat/completions")
    print(f"Model: {DEFAULT_MODEL_ID}")
    debug = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true")
    app.run(host='0.0.0.0', port=4000, debug=debug)
    print(f"Model: {DEFAULT_MODEL_ID}")
    app.run(host='0.0.0.0', port=4000, debug=True)
