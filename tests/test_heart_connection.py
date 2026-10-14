import base64
import hashlib
import socket
import sys
from pathlib import Path
from unittest import TestCase, mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "main"))
import heart


class HeartConnectionTests(TestCase):
    def test_ipv4_is_tried_before_unreachable_ipv6(self):
        addresses = [
            (socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("::1", 443, 0, 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 443)),
        ]
        connections = []

        class FakeSocket:
            def __init__(self, family):
                self.family = family

            def settimeout(self, timeout):
                pass

            def connect(self, sockaddr):
                connections.append(self.family)
                if self.family == socket.AF_INET6:
                    raise TimeoutError("IPv6 unavailable")

            def close(self):
                pass

        with mock.patch.object(heart.socket, "getaddrinfo", return_value=addresses), \
             mock.patch.object(heart.socket, "socket", side_effect=lambda family, *_: FakeSocket(family)):
            connection = heart._open_tcp_stream("example.invalid", 443)

        self.assertEqual(connection.family, socket.AF_INET)
        self.assertEqual(connections, [socket.AF_INET])

    def test_first_frame_bundled_with_handshake_is_not_dropped(self):
        payload = b'{"data":{"heartRate":72}}'
        frame = bytes([0x81, len(payload)]) + payload + bytes([0x88, 0x00])
        packet = (
            b"HTTP/1.1 101 Switching Protocols\r\n"
            b"Upgrade: websocket\r\n"
            b"Connection: Upgrade\r\n"
            b"\r\n"
            + frame
        )

        class OnePacketSocket:
            def __init__(self):
                self.buf = packet

            def sendall(self, data):
                key = b""
                for line in data.split(b"\r\n"):
                    if line.lower().startswith(b"sec-websocket-key:"):
                        key = line.split(b":", 1)[1].strip()
                accept = base64.b64encode(hashlib.sha1(
                    key + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest())
                self.buf = (
                    b"HTTP/1.1 101 Switching Protocols\r\n"
                    b"Upgrade: websocket\r\n"
                    b"Connection: Upgrade\r\n"
                    b"Sec-WebSocket-Accept: " + accept + b"\r\n"
                    b"\r\n"
                    + frame
                )

            def recv(self, n):
                data = self.buf[:n]
                self.buf = self.buf[n:]
                return data

            def settimeout(self, timeout):
                pass

            def close(self):
                pass

        previous_bpm = heart._LAST_BPM
        previous_bpm_t = heart._LAST_BPM_T
        heart._STOP.clear()
        try:
            with mock.patch.object(heart, "_open_tcp_stream", return_value=OnePacketSocket()):
                got_bpm = heart._ws_loop_stdlib("ws://example.invalid/socket")
            self.assertTrue(got_bpm)
            self.assertEqual(heart.latest_bpm(), 72)
        finally:
            heart._LAST_BPM = previous_bpm
            heart._LAST_BPM_T = previous_bpm_t
