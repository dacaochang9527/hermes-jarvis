# DeepSeek direct API notes

DeepSeek direct provider in Hermes uses the OpenAI-compatible Chat Completions endpoint (`https://api.deepseek.com/v1`).

## Vision / image input

As of the local verification on 2026-06-17, routing `auxiliary.vision` to `deepseek` / `deepseek-v4-pro` is not sufficient for Hermes image recognition. Hermes sends OpenAI-style multimodal content items with `type: "image_url"`; the DeepSeek endpoint response observed was:

`400 invalid_request_error: messages[0]: unknown variant image_url, expected text`

Interpretation:

- This is not a local PNG/JPEG file-format problem when the image file is valid and Hermes has successfully base64-encoded it.
- The endpoint/model path is accepting text messages but rejecting OpenAI-style image content items.
- Treat this as DeepSeek direct API / `deepseek-v4-pro` not supporting Hermes's current image-message format, or not supporting vision on that endpoint, unless DeepSeek publishes a different multimodal schema.

Recommended Hermes setup:

- Use DeepSeek direct for text auxiliary tasks like compression if desired.
- Use a known multimodal OpenAI-compatible provider/model for `auxiliary.vision`, for example the same custom provider that main chat uses if it supports `input: ["text", "image"]`.
- Verify after any change with a small local image containing known text/numbers and `vision_analyze`.
