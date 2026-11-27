"""Exercise provider wire protocols without credentials, paid calls, or hidden answers."""

import asyncio
import json
from types import SimpleNamespace as NS

import pytest
from reed_qr_tools import QRTools

from reed_bench.evidence import Trace
from reed_bench.fixtures import build_fixture
from reed_bench.providers import Provider, ProviderError, sse


class Content:
    def __init__(self, events):
        self.data = b"".join(b"data: " + json.dumps(item).encode() + b"\r\n\r\n" for item in events)

    async def iter_any(self):
        # Deliberately split UTF-8, CRLF, and event boundaries across chunks.
        for i in range(0, len(self.data), 7):
            yield self.data[i : i + 7]

    async def read(self, size):
        return self.data[:size]


class Response:
    def __init__(self, events, status=200):
        self.content = Content(events)
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


def test_sse_handles_split_crlf_and_unicode():
    async def run():
        actual = [item async for item in sse(Response([{"text": "Hello ✓"}, {"done": True}]))]
        assert actual == [{"text": "Hello ✓"}, {"done": True}]

    asyncio.run(run())


@pytest.mark.parametrize("provider", ["openai", "gemini"])
def test_actual_tool_round_trip_and_provider_context_isolation(provider):
    fixture = build_fixture("clean", 127)
    resource = NS(id="opaque-authorized-input", data=fixture.data, mime="image/png")
    requests = []

    class Session:
        def post(self, url, *, json, **kwargs):
            requests.append(json)
            first = len(requests) == 1
            if first:
                # Ground truth is never supplied to the provider in clear text.
                assert fixture.expected[0] not in __import__("json").dumps(json)
            if provider == "openai":
                if first:
                    assert json["tools"][0]["name"] == "decode_qr_image"
                    assert json["tool_choice"]["name"] == "decode_qr_image"
                    return Response(
                        [
                            {
                                "type": "response.completed",
                                "response": {
                                    "output": [
                                        {
                                            "type": "function_call",
                                            "name": "decode_qr_image",
                                            "call_id": "call",
                                            "arguments": '{"image_id":"opaque-authorized-input"}',
                                        }
                                    ]
                                },
                            }
                        ]
                    )
                answer = __import__("json").dumps({"payloads": list(fixture.expected)})
                tool_output = __import__("json").loads(json["input"][-1]["output"])
                assert tool_output["detections"][0]["text"] == fixture.expected[0]
                assert "bytes_hex" not in tool_output["detections"][0]
                return Response(
                    [
                        {"type": "response.output_text.delta", "delta": answer},
                        {
                            "type": "response.completed",
                            "response": {
                                "output": [],
                                "model": "reported-model",
                                "usage": {"input_tokens": 7, "output_tokens": 5},
                            },
                        },
                    ]
                )
            if first:
                return Response(
                    [
                        {
                            "candidates": [
                                {
                                    "content": {
                                        "parts": [
                                            {
                                                "functionCall": {
                                                    "name": "decode_qr_image",
                                                    "args": {"image_id": resource.id},
                                                },
                                                "thoughtSignature": "opaque-signature",
                                            }
                                        ]
                                    }
                                }
                            ]
                        }
                    ]
                )
            assert json["contents"][-2]["parts"][0]["thoughtSignature"] == "opaque-signature"
            assert (
                json["contents"][-1]["parts"][0]["functionResponse"]["response"]["detections"][0][
                    "text"
                ]
                == fixture.expected[0]
            )
            return Response(
                [
                    {
                        "candidates": [
                            {
                                "content": {
                                    "parts": [
                                        {
                                            "text": __import__("json").dumps(
                                                {"payloads": list(fixture.expected)}
                                            )
                                        }
                                    ]
                                }
                            }
                        ],
                        "modelVersion": "reported-model",
                        "usageMetadata": {"promptTokenCount": 7, "candidatesTokenCount": 5},
                    }
                ]
            )

    async def run():
        trace = Trace()
        async with QRTools({resource.id: resource.data}.__getitem__, trace.emit) as tools:
            result = await Provider(provider, Session(), key="fixture-only").run(
                resource, "reed", "fixture-model", tools, trace, forced=True
            )
        assert result["payloads"] == list(fixture.expected)
        assert result["model"] == "reported-model"
        assert result["usage"]["input_tokens"] == 7
        assert trace.first("tool_requested") is not None
        assert trace.first("qr_operation_completed") is not None
        assert trace.first("first_model_output") is not None
        assert len(requests) == 2

    asyncio.run(run())


@pytest.mark.parametrize("provider", ["openai", "gemini"])
def test_vision_baseline_does_not_gain_access_to_plugin(provider):
    fixture = build_fixture("clean")
    resource = NS(id="opaque", data=fixture.data, mime="image/png")

    class Session:
        def post(self, url, *, json, **kwargs):
            assert "tools" not in json
            answer = '{"payloads":["wrong answer"]}'
            if provider == "openai":
                return Response(
                    [
                        {"type": "response.output_text.delta", "delta": answer},
                        {"type": "response.completed", "response": {"output": []}},
                    ]
                )
            return Response([{"candidates": [{"content": {"parts": [{"text": answer}]}}]}])

    async def run():
        trace = Trace()
        async with QRTools(lambda identifier: pytest.fail("baseline accessed QR tool")) as tools:
            result = await Provider(provider, Session(), key="fixture").run(
                resource, "vision", "fixture-model", tools, trace
            )
        assert result["payloads"] == ["wrong answer"]
        assert trace.first("tool_requested") is None

    asyncio.run(run())


def test_rejected_credentials_are_sanitized():
    class Session:
        def post(self, *args, **kwargs):
            return Response([{"secret": "must-not-be-returned"}], status=401)

    async def run():
        async with QRTools(lambda identifier: b"image") as tools:
            with pytest.raises(ProviderError) as error:
                await Provider("openai", Session(), key="credential-value").run(
                    NS(id="opaque", data=b"image", mime="image/png"),
                    "vision",
                    "model",
                    tools,
                    Trace(),
                )
        assert error.value.category == "configuration_error"
        assert "credential-value" not in str(error.value)
        assert "must-not-be-returned" not in str(error.value)

    asyncio.run(run())


@pytest.mark.parametrize("provider", ["openai", "gemini"])
def test_hosted_code_baseline_is_observed_and_owned_uploads_are_cleaned(provider):
    deleted = []
    answer = '{"payloads":["provider-decoded-value"]}'

    class Uploaded(Response):
        async def json(self):
            return {"id": "file-owned-fixture"}

    class Session:
        def post(self, url, *, json=None, data=None, **kwargs):
            if url.endswith("/files"):
                assert data is not None
                return Uploaded([])
            if provider == "openai":
                assert json["tools"] == [
                    {
                        "type": "code_interpreter",
                        "container": {"type": "auto", "file_ids": ["file-owned-fixture"]},
                    }
                ]
                return Response(
                    [
                        {"type": "response.code_interpreter_call.in_progress"},
                        {"type": "response.output_text.delta", "delta": answer},
                        {
                            "type": "response.completed",
                            "response": {
                                "output": [
                                    {
                                        "type": "code_interpreter_call",
                                        "container_id": "container-owned-fixture",
                                    }
                                ]
                            },
                        },
                    ]
                )
            assert json["tools"] == [{"codeExecution": {}}]
            return Response(
                [
                    {
                        "candidates": [
                            {
                                "content": {
                                    "parts": [
                                        {
                                            "executableCode": {
                                                "language": "PYTHON",
                                                "code": "print('fixture')",
                                            }
                                        },
                                        {
                                            "codeExecutionResult": {
                                                "outcome": "OUTCOME_OK",
                                                "output": "fixture",
                                            }
                                        },
                                        {"text": answer},
                                    ]
                                }
                            }
                        ]
                    }
                ]
            )

        def delete(self, url, **kwargs):
            deleted.append(url)
            return Response([])

    async def run():
        trace = Trace()
        async with QRTools(
            lambda identifier: pytest.fail("Code baseline accessed REED QR")
        ) as tools:
            result = await Provider(provider, Session(), key="fixture-key").run(
                NS(id="opaque", data=b"fixture", mime="image/png"), "code", "model", tools, trace
            )
        assert result["payloads"] == ["provider-decoded-value"]
        assert trace.first("code_tool_observed") is not None
        assert trace.first("tool_requested") is None
        if provider == "openai":
            assert any(url.endswith("/files/file-owned-fixture") for url in deleted)
            assert any(url.endswith("/containers/container-owned-fixture") for url in deleted)
        else:
            assert deleted == []

    asyncio.run(run())
