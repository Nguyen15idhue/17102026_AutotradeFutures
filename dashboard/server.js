// Dashboard skeleton (P1.0). Read-only, khong dat/huy lenh, khong giu secret.
const http = require("http");

const PORT = 8080;
const server = http.createServer((req, res) => {
  if (req.url === "/healthz") {
    res.writeHead(200, { "Content-Type": "text/plain" });
    res.end("ok");
    return;
  }
  res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
  res.end("<!doctype html><html><body><h1>Bot dashboard — Phase 1 skeleton</h1>" +
    "<p>Engine + mock dang chay. Day du 8 widget o P1.6.</p></body></html>");
});

server.listen(PORT, "0.0.0.0", () => console.log("dashboard listen " + PORT));
