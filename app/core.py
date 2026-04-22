#!/usr/bin/env python3
"""
UV-5R Mini boot image prep / flasher prototype for Linux (Nobara-friendly).

What this currently does:
- Converts an input image to a 128x128 BMP preview file.
- Converts pixels to RGB565 little-endian payload (32768 bytes).
- Opens the serial port at the inferred CPS settings.
- Performs the inferred pre-handshake and handshake.
- Builds packets with the inferred framing and CRC.
- Includes a draft flashing flow based on reversed CPS logic.

What is still inferred and should be treated carefully:
- Response parsing details beyond the framing/CRC.
- Exact semantics of every command/ack value.

Use at your own risk. Test on expendable hardware only.
"""

from __future__ import annotations

import argparse
import struct
import sys
import time
from pathlib import Path
from typing import Optional

from PIL import Image
import serial


WIDTH = 128
HEIGHT = 128
CHUNK = 1024
IMAGE_ADDR = 0x000C0000  # inferred from CPS
ERASE_BLOCKS = 1         # inferred from CPS

# Inferred command IDs from the reversed CPS
CMD_PROGRAM = 0x02
CMD_SET_ADDRESS = 0x03
CMD_ERASE = 0x04
CMD_DATA = 0x57
CMD_OVER = 0x06

PRE_HANDSHAKE_ASCII = b"PROGRAMCOLORPROU"
PRE_HANDSHAKE_EXPECT = 0x06
PRE_HANDSHAKE_REPLY = 0x44


class ProtocolError(RuntimeError):
    pass


def crc16_ccitt_zero(data: bytes) -> int:
    """CRC-CCITT with init 0x0000 and poly 0x1021, matching the reversed CPS."""
    crc = 0
    for b in data:
        crc ^= (b << 8)
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def center_crop_square(img: Image.Image) -> Image.Image:
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    return img.crop((left, top, left + side, top + side))


def prepare_bmp_and_payload(input_path: Path, out_bmp: Path, out_raw: Optional[Path]) -> bytes:
    img = Image.open(input_path).convert("RGB")
    img = center_crop_square(img).resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
    img.save(out_bmp, format="BMP")

    payload = bytearray()
    for y in range(HEIGHT):
        for x in range(WIDTH):
            r, g, b = img.getpixel((x, y))
            rgb565 = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
            payload.append(rgb565 & 0xFF)
            payload.append((rgb565 >> 8) & 0xFF)

    if len(payload) != WIDTH * HEIGHT * 2:
        raise ValueError(f"Unexpected payload length: {len(payload)}")

    if out_raw:
        out_raw.write_bytes(payload)

    return bytes(payload)


def build_packet(cmd: int, package_id: int, payload: bytes) -> bytes:
    if not (0 <= cmd <= 0xFF):
        raise ValueError("cmd out of range")
    if not (0 <= package_id <= 0xFFFF):
        raise ValueError("package_id out of range")
    if not (0 <= len(payload) <= 0xFFFF):
        raise ValueError("payload too large")

    header = bytes([
        0xA5,
        cmd & 0xFF,
        (package_id >> 8) & 0xFF,
        package_id & 0xFF,
        (len(payload) >> 8) & 0xFF,
        len(payload) & 0xFF,
    ])
    crc = crc16_ccitt_zero(header[1:] + payload)
    return header + payload + bytes([(crc >> 8) & 0xFF, crc & 0xFF])


def parse_packet(buf: bytes) -> bytes:
    if len(buf) < 8:
        raise ProtocolError("Packet too short")
    if buf[0] != 0xA5:
        raise ProtocolError(f"Bad sync byte: 0x{buf[0]:02X}")
    payload_len = (buf[4] << 8) | buf[5]
    need = 6 + payload_len + 2
    if len(buf) < need:
        raise ProtocolError(f"Short packet: have {len(buf)}, need {need}")
    payload = buf[6:6 + payload_len]
    rx_crc = (buf[6 + payload_len] << 8) | buf[6 + payload_len + 1]
    calc_crc = crc16_ccitt_zero(buf[1:6] + payload)
    if rx_crc != calc_crc:
        raise ProtocolError(f"CRC mismatch: got 0x{rx_crc:04X}, expected 0x{calc_crc:04X}")
    return payload


class UV5RMiniBootFlasher:
    def __init__(self, port: str, timeout: float = 0.4):
        self.ser = serial.Serial(
            port=port,
            baudrate=115200,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=timeout,
            write_timeout=timeout,
            rtscts=False,
            dsrdtr=False,
        )
        self.ser.dtr = True
        self.ser.rts = True

    def close(self) -> None:
        try:
            self.ser.close()
        except Exception:
            pass

    def _read_exact(self, n: int) -> bytes:
        data = self.ser.read(n)
        if len(data) != n:
            raise ProtocolError(f"Wanted {n} bytes, got {len(data)}")
        return data

    def _read_packet(self) -> bytes:
        start = self._read_exact(1)
        if start[0] != 0xA5:
            raise ProtocolError(f"Expected 0xA5, got 0x{start[0]:02X}")
        hdr_rest = self._read_exact(5)
        payload_len = (hdr_rest[3] << 8) | hdr_rest[4]
        payload_crc = self._read_exact(payload_len + 2)
        return start + hdr_rest + payload_crc

    def pre_handshake(self) -> None:
        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()
        self.ser.write(PRE_HANDSHAKE_ASCII)
        b = self._read_exact(1)[0]
        if b != PRE_HANDSHAKE_EXPECT:
            raise ProtocolError(f"Pre-handshake expected 0x06, got 0x{b:02X}")
        self.ser.write(bytes([PRE_HANDSHAKE_REPLY]))
        time.sleep(0.1)

    def send_packet(self, cmd: int, package_id: int, payload: bytes) -> None:
        pkt = build_packet(cmd, package_id, payload)
        self.ser.write(pkt)

    def start_program(self) -> bytes:
        self.send_packet(CMD_PROGRAM, 0, b"PROGRAM")
        return parse_packet(self._read_packet())

    def erase_region(self, address: int = IMAGE_ADDR, erase_blocks: int = ERASE_BLOCKS) -> bytes:
        # Inferred payload layout from CPS:
        # address: 4 bytes little-endian, erase_blocks: 2 bytes big-endian
        payload = struct.pack("<I", address) + struct.pack(">H", erase_blocks)
        self.send_packet(CMD_ERASE, 0x4504, payload)
        return parse_packet(self._read_packet())

    def set_address(self, address: int = IMAGE_ADDR) -> bytes:
        payload = struct.pack("<I", address)
        self.send_packet(CMD_SET_ADDRESS, 0, payload)
        return parse_packet(self._read_packet())

    def send_chunk(self, package_id: int, payload: bytes) -> bytes:
        if len(payload) != CHUNK:
            raise ValueError(f"Chunk must be {CHUNK} bytes")
        self.send_packet(CMD_DATA, package_id, payload)
        return parse_packet(self._read_packet())

    def finish(self) -> None:
        self.send_packet(CMD_OVER, 0, b"Over")
        # CPS closes shortly after sending this; response is uncertain.

    def flash(self, rgb565_payload: bytes, dry_run: bool = False) -> None:
        if len(rgb565_payload) != WIDTH * HEIGHT * 2:
            raise ValueError("Unexpected image payload length")

        print("[*] Pre-handshake...")
        if not dry_run:
            self.pre_handshake()

        print("[*] PROGRAM...")
        if not dry_run:
            resp = self.start_program()
            print(f"    response: {resp.hex(' ')}")

        print("[*] ERASE...")
        if not dry_run:
            resp = self.erase_region()
            print(f"    response: {resp.hex(' ')}")

        print("[*] SET ADDRESS...")
        if not dry_run:
            resp = self.set_address()
            print(f"    response: {resp.hex(' ')}")

        total = len(rgb565_payload) // CHUNK
        for package_id in range(total):
            chunk = rgb565_payload[package_id * CHUNK:(package_id + 1) * CHUNK]
            print(f"[*] DATA {package_id + 1}/{total}")
            if not dry_run:
                resp = self.send_chunk(package_id, chunk)
                print(f"    response: {resp.hex(' ')}")

        print("[*] OVER")
        if not dry_run:
            self.finish()


def main() -> int:
    parser = argparse.ArgumentParser(description="UV-5R Mini boot image prep / flasher prototype")
    parser.add_argument("image", help="input image path")
    parser.add_argument("--bmp", default="uv5rmini_boot.bmp", help="output 128x128 BMP path")
    parser.add_argument("--raw", default="uv5rmini_boot.rgb565", help="output raw RGB565 path")
    parser.add_argument("--port", help="serial port, e.g. /dev/ttyUSB0")
    parser.add_argument("--prep-only", action="store_true", help="only generate BMP and raw payload")
    parser.add_argument("--dry-run", action="store_true", help="build payload and print planned flash steps without touching serial")
    args = parser.parse_args()

    input_path = Path(args.image)
    out_bmp = Path(args.bmp)
    out_raw = Path(args.raw) if args.raw else None

    payload = prepare_bmp_and_payload(input_path, out_bmp, out_raw)
    print(f"[+] Wrote BMP preview: {out_bmp}")
    if out_raw:
        print(f"[+] Wrote RGB565 payload: {out_raw} ({len(payload)} bytes)")

    if args.prep_only:
        return 0

    if not args.port and not args.dry_run:
        print("[!] --port is required unless --prep-only or --dry-run is used", file=sys.stderr)
        return 2

    flasher = None
    try:
        if args.dry_run:
            print("[i] Dry run mode; not opening serial port")
            total = len(payload) // CHUNK
            print(f"[i] Would send {total} data packets of {CHUNK} bytes each")
            return 0

        flasher = UV5RMiniBootFlasher(args.port)
        flasher.flash(payload, dry_run=False)
        print("[+] Flash sequence completed")
        return 0
    finally:
        if flasher:
            flasher.close()


if __name__ == "__main__":
    raise SystemExit(main())
