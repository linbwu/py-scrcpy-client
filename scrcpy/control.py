"""control module for scrcpy client

references:
    https://github.com/Genymobile/scrcpy/blob/master/app/tests/test_control_msg_serialize.c
    https://github.com/Genymobile/scrcpy/blob/master/app/src/control_msg.c
    https://github.com/Genymobile/scrcpy/blob/master/app/src/input_manager.c
"""

import functools
import socket
import struct
from time import sleep

from . import const, calculate


def inject(control_type: int):
    """
    Inject control code, with this inject, we will be able to do unit test

    Args:
        control_type: event to send, TYPE_*
    """

    def wrapper(f):
        @functools.wraps(f)
        def inner(*args, **kwargs):
            package = struct.pack(">B", control_type) + f(*args, **kwargs)
            if args[0].parent.control_socket is not None:
                with args[0].parent.control_socket_lock:
                    args[0].parent.control_socket.send(package)
            return package

        return inner

    return wrapper


class ControlSender:
    """control sender class"""

    def __init__(self, parent):
        self.parent = parent
        self._clipboard_sequence = 0

    @inject(const.TYPE_INJECT_KEYCODE)
    def keycode(
        self, keycode: int, action: int = const.ACTION_DOWN, repeat: int = 1, meta: int = const.META_NONE
    ) -> bytes:
        """
        Send keycode to device

        Args:
            keycode: const.KEYCODE_*
            action: ACTION_DOWN | ACTION_UP
            repeat: repeat count
            meta: const.META_NONE | META_SHIFT_ON | META_ALT_ON | META_SYM_ON
        """
        return struct.pack(">Biii", action, keycode, repeat, meta)

    @inject(const.TYPE_INJECT_TEXT)
    def text(self, text: str) -> bytes:
        """
        Send text to device

        Args:
            text: text to send
        """

        buffer = text.encode("utf-8")
        return struct.pack(">i", len(buffer)) + buffer

    @inject(const.TYPE_INJECT_TOUCH_EVENT)
    def touch(
        self, x: int, y: int, action: int = const.ACTION_DOWN, touch_id: int = const.SC_POINTER_ID_MOUSE
    ) -> bytes:
        """
        Touch screen

        Args:
            x: horizontal position
            y: vertical position
            action: ACTION_DOWN | ACTION_UP | ACTION_MOVE
            touch_id: Default using virtual id -1, you can specify it to emulate multi finger touch
        """
        if self.parent.resolution is None:
            raise ValueError("Resolution is not known yet")
        x, y = max(int(x), 0), max(int(y), 0)
        return struct.pack(
            ">BqiiHHHii",
            action,
            touch_id,
            x,
            y,
            int(self.parent.resolution[0]),
            int(self.parent.resolution[1]),
            0xFFFF,  # pressure
            const.AMOTION_EVENT_BUTTON_PRIMARY,
            const.AMOTION_EVENT_BUTTON_PRIMARY,
        )

    def click(self, x: int, y: int, duration: int = 200) -> None:
        """
        Click on screen

        Args:
            x: horizontal position
            y: vertical position
            duration: press duration in ms
        :return:
        """

        self.touch(x, y, const.ACTION_DOWN)
        sleep(duration / 1000)
        self.touch(x, y, const.ACTION_UP)

    @inject(const.TYPE_INJECT_SCROLL_EVENT)
    def scroll(self, x: int, y: int, h: int = 16, v: int = -16) -> bytes:
        """
        Scroll screen

        Args:
            x: horizontal position
            y: vertical position
            h: horizontal movement
            v: vertical movement
        """
        if self.parent.resolution is None:
            raise ValueError("Resolution is not known yet")

        x, y = max(int(x), 0), max(int(y), 0)
        return struct.pack(
            ">iiHHHHi",
            x,
            y,
            int(self.parent.resolution[0]),
            int(self.parent.resolution[1]),
            calculate.float_toi16(h / 16.0),
            calculate.float_toi16(v / 16.0),
            const.AMOTION_EVENT_BUTTON_PRIMARY,
        )

    @inject(const.TYPE_BACK_OR_SCREEN_ON)
    def back_or_turn_screen_on(self, action: int = const.ACTION_DOWN) -> bytes:
        """
        If the screen is off, it is turned on only on ACTION_DOWN

        Args:
            action: ACTION_DOWN | ACTION_UP
        """
        return struct.pack(">B", action)

    @inject(const.TYPE_EXPAND_NOTIFICATION_PANEL)
    def expand_notification_panel(self) -> bytes:
        """
        Expand notification panel
        """
        return b""

    @inject(const.TYPE_EXPAND_SETTINGS_PANEL)
    def expand_settings_panel(self) -> bytes:
        """
        Expand settings panel
        """
        return b""

    @inject(const.TYPE_COLLAPSE_PANELS)
    def collapse_panels(self) -> bytes:
        """
        Collapse all panels
        """
        return b""

    def get_clipboard(self, timeout=2000) -> str:
        """
        Get clipboard

        timeout: timeout in ms

        clipboard_autosync must be disabled
        """
        # Since this function need socket response, we can't auto inject it any more
        s: socket.socket = self.parent.control_socket

        with self.parent.control_socket_lock:
            # Flush socket
            s.setblocking(False)
            while True:
                try:
                    s.recv(1024)
                except BlockingIOError:
                    break
            s.setblocking(True)

            # Read package
            package = struct.pack(">BB", const.TYPE_GET_CLIPBOARD, const.SC_COPY_KEY_COPY)
            s.send(package)

            s.setblocking(False)
            for _ in range(int(timeout / 200)):
                try:
                    (code,) = struct.unpack(">B", s.recv(1))
                    break
                except BlockingIOError:
                    sleep(0.2)
            else:
                s.setblocking(True)
                # timeout
                return ""
                # raise ConnectionError("Failed to connect scrcpy-server after 3 seconds")
            s.setblocking(True)
            assert code == const.TYPE_CLIPBOARD, "Invalid clipboard response code"
            (length,) = struct.unpack(">i", s.recv(4))
            if length == 0:
                return ""

            return s.recv(length).decode("utf-8")

    @inject(const.TYPE_SET_CLIPBOARD)
    def set_clipboard(self, text: str, paste: bool = False) -> bytes:
        """
        Set clipboard

        Args:
            text: the string you want to set
            paste: paste now
        """
        buffer = text.encode("utf-8")
        if len(buffer) > const.SC_CONTROL_MSG_INJECT_TEXT_MAX_LENGTH:
            raise ValueError(f"Text length exceeds maximum {const.SC_CONTROL_MSG_INJECT_TEXT_MAX_LENGTH}")

        self._clipboard_sequence += 1
        return struct.pack(">q?i", self._clipboard_sequence, paste, len(buffer)) + buffer

    @inject(const.TYPE_SET_DISPLAY_POWER)
    def set_display_power(self, on: bool = True) -> bytes:
        """
        Set display power

        Args:
            on: True for on, False for off(when wake_up is True, the screen will be turned on immediately)
        """
        return struct.pack(">b", int(on))

    @inject(const.TYPE_ROTATE_DEVICE)
    def rotate_device(self) -> bytes:
        """
        Rotate device
        """
        return b""

    def swipe(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        move_step_length: int = 5,
        move_steps_delay: float = 0.005,
    ) -> None:
        """
        Swipe on screen

        Args:
            start_x: start horizontal position
            start_y: start vertical position
            end_x: start horizontal position
            end_y: end vertical position
            move_step_length: length per step
            move_steps_delay: sleep seconds after each step
        :return:
        """
        if not self.parent.resolution:
            raise ValueError("Resolution is not known yet")
        start_x, start_y = max(int(start_x), 0), max(int(start_y), 0)
        self.touch(start_x, start_y, const.ACTION_DOWN)
        next_x = start_x
        next_y = start_y

        end_x, end_y = min(int(end_x), int(self.parent.resolution[0])), min(int(end_y), int(self.parent.resolution[1]))

        decrease_x, decrease_y = start_x > end_x, start_y > end_y
        while True:
            if decrease_x:
                next_x -= move_step_length
                next_x = max(next_x, end_x)
            else:
                next_x += move_step_length
                next_x = min(next_x, end_x)

            if decrease_y:
                next_y -= move_step_length
                next_y = max(next_y, end_y)
            else:
                next_y += move_step_length
                next_y = min(next_y, end_y)

            self.touch(next_x, next_y, const.ACTION_MOVE)

            if next_x == end_x and next_y == end_y:
                self.touch(next_x, next_y, const.ACTION_UP)
                break
            sleep(move_steps_delay)
