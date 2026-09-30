"""
Independent fallback TTS client for Sonora.

Speaks the same Microsoft Edge read-aloud protocol as the main `edge-tts`
client, but is a completely separate implementation: its own WebSocket
session, its own DRM token, its own MUID/ConnectionId. Used only when the
primary client fails repeatedly (transient service rejections).
"""
import asyncio
import hashlib
import secrets
import time
from datetime import datetime as dt
from datetime import timezone as tz
from xml.sax.saxutils import escape

import aiohttp

TRUSTED_CLIENT_TOKEN = "6A5AA1D4EAFF4E9FB37E23D68491D6F4"
BASE_URL = "speech.platform.bing.com/consumer/speech/synthesize/readaloud"
CHROMIUM_MAJOR = "143"
SEC_MS_GEC_VERSION = f"1-143.0.3650.75"
WIN_EPOCH = 11644473600


def _sec_ms_gec() -> str:
    ticks = dt.now(tz.utc).timestamp() + WIN_EPOCH
    ticks -= ticks % 300
    ticks *= 1e9 / 100
    return hashlib.sha256(f"{ticks:.0f}{TRUSTED_CLIENT_TOKEN}".encode("ascii")).hexdigest().upper()


def _date_string() -> str:
    return time.strftime("%a %b %d %Y %H:%M:%S GMT+0000 (Coordinated Universal Time)", time.gmtime())


def _clean(text: str) -> str:
    chars = list(text)
    for i, c in enumerate(chars):
        code = ord(c)
        if (0 <= code <= 8) or (11 <= code <= 12) or (14 <= code <= 31):
            chars[i] = " "
    return "".join(chars)


def _ssml(voice: str, rate: str, text: str) -> str:
    return (
        "<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='en-US'>"
        f"<voice name='{voice}'>"
        f"<prosody pitch='+0Hz' rate='{rate}' volume='+0%'>"
        f"{escape(_clean(text))}"
        "</prosody></voice></speak>"
    )


async def _tts_once(text: str, voice: str, rate: str, timeout: int = 90,
                    output_format: str = "audio-24khz-48kbitrate-mono-mp3") -> bytes:
    url = (
        f"wss://{BASE_URL}/edge/v1?TrustedClientToken={TRUSTED_CLIENT_TOKEN}"
        f"&ConnectionId={secrets.token_hex(16)}"
        f"&Sec-MS-GEC={_sec_ms_gec()}"
        f"&Sec-MS-GEC-Version={SEC_MS_GEC_VERSION}"
    )
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            f"(KHTML, like Gecko) Chrome/{CHROMIUM_MAJOR}.0.0.0 Safari/537.36 "
            f"Edg/{CHROMIUM_MAJOR}.0.0.0"
        ),
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "en-US,en;q=0.9",
        "Pragma": "no-cache",
        "Cache-Control": "no-cache",
        "Origin": "chrome-extension://jdiccldimpdaibmpdkjnbmckianbfold",
        "Sec-WebSocket-Version": "13",
        "Cookie": f"muid={secrets.token_hex(16).upper()};",
    }
    audio = b""
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
        async with session.ws_connect(url, headers=headers, compress=15, heartbeat=15) as ws:
            await ws.send_str(
                f"X-Timestamp:{_date_string()}\r\n"
                "Content-Type:application/json; charset=utf-8\r\n"
                "Path:speech.config\r\n\r\n"
                '{"context":{"synthesis":{"audio":{"metadataoptions":{'
                '"sentenceBoundaryEnabled":"true","wordBoundaryEnabled":"false"'
                '},"outputFormat":"' + output_format + '"}}}}\r\n'
            )
            await ws.send_str(
                f"X-RequestId:{secrets.token_hex(16)}\r\n"
                "Content-Type:application/ssml+xml\r\n"
                f"X-Timestamp:{_date_string()}Z\r\n"
                "Path:ssml\r\n\r\n"
                + _ssml(voice, rate, text)
            )
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    raw = msg.data.encode("utf-8")
                    sep = raw.find(b"\r\n\r\n")
                    if sep == -1:
                        continue
                    hdr = {}
                    for line in raw[:sep].split(b"\r\n"):
                        k, _, v = line.partition(b":")
                        hdr[k] = v
                    if hdr.get(b"Path") == b"turn.end":
                        break
                    if hdr.get(b"Path") == b"response":
                        # handshake confirmation is normal; only a real error payload matters
                        body = raw[sep + 4:].decode("utf-8", "replace")
                        if '"error"' in body:
                            raise RuntimeError(f"service error: {body[:200]}")
                elif msg.type == aiohttp.WSMsgType.BINARY:
                    data = msg.data
                    if len(data) < 2:
                        continue
                    hlen = int.from_bytes(data[:2], "big")
                    if hlen > len(data):
                        raise RuntimeError("malformed audio frame")
                    hdr = {}
                    for line in data[:hlen].split(b"\r\n"):
                        k, _, v = line.partition(b":")
                        hdr[k] = v
                    if hdr.get(b"Path") == b"audio":
                        audio += data[hlen + 2:]
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING):
                    break
    if not audio:
        raise RuntimeError("no audio received")
    return audio


def fallback_tts(text: str, voice: str, rate: str = "+0%",
                 output_format: str = "audio-24khz-48kbitrate-mono-mp3") -> bytes:
    """Blocking wrapper: synthesize via the independent client. Raises on failure.

    `output_format` lets the studio ask for a higher-resolution stream
    (audio-48khz-192kbitrate-mono-mp3) where the service supports it — used by
    the narration-style demos, which are meant to be heard clean.
    """
    return asyncio.run(_tts_once(text, voice, rate, output_format=output_format))
