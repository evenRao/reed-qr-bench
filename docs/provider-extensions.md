# Adding a benchmark provider

OpenAI and Gemini are built in. Other providers register through the installed
Python entry-point group `reed_bench.providers`. The host and each fresh worker
discover the same installed adapter. This is trusted application code, not a
facility for uploading arbitrary scripts through the browser.

Export a `ProviderSpec` instance from your installed package:

```python
from reed_bench.adapters import ProviderSpec

spec = ProviderSpec(
    name="my_provider",
    label="My provider",
    key_env="MY_PROVIDER_API_KEY",
    model_env="MY_PROVIDER_MODEL",
    factory=lambda session: MyAdapter(session),
    modes=("vision", "reed"),
)
```

```toml
[project.entry-points."reed_bench.providers"]
my_provider = "my_adapter:spec"
```

Implement `async run(resource, mode, model, tools, trace, *, forced=False)`.
Return `answer`, parsed `payloads`, provider-reported `model`, and numeric `usage`.
Use `trace.emit()` for observable stages (`first_model_output`, `tool_requested`,
`tool_result_available`, `model_response_completed`, `code_tool_observed`). Use
`ProviderError(category, safe_message)` for unsupported/configuration/quota errors.

For REED tool mode, supply `tools.declaration()`, accept only the current opaque
`resource.id`, call `tools.invoke()`, and return its structured result to the model.
Never supply evaluator labels or baseline outputs. Preserve provider continuation
requirements, such as reasoning signatures, and close owned remote artifacts.

The registry adds implementation choices, model inputs, and in-memory credentials
to the interface. A provider lacking hosted code tools should omit `code`; do not
fabricate a baseline. Add mocked wire-protocol, authorization, error, cancellation,
and actual-tool-call tests before collecting paid performance evidence.
