# REED QR tools

A provider-neutral plugin a host application embeds. It depends only on REED QR,
uses its public APIs, and keeps provider credentials, media ownership, and scoring
outside the plugin.

Version 0.2 adds observable frame completions and optional model-facing encoding.

```python
from reed_qr_tools import QRTools

images = {"authorized-image": image_bytes}
async with QRTools(images.__getitem__) as qr:
    result = await qr.decode_image("authorized-image")
    generated = await qr.encode_text("Hello from REED QR")
    # Register qr.declaration() with your provider's tool interface, then route
    # actual tool calls to await qr.invoke(name, arguments).
```

The resolver must authorize every image reference. No arbitrary paths or URLs are
accepted. A toolset owns one decoder executor and must be closed. Cancelling a
caller waits for outstanding native work rather than abandoning decoder threads.
The benchmark host shows whether this package and the SDK were installed from
editable source or an immutable artifact; neither implies vendor endorsement.

Video hosts can call `await qr.decode_frame(frame, source_id="camera", generation=2)`.
The host authorizes sources and owns sampling, bounded queues, and generation
retirement. The operation returns a completion even when no QR is found.

To advertise encoding to a model, construct `QRTools(resolve_image,
publish_artifact=publish)` and register `qr.declarations()`. The publisher receives
an `EncodedQR` and returns an opaque, authorized artifact ID. Calls to
`qr.invoke("encode_qr_text", {"text": "Hello", "correction": "M", "scale": 8})`
return that ID and dimensions; PNG bytes remain in host-owned storage. The host
owns artifact lifetime and authorization. Without a publisher, encoding is not
advertised as a model tool and model encoding calls are rejected.
