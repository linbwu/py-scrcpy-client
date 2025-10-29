"""control module for scrcpy client

references:
    https://github.com/Genymobile/scrcpy/blob/master/app/tests/test_control_msg_serialize.c
    https://github.com/Genymobile/scrcpy/blob/master/app/src/control_msg.c
    https://github.com/Genymobile/scrcpy/blob/master/app/src/input_manager.c
"""

import functools
import socket
import struct
import math
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
        self._clipboard_sequence: int = 0

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
        self,
        x: int,
        y: int,
        action: int = const.ACTION_DOWN,
        touch_id: int = const.SC_POINTER_ID_MOUSE,
        pressure: float = 1.0,
    ) -> bytes:
        """
        Touch screen

        Args:
            x: horizontal position
            y: vertical position
            action: ACTION_DOWN | ACTION_UP | ACTION_MOVE
            touch_id: Default using virtual id -1, you can specify it to emulate multi finger touch
            pressure: 0.0 - 1.0
        """
        if self.parent.resolution is None:
            raise ValueError("Resolution is not known yet")
        max_x, max_y = int(self.parent.resolution[0]), int(self.parent.resolution[1])
        x, y = min(max(int(x), 0), max_x), min(max(int(y), 0), max_y)

        return struct.pack(
            ">BqiiHHHii",
            action,
            touch_id,
            x,
            y,
            max_x,
            max_y,
            calculate.float_to_u16(int(pressure)),  # 0xFFFF,  # pressure
            const.AMOTION_EVENT_BUTTON_PRIMARY,
            const.AMOTION_EVENT_BUTTON_PRIMARY,
        )

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

        max_x, max_y = int(self.parent.resolution[0]), int(self.parent.resolution[1])
        x, y = min(max(int(x), 0), max_x), min(max(int(y), 0), max_y)

        return struct.pack(
            ">iiHHHHi",
            x,
            y,
            max_x,
            max_y,
            calculate.float_to_i16(h / 16.0),
            calculate.float_to_i16(v / 16.0),
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

        timeout: timeout in milliseconds

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

            # Read package
            package = struct.pack(">BB", const.TYPE_GET_CLIPBOARD, const.SC_COPY_KEY_COPY)
            s.send(package)

            def _get_resp_code():
                for _ in range(timeout // 200):
                    try:
                        (c,) = struct.unpack(">B", s.recv(1))
                        return c
                    except BlockingIOError:
                        sleep(0.2)
                else:
                    raise TimeoutError

            try:
                code = _get_resp_code()
            except TimeoutError:
                raise TimeoutError(f"get clipboard timeout in {timeout}ms")
            finally:
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
        delay: int = 0,
        move_step_length: int = 10,
        move_steps_delay: int = 5,
    ) -> None:
        """
        Swipe on screen

        Args:
            start_x: start horizontal position
            start_y: start vertical position
            end_x: start horizontal position
            end_y: end vertical position
            delay: press and hold milliseconds before move
            move_step_length: length per step. If you want to swipe quickly, set this value higher, such as 40
            move_steps_delay: sleep milliseconds after each step
        :return:
        """
        if not self.parent.resolution:
            raise ValueError("Resolution is not known yet")
        max_x, max_y = int(self.parent.resolution[0]), int(self.parent.resolution[1])
        start_x, start_y = min(max(int(start_x), 0), max_x), min(max(int(start_y), 0), max_y)
        end_x, end_y = min(max(int(end_x), 0), max_x), min(max(int(end_y), 0), max_y)

        self.touch(start_x, start_y, const.ACTION_DOWN)
        sleep(max(int(delay), int(move_steps_delay)) / 1000)

        hypotenuse = math.sqrt((end_x - start_x) ** 2 + (end_y - start_y) ** 2)
        steps_num = max(int(hypotenuse / move_step_length + 0.5), 1)
        next_x, next_y = float(start_x), float(start_y)
        step_x, step_y = (end_x - start_x) / steps_num, (end_y - start_y) / steps_num

        # moving action steps
        steps_num -= 1
        for _ in range(steps_num):
            next_x += step_x
            next_y += step_y
            self.touch(int(next_x), int(next_y), const.ACTION_MOVE)
            sleep(move_steps_delay / 1000)

        # up action
        next_x += step_x
        next_y += step_y
        self.touch(int(next_x), int(next_y), const.ACTION_UP)
