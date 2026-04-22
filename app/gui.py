from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QComboBox,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

import serial.tools.list_ports

from .core import prepare_bmp_and_payload, UV5RMiniBootFlasher


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("UV-5R Mini Boot Flasher")
        self.resize(760, 520)

        self.image_path: Path | None = None

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        top_group = QGroupBox("Boot Image")
        top_layout = QGridLayout(top_group)

        self.image_edit = QLineEdit()
        self.image_edit.setPlaceholderText("Select an image file...")
        self.image_edit.setReadOnly(True)

        self.browse_button = QPushButton("Browse")
        self.browse_button.clicked.connect(self.choose_image)

        self.preview_label = QLabel("No preview")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumSize(180, 180)
        self.preview_label.setStyleSheet("border: 1px solid gray;")

        top_layout.addWidget(QLabel("Image:"), 0, 0)
        top_layout.addWidget(self.image_edit, 0, 1)
        top_layout.addWidget(self.browse_button, 0, 2)
        top_layout.addWidget(self.preview_label, 1, 0, 1, 3)

        serial_group = QGroupBox("Radio Port")
        serial_layout = QHBoxLayout(serial_group)

        self.port_combo = QComboBox()
        self.refresh_ports_button = QPushButton("Refresh Ports")
        self.refresh_ports_button.clicked.connect(self.refresh_ports)

        serial_layout.addWidget(QLabel("Serial Port:"))
        serial_layout.addWidget(self.port_combo)
        serial_layout.addWidget(self.refresh_ports_button)

        buttons_group = QGroupBox("Actions")
        buttons_layout = QHBoxLayout(buttons_group)

        self.prep_button = QPushButton("Prep Image")
        self.prep_button.clicked.connect(self.prep_image)

        self.dry_run_button = QPushButton("Dry Run")
        self.dry_run_button.clicked.connect(self.dry_run)

        self.flash_button = QPushButton("Flash Boot Image")
        self.flash_button.clicked.connect(self.flash_image)

        buttons_layout.addWidget(self.prep_button)
        buttons_layout.addWidget(self.dry_run_button)
        buttons_layout.addWidget(self.flash_button)

        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)

        layout.addWidget(top_group)
        layout.addWidget(serial_group)
        layout.addWidget(buttons_group)
        layout.addWidget(QLabel("Log"))
        layout.addWidget(self.log_box)

        self.refresh_ports()

    def log(self, text: str) -> None:
        self.log_box.appendPlainText(text)

    def choose_image(self) -> None:
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Select boot image",
            str(Path.home() / "Downloads"),
            "Images (*.png *.jpg *.jpeg *.bmp *.webp)",
        )
        if not file_name:
            return

        self.image_path = Path(file_name)
        self.image_edit.setText(str(self.image_path))
        self.update_preview(self.image_path)
        self.log(f"[+] Selected image: {self.image_path}")

    def update_preview(self, image_path: Path) -> None:
        pixmap = QPixmap(str(image_path))
        if pixmap.isNull():
            self.preview_label.setText("Preview failed")
            return
        self.preview_label.setPixmap(
            pixmap.scaled(
                180,
                180,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def refresh_ports(self) -> None:
        self.port_combo.clear()
        ports = list(serial.tools.list_ports.comports())
        for port in ports:
            self.port_combo.addItem(port.device)
        if not ports:
            self.port_combo.addItem("/dev/ttyUSB0")
        self.log("[i] Refreshed serial ports")

    def require_image(self) -> Path | None:
        if not self.image_path:
            QMessageBox.warning(self, "Missing image", "Please choose an image first.")
            return None
        return self.image_path

    def prep_image(self) -> None:
        image_path = self.require_image()
        if not image_path:
            return

        out_bmp = Path.cwd() / "uv5rmini_boot.bmp"
        out_raw = Path.cwd() / "uv5rmini_boot.rgb565"

        try:
            payload = prepare_bmp_and_payload(image_path, out_bmp, out_raw)
            self.log(f"[+] Wrote BMP preview: {out_bmp}")
            self.log(f"[+] Wrote RGB565 payload: {out_raw} ({len(payload)} bytes)")
            QMessageBox.information(self, "Success", "Boot image prepared successfully.")
        except Exception as e:
            self.log(f"[!] Prep failed: {e}")
            QMessageBox.critical(self, "Error", str(e))

    def dry_run(self) -> None:
        image_path = self.require_image()
        if not image_path:
            return

        out_bmp = Path.cwd() / "uv5rmini_boot.bmp"
        out_raw = Path.cwd() / "uv5rmini_boot.rgb565"

        try:
            payload = prepare_bmp_and_payload(image_path, out_bmp, out_raw)
            packets = len(payload) // 1024
            self.log(f"[+] Wrote BMP preview: {out_bmp}")
            self.log(f"[+] Wrote RGB565 payload: {out_raw} ({len(payload)} bytes)")
            self.log("[i] Dry run mode; not opening serial port")
            self.log(f"[i] Would send {packets} data packets of 1024 bytes each")
            QMessageBox.information(self, "Dry Run", f"Would send {packets} packets.")
        except Exception as e:
            self.log(f"[!] Dry run failed: {e}")
            QMessageBox.critical(self, "Error", str(e))

    def flash_image(self) -> None:
        image_path = self.require_image()
        if not image_path:
            return

        port = self.port_combo.currentText().strip()
        if not port:
            QMessageBox.warning(self, "Missing port", "Please choose a serial port first.")
            return

        confirm = QMessageBox.question(
            self,
            "Confirm Flash",
            f"This will attempt to flash a boot image to the radio on {port}.\n\n"
            "This is still prototype-grade flashing logic.\n\n"
            "Continue?",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            self.log("[i] Flash cancelled by user.")
            return

        out_bmp = Path.cwd() / "uv5rmini_boot.bmp"
        out_raw = Path.cwd() / "uv5rmini_boot.rgb565"

        flasher = None
        try:
            payload = prepare_bmp_and_payload(image_path, out_bmp, out_raw)
            self.log(f"[+] Wrote BMP preview: {out_bmp}")
            self.log(f"[+] Wrote RGB565 payload: {out_raw} ({len(payload)} bytes)")
            self.log(f"[*] Opening port {port}")

            flasher = UV5RMiniBootFlasher(port)

            self.log("[*] Pre-handshake...")
            flasher.pre_handshake()
            self.log("[+] Pre-handshake OK")

            self.log("[*] Sending PROGRAM...")
            resp = flasher.start_program()
            self.log(f"[+] PROGRAM response: {resp.hex(' ')}")

            self.log("[*] Sending ERASE...")
            resp = flasher.erase_region()
            self.log(f"[+] ERASE response: {resp.hex(' ')}")

            self.log("[*] Sending SET ADDRESS...")
            resp = flasher.set_address()
            self.log(f"[+] SET ADDRESS response: {resp.hex(' ')}")

            total = len(payload) // 1024
            for package_id in range(total):
                chunk = payload[package_id * 1024:(package_id + 1) * 1024]
                self.log(f"[*] Sending DATA packet {package_id + 1}/{total}")
                resp = flasher.send_chunk(package_id, chunk)
                self.log(f"[+] DATA response: {resp.hex(' ')}")

            self.log("[*] Sending OVER...")
            flasher.finish()
            self.log("[+] Flash sequence completed")

            QMessageBox.information(self, "Success", "Boot image flash sequence completed.")

        except Exception as e:
            self.log(f"[!] Flash failed: {e}")
            QMessageBox.critical(self, "Flash Error", str(e))
        finally:
            if flasher:
                flasher.close()
