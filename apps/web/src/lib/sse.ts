/**
 * Minimal, spec-following Server-Sent Events parser for fetch() response bodies.
 * EventSource cannot POST or send an Authorization header, so the chat stream is read manually.
 */

export interface SSEMessage {
  event: string;
  data: string;
  id?: string;
}

/** Incremental parser: feed text chunks, receive complete messages. */
export class SSEParser {
  private buffer = "";
  private event = "";
  private data: string[] = [];
  private id: string | undefined;

  feed(chunk: string): SSEMessage[] {
    this.buffer += chunk;
    const out: SSEMessage[] = [];
    // Split on any line terminator (CRLF, LF, CR); keep the trailing partial line buffered.
    const lines = this.buffer.split(/\r\n|\n|\r/);
    this.buffer = lines.pop() ?? "";
    for (const line of lines) {
      const msg = this.line(line);
      if (msg) out.push(msg);
    }
    return out;
  }

  /** Flush at end of stream (a final message without a trailing blank line is dispatched). */
  end(): SSEMessage[] {
    const out = this.buffer ? this.feed("\n") : [];
    const last = this.line("");
    if (last) out.push(last);
    return out;
  }

  private line(line: string): SSEMessage | null {
    if (line === "") {
      if (this.data.length === 0) {
        this.event = "";
        return null;
      }
      const msg: SSEMessage = { event: this.event || "message", data: this.data.join("\n") };
      if (this.id !== undefined) msg.id = this.id;
      this.event = "";
      this.data = [];
      return msg;
    }
    if (line.startsWith(":")) return null;
    const idx = line.indexOf(":");
    const field = idx === -1 ? line : line.slice(0, idx);
    let value = idx === -1 ? "" : line.slice(idx + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") this.event = value;
    else if (field === "data") this.data.push(value);
    else if (field === "id") this.id = value;
    return null;
  }
}

/** Iterate SSE messages from a ReadableStream of bytes. */
export async function* readSSE(
  body: ReadableStream<Uint8Array>,
  signal?: AbortSignal,
): AsyncGenerator<SSEMessage> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  const parser = new SSEParser();
  try {
    while (true) {
      if (signal?.aborted) return;
      const { value, done } = await reader.read();
      if (done) break;
      for (const msg of parser.feed(decoder.decode(value, { stream: true }))) yield msg;
    }
    for (const msg of parser.feed(decoder.decode())) yield msg;
    for (const msg of parser.end()) yield msg;
  } finally {
    reader.releaseLock();
  }
}
