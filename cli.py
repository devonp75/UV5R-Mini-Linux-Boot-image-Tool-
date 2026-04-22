from __future__ import annotations

import argparse
from pathlib import Path

import serial.tools.list_ports

from app.core import prepare_bmp_and_payload, UV5RMiniBootFlasher


def list_ports() -> int:
    ports = list(serial.tools.list_ports.comports())
    if not ports:
        print("[!] No serial ports found")
        return 1

    print("[+] Available serial ports:")
    for port in ports:
        desc = f" - {port.description}" if port.description else ""
        print(f"  {port.device}{desc}")
    return 0


def do_prep(image: str) -> int:
    image_path = Path(image)
    out_bmp = Path.cwd() / "uv5rmini_boot.bmp"
    out_raw = Path.cwd() / "uv5rmini_boot.rgb565"

    payload = prepare_bmp_and_payload(image_path, out_bmp, out_raw)
    print(f"[+] Wrote BMP preview: {out_bmp}")
    print(f"[+] Wrote RGB565 payload: {out_raw} ({len(payload)} bytes)")
    return 0


def do_dry_run(image: str) -> int:
    image_path = Path(image)
    out_bmp = Path.cwd() / "uv5rmini_boot.bmp"
    out_raw = Path.cwd() / "uv5rmini_boot.rgb565"

    payload = prepare_bmp_and_payload(image_path, out_bmp, out_raw)
    packets = len(payload) // 1024

    print(f"[+] Wrote BMP preview: {out_bmp}")
    print(f"[+] Wrote RGB565 payload: {out_raw} ({len(payload)} bytes)")
    print("[i] Dry run mode; not opening serial port")
    print(f"[i] Would send {packets} data packets of 1024 bytes each")
    return 0


def do_flash(image: str, port: str) -> int:
    image_path = Path(image)
    out_bmp = Path.cwd() / "uv5rmini_boot.bmp"
    out_raw = Path.cwd() / "uv5rmini_boot.rgb565"

    payload = prepare_bmp_and_payload(image_path, out_bmp, out_raw)
    print(f"[+] Wrote BMP preview: {out_bmp}")
    print(f"[+] Wrote RGB565 payload: {out_raw} ({len(payload)} bytes)")
    print(f"[*] Opening port: {port}")

    flasher = None
    try:
        flasher = UV5RMiniBootFlasher(port)

        print("[*] Pre-handshake...")
        flasher.pre_handshake()
        print("[+] Pre-handshake OK")

        print("[*] Sending PROGRAM...")
        resp = flasher.start_program()
        print(f"[+] PROGRAM response: {resp.hex(' ')}")

        print("[*] Sending ERASE...")
        resp = flasher.erase_region()
        print(f"[+] ERASE response: {resp.hex(' ')}")

        print("[*] Sending SET ADDRESS...")
        resp = flasher.set_address()
        print(f"[+] SET ADDRESS response: {resp.hex(' ')}")

        total = len(payload) // 1024
        for package_id in range(total):
            chunk = payload[package_id * 1024:(package_id + 1) * 1024]
            print(f"[*] Sending DATA packet {package_id + 1}/{total}")
            resp = flasher.send_chunk(package_id, chunk)
            print(f"[+] DATA response: {resp.hex(' ')}")

        print("[*] Sending OVER...")
        flasher.finish()
        print("[+] Flash sequence completed")
        return 0

    finally:
        if flasher:
            flasher.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="UV-5R Mini Boot Flasher CLI (macOS-friendly)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list-ports", help="List available serial ports")

    prep = sub.add_parser("prep", help="Prepare BMP preview and RGB565 payload")
    prep.add_argument("image", help="Input image path")

    dry = sub.add_parser("dry-run", help="Prepare image and show flash plan")
    dry.add_argument("image", help="Input image path")

    flash = sub.add_parser("flash", help="Flash boot image to radio")
    flash.add_argument("image", help="Input image path")
    flash.add_argument("--port", required=True, help="Serial port, e.g. /dev/cu.usbserial-XXXX")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "list-ports":
        return list_ports()
    if args.command == "prep":
        return do_prep(args.image)
    if args.command == "dry-run":
        return do_dry_run(args.image)
    if args.command == "flash":
        return do_flash(args.image, args.port)

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
