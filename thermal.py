#!/usr/bin/env python3
"""ESC/POS driver and CLI for the Gprinter GP-L80160 over USB or Bluetooth.

    thermal.py text "Hello"        print text (or pipe it in on stdin)
    thermal.py image photo.png     print an image, dithered to fit the paper
    thermal.py test                print a width and dither test pattern
    thermal.py status              show online and paper state

Add --cut to feed and cut afterwards, --width to override the 576-dot default,
--port /dev/cu.BlueToothPrinter to use Bluetooth instead of USB.
"""
import argparse
import os
import select
import signal
import sys
import termios
import threading
import time

USB = "usb"
USB_VENDOR = 0x0416
USB_PRODUCT = 0x5011
BLUETOOTH_PORT = "/dev/cu.BlueToothPrinter"
WIDTH_DOTS = 576
PHOTO_CUTOFF = 2  # percent of darkest and lightest pixels ignored by auto-levels
PHOTO_GAMMA = 0.85  # under 1 lifts shadows; lower is lighter with less contrast
PHOTO_CONTRAST = 0.8  # above 1 pushes tones away from mid-grey, below pulls them in
CONNECT_TIMEOUT = 20
WRITE_TIMEOUT = 10
SERIAL_CHUNK = 512
SERIAL_CHUNK_DELAY = 0.02
USB_CHUNK = 64
USB_CHUNK_DELAY = 0.03  # quality over speed; slower lets the head cool between rows and prints lighter
USB_BAND_DELAY = 0.2
USB_STALL_RETRIES = 5
USB_MAX_DOTS = 384  # measured print head width: 48mm; anything wider is cut off


class UsbLink:
    def __init__(self):
        self.device = None
        self.stalls = 0
        self.row_delay = USB_CHUNK_DELAY
        self._connect()

    def _connect(self):
        import libusb_package
        import usb.util

        self.device = libusb_package.find(idVendor=USB_VENDOR, idProduct=USB_PRODUCT)
        if self.device is None:
            raise ConnectionError("printer not found on USB: is it plugged in and on?")
        self.device.set_configuration()
        interface = self.device.get_active_configuration()[(0, 0)]

        def endpoint(direction):
            return usb.util.find_descriptor(
                interface,
                custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress) == direction,
            )

        self.ep_out = endpoint(usb.util.ENDPOINT_OUT)
        self.ep_in = endpoint(usb.util.ENDPOINT_IN)
        # The printer stalls its endpoints across connections, which fails the
        # first write with a pipe error unless they're cleared.
        usb.util.claim_interface(self.device, interface)
        self.ep_out.clear_halt()
        self.ep_in.clear_halt()

    def write(self, data):
        for i in range(0, len(data), USB_CHUNK):
            self._send(data[i : i + USB_CHUNK])
            time.sleep(self.row_delay)

    def _send(self, packet):
        import usb.core

        # clear_halt alone desyncs the raster and prints garbage, so a stall
        # gets a full reconnect, then the same packet again.
        for attempt in range(USB_STALL_RETRIES):
            try:
                self.ep_out.write(packet, timeout=WRITE_TIMEOUT * 1000)
                return
            except usb.core.USBError:
                self.stalls += 1
                time.sleep(USB_BAND_DELAY)
                self._reconnect()
        self.ep_out.write(packet, timeout=WRITE_TIMEOUT * 1000)

    def _reconnect(self):
        import usb.core

        deadline = time.time() + CONNECT_TIMEOUT
        while True:
            try:
                self.close()
                self._connect()
                return
            except (usb.core.USBError, ConnectionError):
                if time.time() > deadline:
                    raise
                time.sleep(USB_BAND_DELAY)

    def query(self, cmd, wait=1.0):
        import usb.core

        self.write(cmd)
        if self.ep_in is None:
            return b""
        try:
            return bytes(self.ep_in.read(self.ep_in.wMaxPacketSize, timeout=int(wait * 1000)))
        except usb.core.USBTimeoutError:
            return b""

    def close(self):
        import usb.util

        if self.device is not None:
            usb.util.dispose_resources(self.device)


class SerialLink:
    def __init__(self, port):
        signal.signal(signal.SIGALRM, self._timed_out)
        self.fd = self._open(port)
        attrs = termios.tcgetattr(self.fd)
        attrs[0] = attrs[1] = attrs[3] = 0
        attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
        termios.tcsetattr(self.fd, termios.TCSANOW, attrs)
        self._wait_for_link()

    @staticmethod
    def _open(port):
        # A wedged Bluetooth link hangs open() in the kernel, where signals
        # can't reach it, so it has to run on a thread we can walk away from.
        result = []

        def target():
            try:
                result.append(os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK))
            except OSError as error:
                result.append(error)

        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        thread.join(CONNECT_TIMEOUT)
        if not result:
            raise TimeoutError("could not open port: power cycle the printer")
        if isinstance(result[0], OSError):
            raise result[0]
        return result[0]

    @staticmethod
    def _timed_out(*_):
        raise TimeoutError("printer timed out: is it on and in range?")

    def _wait_for_link(self):
        # The port opens before the Bluetooth link is usable, and writes made
        # too early sit in the Mac's buffer, so wait for a real status reply.
        deadline = time.time() + CONNECT_TIMEOUT
        while time.time() < deadline:
            if self.query(b"\x10\x04\x01"):
                return
        raise TimeoutError("no reply from printer: power cycle it and try again")

    def write(self, data):
        view = memoryview(data)
        while view:
            _, ready, _ = select.select([], [self.fd], [], WRITE_TIMEOUT)
            if not ready:
                raise TimeoutError("printer stopped accepting data")
            try:
                sent = os.write(self.fd, view[:SERIAL_CHUNK])
            except BlockingIOError:
                continue
            view = view[sent:]
            time.sleep(SERIAL_CHUNK_DELAY)

    def query(self, cmd, wait=1.0):
        os.write(self.fd, cmd)
        ready, _, _ = select.select([self.fd], [], [], wait)
        return os.read(self.fd, 1) if ready else b""

    def close(self):
        signal.alarm(CONNECT_TIMEOUT)
        termios.tcdrain(self.fd)
        signal.alarm(0)
        os.close(self.fd)


class Printer:
    def __init__(self, port=USB, width=WIDTH_DOTS, row_delay=USB_CHUNK_DELAY):
        self.width = min(width, USB_MAX_DOTS) if port == USB else width
        self.link = UsbLink() if port == USB else SerialLink(port)
        self.link.row_delay = row_delay
        self.write(b"\x1b@")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.link.close()

    def write(self, data):
        self.link.write(data)

    def text(self, s):
        if not s.endswith("\n"):
            s += "\n"
        self.write(s.encode("cp437", "replace"))

    def feed(self, lines=4):
        self.write(b"\x1bd" + bytes([lines]))

    def cut(self):
        self.write(b"\x1dV\x42\x00")

    def image(self, img, should_stop=lambda: False):
        from PIL import Image

        img = img.convert("RGBA")
        white = Image.new("RGBA", img.size, "white")
        img = Image.alpha_composite(white, img).convert("L")
        if img.width != self.width:
            height = round(img.height * self.width / img.width)
            img = img.resize((self.width, height), Image.LANCZOS)
        img = img.convert("1")

        width_bytes = (img.width + 7) // 8
        # PIL packs "1" images as 1=white; the printer wants 1=black.
        raster = bytes(b ^ 0xFF for b in img.tobytes())
        # One self-contained command per row, each fitting one USB packet: a
        # packet lost to a stall costs a row of pixels, not the raster's sync.
        header = b"\x1dv0\x00" + width_bytes.to_bytes(2, "little") + (1).to_bytes(2, "little")
        for y in range(img.height):
            if should_stop():
                return
            self.write(header + raster[y * width_bytes : (y + 1) * width_bytes])

    def status(self):
        online = self.link.query(b"\x10\x04\x01")
        paper = self.link.query(b"\x10\x04\x04")
        if not online or not paper:
            return "no reply from printer"
        return "\n".join(
            [
                "offline" if online[0] & 0x08 else "online",
                "paper out" if paper[0] & 0x60 else "paper ok",
            ]
        )


def usb_connected():
    import libusb_package

    return libusb_package.find(idVendor=USB_VENDOR, idProduct=USB_PRODUCT) is not None


def prepare_photo(img):
    return adjust_photo(photo_base(img))


def photo_base(img):
    from PIL import ImageOps

    return ImageOps.exif_transpose(img).convert("L")


def adjust_photo(photo, cutoff=PHOTO_CUTOFF, gamma=PHOTO_GAMMA, contrast=PHOTO_CONTRAST, exposure=0):
    from PIL import ImageEnhance, ImageOps

    photo = ImageOps.autocontrast(photo, cutoff=cutoff)
    gain = 2**exposure
    photo = photo.point(lambda v: round(255 * min(1, v / 255 * gain) ** gamma))
    return ImageEnhance.Contrast(photo).enhance(contrast)


def test_pattern(width):
    from PIL import Image, ImageDraw

    height = 260
    img = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, width - 1, 139], outline=0, width=2)
    for x in range(0, width, 16):
        tall = x % 96 == 0
        draw.line([x, 0, x, 40 if tall else 20], fill=0, width=2 if tall else 1)
        if tall:
            draw.text((x + 4, 44), str(x), fill=0)
    draw.text((8, 90), f"{width} dots: the box should have 4 complete sides", fill=0)
    for x in range(width):
        draw.line([x, 150, x, height], fill=round(255 * x / (width - 1)))
    return img


def main():
    parser = argparse.ArgumentParser(description="Print to the GP-L80160.")
    parser.add_argument("--port", default=USB, help=f'"usb" or a serial port like {BLUETOOTH_PORT}')
    parser.add_argument("--width", type=int, default=WIDTH_DOTS)
    parser.add_argument("--cut", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("text").add_argument("message", nargs="?")
    sub.add_parser("image").add_argument("path")
    sub.add_parser("test")
    sub.add_parser("status")
    args = parser.parse_args()

    with Printer(args.port, args.width) as printer:
        if args.command == "status":
            print(printer.status())
            return
        if args.command == "text":
            printer.text(args.message if args.message is not None else sys.stdin.read())
        elif args.command == "image":
            from PIL import Image

            printer.image(prepare_photo(Image.open(args.path)))
        elif args.command == "test":
            printer.image(test_pattern(args.width))
        printer.feed()
        if args.cut:
            printer.cut()


if __name__ == "__main__":
    main()
