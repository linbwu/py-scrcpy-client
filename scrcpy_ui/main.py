import os
import time
import struct
import socket
import threading
from argparse import ArgumentParser
from typing import Optional

from av import CodecContext
from adbutils import adb

from PySide6.QtGui import QImage, QKeyEvent, QMouseEvent, QPixmap  # pylint: disable=no-name-in-module
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox, QFileDialog  # pylint: disable=no-name-in-module
from PySide6.QtCore import Signal, QObject  # pylint: disable=no-name-in-module

import scrcpy

from .ui import UI

if not QApplication.instance():
    app = QApplication([])
else:
    app = QApplication.instance()


class TCPVideoReceiver(QObject):
    """Receive raw H264 video via TCP and emit decoded frames."""

    frame_received = Signal(object)

    def __init__(self, port: int):
        super().__init__()
        self.port = port
        self.alive = False
        self._socket: Optional[socket.socket] = None
        self._conn: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start listening for TCP H264 stream."""
        self.alive = True
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind(("127.0.0.1", self.port))
        self._socket.listen(1)
        self._socket.settimeout(0.5)
        self._thread = threading.Thread(target=self._receive_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the TCP receiver."""
        self.alive = False
        if self._conn:
            try:
                self._conn.close()
            except OSError:
                pass
            self._conn = None
        if self._socket:
            try:
                self._socket.close()
            except OSError:
                pass

    def _recv_exact(self, n: int) -> Optional[bytes]:
        """Receive exactly n bytes from the connection."""
        data = b""
        while len(data) < n:
            try:
                chunk = self._conn.recv(n - len(data))
                if not chunk:
                    return None
                data += chunk
            except socket.timeout:
                if not self.alive:
                    return None
                continue
            except socket.error:
                return None

        return data

    def _receive_loop(self) -> None:
        """Main loop: accept TCP connection and decode H264 frames."""
        codec = CodecContext.create("h264", "r")
        while self.alive:
            # Accept incoming TCP connection
            try:
                self._conn, _ = self._socket.accept()
                self._conn.settimeout(0.5)
            except socket.timeout:
                continue
            except OSError:
                break

            # Read framed messages from the connection
            while self.alive:
                header = self._recv_exact(4)
                if header is None:
                    break
                msg_len = struct.unpack(">I", header)[0]

                msg = self._recv_exact(msg_len)
                if msg is None:
                    break

                packets = codec.parse(msg)
                for packet in packets:
                    try:
                        frames = codec.decode(packet)
                        for frame in frames:
                            self.frame_received.emit(frame)
                    except Exception:
                        # Mid-stream join: decoder lacks SPS/PPS config,
                        # skip until IDR with parameter sets arrives.
                        continue

            # Connection closed, clean up
            if self._conn:
                try:
                    self._conn.close()
                except OSError:
                    pass
                print("client has disconnect")
                self._conn = None


class MainWindow(QMainWindow):
    """main window frame"""

    def __init__(self, max_width: Optional[int], serial: Optional[str] = None, tcp_port: Optional[int] = None):
        super().__init__()
        self.ui = UI(self)
        self.max_width = max_width
        self.img_path = ""
        self.alive = True
        self.resolution = None
        self.last_frame = None

        if tcp_port is not None:
            self._init_tcp_mode(tcp_port)
        else:
            self._init_adb_mode(serial)

    def _init_adb_mode(self, serial: Optional[str]) -> None:
        """Initialize ADB/scrcpy mode."""
        # Setup devices
        self.devices = self.list_devices()
        if serial:
            self.choose_device(serial)
        self.device = adb.device(serial=self.ui.combo_device.currentText())

        # Setup client
        self.client = scrcpy.Client(
            device=self.device,
            max_fps=30,
        )
        self.client.add_listener(scrcpy.EVENT_INIT, self.on_init)
        self.client.add_listener(scrcpy.EVENT_FRAME, self.on_frame)

        # Bind controllers
        self.ui.button_home.clicked.connect(self.on_click_home)
        self.ui.button_back.clicked.connect(self.on_click_back)
        self.ui.button_overview.clicked.connect(self.on_click_overview)
        self.ui.button_screenshot.clicked.connect(self.on_click_screenshot)

        # Bind config
        self.ui.combo_device.currentTextChanged.connect(self.choose_device)

        # Bind mouse event
        self.ui.label.mousePressEvent = self.on_mouse_event(scrcpy.ACTION_DOWN)
        self.ui.label.mouseMoveEvent = self.on_mouse_event(scrcpy.ACTION_MOVE)
        self.ui.label.mouseReleaseEvent = self.on_mouse_event(scrcpy.ACTION_UP)

        # Keyboard event
        self.keyPressEvent = self.on_key_event(scrcpy.ACTION_DOWN)
        self.keyReleaseEvent = self.on_key_event(scrcpy.ACTION_UP)

    def _init_tcp_mode(self, tcp_port: int) -> None:
        """Initialize TCP video receiver mode."""
        self.setWindowTitle(f"TCP Video Receiver (port: {tcp_port})")
        self.tcp_receiver = TCPVideoReceiver(tcp_port)
        self.tcp_receiver.frame_received.connect(self._on_tcp_frame)

        # ADB control buttons are not needed in TCP mode
        self.ui.button_home.setEnabled(False)
        self.ui.button_back.setEnabled(False)
        self.ui.button_overview.setEnabled(False)
        self.ui.combo_device.setEnabled(False)

        # Screenshot still works via last_frame
        self.ui.button_screenshot.clicked.connect(self._on_tcp_screenshot)

    def choose_device(self, device):
        """on choice device"""
        if device not in self.devices:
            msg_box = QMessageBox()
            msg_box.setText(f"Device serial [{device}] not found!")
            msg_box.exec()
            return

        # Ensure text
        self.ui.combo_device.setCurrentText(device)
        # Restart service
        if getattr(self, "client", None):
            self.client.stop()
            self.client.device = adb.device(serial=device)

    def list_devices(self):
        """list adb devices"""
        self.ui.combo_device.clear()
        items = [i.serial for i in adb.device_list()]
        self.ui.combo_device.addItems(items)
        return items

    # def on_flip(self, _):
    # self.client.flip = self.ui.flip.isChecked()

    def on_click_home(self):
        """click home"""
        self.client.control.keycode(scrcpy.KEYCODE_HOME, scrcpy.ACTION_DOWN)
        time.sleep(0.05)
        self.client.control.keycode(scrcpy.KEYCODE_HOME, scrcpy.ACTION_UP)

    def on_click_back(self):
        """click back"""
        self.client.control.back_or_turn_screen_on(scrcpy.ACTION_DOWN)
        time.sleep(0.05)
        self.client.control.back_or_turn_screen_on(scrcpy.ACTION_UP)

    def on_click_overview(self):
        """click app switch"""
        self.client.control.keycode(scrcpy.KEYCODE_APP_SWITCH, scrcpy.ACTION_DOWN)
        time.sleep(0.05)
        self.client.control.keycode(scrcpy.KEYCODE_APP_SWITCH, scrcpy.ACTION_UP)

    def on_click_screenshot(self):
        """save screenshot"""
        if not self.img_path:
            self.img_path = QFileDialog.getExistingDirectory(self, "选择保存截图的文件夹")

        # 检查是否选择了文件夹
        if self.img_path:
            filename = f"scrcpy_{time.strftime('%Y%m%d_%H%M%S')}.png"
            self.client.screenshot(os.path.join(self.img_path, filename))

    def on_mouse_event(self, action=scrcpy.ACTION_DOWN):
        """mouse event on frame"""

        def handler(evt: QMouseEvent):
            if self.client.resolution is None:
                return
            focused_widget = QApplication.focusWidget()
            if focused_widget is not None:
                focused_widget.clearFocus()
            ratio = self.max_width / max(self.client.resolution)
            self.client.control.touch(evt.position().x() / ratio, evt.position().y() / ratio, action)

        return handler

    def on_key_event(self, action=scrcpy.ACTION_DOWN):
        """key event on frame"""

        def handler(evt: QKeyEvent):
            code = self.map_code(evt.key())
            if code != -1:
                self.client.control.keycode(code, action)

        return handler

    def map_code(self, code):
        """
        Map qt keycode ti android keycode

        Args:
            code: qt keycode
            android keycode, -1 if not founded
        """

        if code == -1:
            return -1
        if 48 <= code <= 57:
            return code - 48 + 7
        if 65 <= code <= 90:
            return code - 65 + 29
        if 97 <= code <= 122:
            return code - 97 + 29

        hard_code = {
            32: scrcpy.KEYCODE_SPACE,
            16777219: scrcpy.KEYCODE_DEL,
            16777248: scrcpy.KEYCODE_SHIFT_LEFT,
            16777220: scrcpy.KEYCODE_ENTER,
            16777217: scrcpy.KEYCODE_TAB,
            16777249: scrcpy.KEYCODE_CTRL_LEFT,
        }
        if code in hard_code:
            return hard_code[code]

        print(f"Unknown keycode: {code}")
        return -1

    def on_init(self):
        """device init"""
        self.setWindowTitle(f"Serial: {self.client.device_name}")

    def on_frame(self, frame):
        """frame event"""
        app.processEvents()
        if frame is not None and self.client.resolution is not None:
            ratio = min(1, self.max_width / max(self.client.resolution))
            data = frame.to_ndarray(format="bgr24")
            image = QImage(
                data,
                data.shape[1],
                data.shape[0],
                data.shape[1] * 3,
                QImage.Format_BGR888,
            )
            pix = QPixmap(image)
            pix.setDevicePixelRatio(1 / ratio)
            self.ui.label.setPixmap(pix)
            self.resize(1, 1)

    def _on_tcp_frame(self, frame):
        """Handle decoded frame from TCP receiver."""
        if self.resolution is None:
            self.resolution = (frame.width, frame.height)
        self.last_frame = frame
        app.processEvents()
        if self.resolution is not None:
            ratio = min(1, self.max_width / max(self.resolution))
            data = frame.to_ndarray(format="bgr24")
            image = QImage(
                data,
                data.shape[1],
                data.shape[0],
                data.shape[1] * 3,
                QImage.Format_BGR888,
            )
            pix = QPixmap(image)
            pix.setDevicePixelRatio(1 / ratio)
            self.ui.label.setPixmap(pix)
            self.resize(1, 1)

    def _on_tcp_screenshot(self):
        """Save screenshot from TCP stream."""
        if self.last_frame is None:
            return
        if not self.img_path:
            self.img_path = QFileDialog.getExistingDirectory(self, "选择保存截图的文件夹")
        if self.img_path:
            filename = f"scrcpy_{time.strftime('%Y%m%d_%H%M%S')}.png"
            self.last_frame.save(os.path.abspath(os.path.join(self.img_path, filename)))

    def closeEvent(self, _):  # pylint: disable=invalid-name
        """close event, overwrite"""
        if hasattr(self, "client"):
            self.client.stop()
        if hasattr(self, "tcp_receiver"):
            self.tcp_receiver.stop()
        self.alive = False


def main():
    """main frame"""

    parser = ArgumentParser(description="A simple scrcpy client")
    parser.add_argument(
        "-m",
        "--max_width",
        type=int,
        default=800,
        help="Set max width of the window, default 800",
    )
    parser.add_argument(
        "-d",
        "--device",
        type=str,
        help="Select device manually (device serial required)",
    )
    parser.add_argument(
        "-t",
        "--tcp",
        type=int,
        default=None,
        help="TCP port to receive raw H264 video stream (127.0.0.1:<port>)",
    )
    args = parser.parse_args()

    m = MainWindow(args.max_width, args.device, args.tcp)
    m.show()

    if args.tcp is not None:
        # TCP mode: start receiver and run Qt event loop
        m.tcp_receiver.start()
        app.exec()
    else:
        # ADB mode: original scrcpy client loop with auto-reconnect
        m.client.start()
        while m.alive:
            try:
                m.client.start()
            except (ConnectionError, OSError) as e:
                print(f"Connection lost: {e}, retrying in 1s...")
                time.sleep(1)


if __name__ == "__main__":
    main()
