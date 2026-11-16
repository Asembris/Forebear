"""Regression for the security review finding: the SPA catch-all route must never serve
files outside web/dist (e.g. ../.env, ../README.md, absolute Windows paths).

Uses raw sockets so the request line reaches the server byte-for-byte; HTTP clients
normalise '../' before sending, which would make the test pass vacuously."""
import socket

CRLF = "\r\n"
PROBES = (
    "/../../README.md",
    "/..%2f..%2fREADME.md",
    "/C:/Windows/win.ini",
    "/%2e%2e/%2e%2e/requirements.txt",
    "/..%5c..%5cREADME.md",
    "/../data/build_report.json",
)


def raw_get(port: int, path: str) -> str:
    request = f"GET {path} HTTP/1.1{CRLF}Host: x{CRLF}Connection: close{CRLF}{CRLF}"
    with socket.create_connection(("127.0.0.1", port), timeout=10) as s:
        s.sendall(request.encode())
        data = b""
        while chunk := s.recv(65536):
            data += chunk
    return data.decode("latin-1")


def test_static_route_cannot_escape_dist(live_api):
    port = int(live_api["_PORT"])
    for path in PROBES:
        body = raw_get(port, path)
        leaked = ("# Forebear" in body or "relate-db==" in body or "16-bit" in body
                  or "citation_extraction" in body)
        assert not leaked, f"{path} leaked a file outside web/dist"
    assert "<!doctype html>" in raw_get(port, "/").lower()
