## UV5R Mini Boot Flasher v0.1.1

This release adds **macOS CLI support** alongside the existing Linux workflow.

### What's new
- Added a **macOS-friendly CLI workflow**
- Added `cli.py` for command-line image prep, dry-run, and flashing
- Updated documentation for macOS usage
- Continued support for the Linux GUI/AppImage workflow

### Platform support
- **Linux:** GUI + AppImage
- **macOS:** CLI workflow

### macOS CLI requirements
Install the required Python packages first:

```bash
pip3 install Pillow pyserial
