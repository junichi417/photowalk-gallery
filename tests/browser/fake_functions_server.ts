// テスト用：本物の投稿処理（createUploadHandler）を、DB・ストレージだけ偽物にして動かす
import { createServer } from "node:http";
import { writeFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import { createUploadHandler } from "../../supabase/functions/_shared/upload_handler.ts";

const port = Number(process.argv[2]);
const outDir = process.argv[3];
const origin = process.argv[4];
mkdirSync(outDir, { recursive: true });
let n = 0;
let closed = false;

const handler = createUploadHandler({
  allowedOrigins: [origin],
  getUser: async (h) => (h === "Bearer fake-token" ? { id: "u1" } : null),
  beginUpload: async () => {
    if (closed) throw new Error("submission_closed");
    n++; return { photo_id: `ph${n}`, full_path: `ph${n}.jpg`, thumb_path: `ph${n}_t.jpg` };
  },
  putObject: async (p, b) => writeFileSync(join(outDir, p), b),
  removeObjects: async () => {},
  finishUpload: async () => {},
  abortUpload: async () => {},
});

createServer(async (req, res) => {
  if (req.url === "/__close") { closed = true; res.end("ok"); return; }
  const chunks: Buffer[] = [];
  for await (const c of req) chunks.push(c as Buffer);
  const r = await handler(new Request(`http://localhost:${port}${req.url}`, {
    method: req.method, headers: req.headers as Record<string, string>,
    body: req.method === "POST" ? Buffer.concat(chunks) : undefined,
  }));
  res.writeHead(r.status, Object.fromEntries(r.headers));
  res.end(Buffer.from(await r.arrayBuffer()));
}).listen(port, () => console.log("ready"));
