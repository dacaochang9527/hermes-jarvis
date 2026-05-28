# Hermes vision auxiliary provider: custom OpenAI-compatible endpoint

Session learning: OpenClaw and Hermes can both use the same OpenAI-compatible multimodal model, but Hermes `auxiliary.vision.provider: main` may fail to inherit the main model endpoint/key for custom providers.

Observed symptoms:

- Main chat works with `model.provider: sub2api` and `model.default: gpt-5.5`.
- Vision fails with logs like:
  - `resolve_provider_client: custom/main requested but no endpoint credentials found`
  - `Vision provider main unavailable, falling back to auto vision backends`
  - `No LLM provider configured for task=vision provider=main`
- Fallback `auto` then tries OpenRouter/Nous/other API-key backends and may report unrelated-looking missing key, invalid key, payment, or credit errors.

Useful comparison source:

- If OpenClaw on the same machine can read images, inspect `~/.openclaw/openclaw.json` and compare its `models.providers.<provider>` block.
- The durable fields to mirror into Hermes are:
  - provider name, e.g. `sub2api`
  - `baseUrl` / `base_url`
  - API key or env var
  - model id, e.g. `gpt-5.5`
  - evidence that the model supports image input, e.g. `input: ["text", "image"]` in OpenClaw.

Hermes fix pattern:

```yaml
model:
  default: gpt-5.5
  provider: sub2api
  base_url: http://example/v1
  api_mode: chat_completions

providers:
  sub2api:
    name: sub2api
    base_url: http://example/v1
    key_env: SUB2API_API_KEY
    api_mode: chat_completions
    default_model: gpt-5.5

auxiliary:
  vision:
    provider: sub2api
    model: gpt-5.5
    base_url: http://example/v1
    api_key: "..."        # most robust for current auxiliary resolver
    api_key_env: SUB2API_API_KEY
    timeout: 120
```

Notes:

- In the current resolver path, `auxiliary.vision.api_key_env` alone may not be enough when `auxiliary.vision.base_url` is present, because `_resolve_task_provider_model()` reads `api_key` but not `api_key_env` for the per-task override. If direct verification still fails, copy the actual key from `.env` into `auxiliary.vision.api_key` or patch Hermes to resolve `api_key_env` for auxiliary tasks.
- Avoid concluding that the model lacks image support when a sibling client (OpenClaw) proves it does. Treat it as provider-routing/config first.
- Verify with a generated local test image containing known text/numbers and a one-shot Hermes call using the vision toolset. Success means the returned text/numbers match the image approximately.

Verification example:

```bash
# create a simple image with text using any available local method, then:
hermes chat -Q -t vision -q "请使用 vision_analyze 工具读取这张图片，并告诉我图片里的文字和数字：/tmp/hermes_vision_test.png"
```
