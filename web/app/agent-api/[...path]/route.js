export const dynamic = "force-dynamic";

async function proxy(request, context) {
  const agentOrigin = process.env.AGENT_API_ORIGIN || "http://127.0.0.1:8000";
  const { path } = await context.params;
  const incomingUrl = new URL(request.url);
  const targetUrl = new URL(path.join("/"), `${agentOrigin}/`);
  targetUrl.search = incomingUrl.search;

  const headers = new Headers();
  for (const name of ["accept", "authorization", "content-type", "x-razorpay-event-id", "x-razorpay-signature"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }

  const hasBody = request.method !== "GET" && request.method !== "HEAD";
  try {
    const response = await fetch(targetUrl, {
      method: request.method,
      headers,
      body: hasBody ? await request.arrayBuffer() : undefined,
      cache: "no-store",
    });
    return new Response(response.body, {
      status: response.status,
      headers: response.headers,
    });
  } catch {
    return Response.json({ detail: "The server could not complete this request" }, { status: 502 });
  }
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
