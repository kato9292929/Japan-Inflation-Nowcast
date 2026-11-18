// /mcp — JIN の MCP サーバ（Streamable HTTP・セッションなし・JSON 応答）。無料・読み取り専用。
// サーバレスでインスタンス間の状態を持たないよう、リクエストごとにサーバと transport を作る。
import { WebStandardStreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/webStandardStreamableHttp.js";
import { buildMcpServer } from "@/lib/mcp-server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const CORS: Record<string, string> = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, POST, DELETE, OPTIONS",
  "access-control-allow-headers": "Content-Type, Accept, Mcp-Session-Id, Mcp-Protocol-Version, Last-Event-ID",
  "access-control-expose-headers": "Mcp-Session-Id, Mcp-Protocol-Version",
};

async function handle(req: Request): Promise<Response> {
  const server = buildMcpServer();
  const transport = new WebStandardStreamableHTTPServerTransport({
    sessionIdGenerator: undefined,
    enableJsonResponse: true,
  });
  await server.connect(transport);
  try {
    const res = await transport.handleRequest(req);
    const headers = new Headers(res.headers);
    for (const [k, v] of Object.entries(CORS)) headers.set(k, v);
    headers.set("cache-control", "no-store");
    return new Response(res.body, { status: res.status, statusText: res.statusText, headers });
  } finally {
    await server.close();
  }
}

// セッションもサーバ発のストリームも持たないので、GET（SSE）と DELETE（セッション終了）は 405 にする（MCP 仕様）。
const notAllowed = () =>
  Response.json(
    { jsonrpc: "2.0", error: { code: -32000, message: "Method not allowed. Use POST." }, id: null },
    { status: 405, headers: { ...CORS, allow: "POST, OPTIONS" } },
  );

export const POST = handle;
export const GET = notAllowed;
export const DELETE = notAllowed;
export const OPTIONS = () => new Response(null, { status: 204, headers: CORS });
