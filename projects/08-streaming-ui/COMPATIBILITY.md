# P08 compatibility decisions

Verified against installed packages on **2026-09-29**. Exact transitive versions and integrity
hashes live in `apps/copilot/package-lock.json`; Python dependencies use the root `uv.lock`.

| Component | Pinned version |
|---|---|
| Next.js | 16.3.6 |
| React / React DOM | 19.3.0 |
| Vercel AI SDK (`ai`) | 7.0.122 |
| AI SDK React (`@ai-sdk/react`) | 4.0.125 |
| TypeScript | 7.0.2 |
| Playwright | 1.63.0 |
| Packaged Chromium | `@sparticuz/chromium` 153.0.0; executable reported Chromium 153.0.8010.0 |

The official [stream protocol documentation](https://ai-sdk.dev/docs/ai-sdk-ui/stream-protocol)
defines a v1 UI message stream over SSE and the `x-vercel-ai-ui-message-stream: v1` header.
The backend emits the documented start/delta/end text blocks and custom `data-citations`.
`[DONE]` closes the stream. `useChat` consumes it through `DefaultChatTransport`; a successful
TypeScript build and real-browser tests verify this contract against the pinned installation.

The [useChat reference](https://ai-sdk.dev/docs/reference/ai-sdk-ui/use-chat) and
[transport guide](https://ai-sdk.dev/docs/ai-sdk-ui/transport) informed the hook and request
adapter. Only the last user's question, stable user message ID, and conversation ID are sent
to Python. Server-side authentication supplies the principal. The
[message persistence guide](https://ai-sdk.dev/docs/ai-sdk-ui/chatbot-message-persistence)
informed stable server IDs and history reconciliation; SQLite remains authoritative here.

The [Next rewrite reference](https://nextjs.org/docs/app/api-reference/config/next-config-js/rewrites)
supports the same-origin proxy. Actual browser tests found that compression delayed our
small stream frames. `compress: false` and preservation of `no-transform` now allow partial
display and cancellation through the proxy. This trades static-asset compression at this
local Next process for predictable stream delivery; a deployment can separately compress
static assets while explicitly bypassing SSE responses.

The [Sparticuz README](https://github.com/Sparticuz/chromium/blob/master/README.md) documents
the packaged headless Chromium and Playwright integration. The ordinary Playwright CDN
returned a small HTML availability page in this environment. The pinned npm package
provided actual browser bytes. Its default tar extraction attempted unsupported ownership
metadata, so `scripts/prepare-browser.mjs` uses current-user ownership for the trusted
package archives. [Playwright's browser options](https://playwright.dev/docs/api/class-browsertype)
document a custom executable; compatibility is verified by the actual suite rather than
assumed from the package name. No third-party network proxy or approval bypass was used.
