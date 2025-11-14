import os
import socket
import logging
import threading
import time
from time import sleep
from typing import Any, Callable, Optional, Union, Tuple

from adbutils import AdbConnection, AdbDevice, AdbError, AdbTimeout, Network, adb
from av import CodecContext, VideoFrame

from .const import (
    EVENT_DISCONNECT,
    EVENT_FRAME,
    EVENT_INIT,
    SCRCPY_VERSION,
    SCRCPY_LOCAL_NAME,
    SCRCPY_JAR_NAME,
)
from .control import ControlSender


class Client:
    """
    Create a scrcpy client, this client won't be started until you call the start function

    Args:
        device: Android device, select first one if none, from serial if str
        max_width: frame width that will be broadcast from android server
        max_fps: maximum fps, 0 means not limited (supported after android 10)
        bitrate: video_bit_rate
        block_frame: only return nonempty frames, may block cv2 render thread
        stay_awake: keep Android device awake
        lock_screen_orientation: lock screen orientation, LOCK_SCREEN_ORIENTATION_*
        connection_timeout: timeout for connection, unit is ms
    """

    def __init__(
        self,
        device: Optional[Union[AdbDevice, str, any]] = None,
        max_width: int = 0,
        bitrate: int = 8000000,
        max_fps: int = 0,
        block_frame: bool = False,
        stay_awake: bool = True,
        connection_timeout: int = 3000,
        logger: logging.Logger = None,
    ):
        # Check Params
        assert max_width >= 0, "max_width must be greater than or equal to 0"
        assert bitrate >= 0, "bitrate must be greater than or equal to 0"
        assert max_fps >= 0, "max_fps must be greater than or equal to 0"
        assert connection_timeout >= 0, "connection_timeout must be greater than or equal to 0"

        # Params
        self.max_width = max_width
        self.bitrate = bitrate
        self.max_fps = max_fps
        self.block_frame = block_frame
        self.stay_awake = stay_awake
        self.connection_timeout = connection_timeout
        self._device = device

        self.logger = logger or logging.getLogger("scrcpy")

        self.device: Optional[AdbDevice]  = None
        self.listeners = {
            EVENT_FRAME: [],
            EVENT_INIT: [],
            EVENT_DISCONNECT: [],
        }

        # User accessible
        self.last_frame: Optional[VideoFrame] = None
        self.resolution: Optional[Tuple[int, int]] = None  # used in ControlSender
        self._frame_locker = threading.Lock()  # for last_frame access
        self.device_name: Optional[str] = None
        self.control = ControlSender(self)

        # Need to destroy
        self.alive = False
        self.__server_stream: Optional[AdbConnection] = None
        self.__video_socket: Optional[socket.socket] = None
        self.control_socket: Optional[socket.socket] = None
        self.control_socket_lock = threading.Lock()  # used in ControlSender

        # Available if start with threaded or daemon_threaded
        self.stream_loop_thread = None

    def __del__(self):
        self.stop()

    @property
    def serial(self) -> str:
        """device serial"""
        self.__init_device()
        return self.device.serial

    def __init_device(self) -> None:
        """
        Initialize device connection
        """
        if self.device:
            return

        # Connect to device
        if self._device is None:
            for dev in adb.iter_device():
                self.device = dev
                break
        elif isinstance(self._device, str):
            self.device = adb.device(serial=self._device)
        elif isinstance(self._device, AdbDevice):
            self.device = self._device
        if self.device is None:
            raise ConnectionError("No available device found")
        self.logger.debug(f"adb device[{self.device.serial}] raedy")

    def __init_server_connection(self) -> None:
        """
        Connect to android server, there will be two sockets, video and control socket.
        This method will set: video_socket, control_socket, resolution variables
        """
        self.logger.debug("connect video scocket...")
        for _ in range(self.connection_timeout // 200):
            try:
                self.__video_socket = self.device.create_connection(Network.LOCAL_ABSTRACT, "scrcpy")
                break
            except AdbError:
                sleep(0.2)
        else:
            raise ConnectionError(f"Failed to connect scrcpy-server within {self.connection_timeout}ms")

        self.logger.debug("connect control scocket...")
        self.control_socket = self.device.create_connection(Network.LOCAL_ABSTRACT, "scrcpy")

        self.__video_socket.setblocking(False)
        for _ in range(self.connection_timeout // 200):
            try:
                dummy_byte = self.__video_socket.recv(1)
                break
            except BlockingIOError:
                sleep(0.2)
        else:
            raise TimeoutError("Receive Dummy Byte Timeout")

        if not dummy_byte or dummy_byte != b"\x00":
            raise ConnectionError(f"Unexpected Dummy Byte! {dummy_byte}")

        self.logger.debug("all connections has ready")

    def __deploy_server(self) -> None:
        """
        Deploy server to android device
        """
        remote_name = f"/data/local/tmp/{SCRCPY_JAR_NAME}"
        server_file_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), SCRCPY_LOCAL_NAME)
        self.device.sync.push(server_file_path, remote_name)
        commands = [
            f"CLASSPATH={remote_name}",
            "app_process",
            "/",
            "com.genymobile.scrcpy.Server",
            SCRCPY_VERSION,  # Scrcpy server version
            "log_level=info",  # Log level: info, verbose...
            "tunnel_forward=true",  # Tunnel forward
            "video=true",  # Video enabled
            "audio=false",  # Audio disabled
            "control=true",  # Control enabled
            "clipboard_autosync=false",  # Disable clipboard autosync
            "stay_awake=true" if self.stay_awake else "stay_awake=false",  # Stay awake
            "raw_stream=true",  # Use raw stream
            "power_off_on_close=false",  # Power off screen after server closed
        ]
        if self.max_width > 0:
            commands.append(f"max_size={self.max_width}")  # Max screen width (long side)
        if self.max_fps > 0:
            commands.append(f"max_fps={self.max_fps}")  # Max frame per second
        if self.bitrate > 0:
            commands.append(f"video_bit_rate={self.bitrate}")  # Video bit rate

        self.logger.debug(f"Starting scrcpy server with command:{' '.join(commands)}")
        self.__server_stream: AdbConnection = self.device.shell(
            commands,
            stream=True,
        )

        # Wait for server to start
        buffer = bytearray()
        while True:
            try:
                chunk = self.__server_stream.recv(1)
                buffer.extend(chunk)
                if b"\n" in chunk and b"INFO" in buffer:
                    break
            except AdbTimeout:
                break

        lines = buffer.decode(errors="ignore").splitlines()
        for line in lines:
            # maybe check "WARN" in line?
            self.logger.debug(line)
            if "Device:" in line:
                self.device_name = line.split("Device:")[-1].strip()
                break
        self.logger.debug("scrcpy server has ready")

    def start(self, threaded: bool = False, daemon_threaded: bool = False) -> None:
        """
        Start listening video stream

        Args:
            threaded: Run stream loop in a different thread to avoid blocking
            daemon_threaded: Run stream loop in a daemon thread to avoid blocking
        """
        assert self.alive is False

        self.resolution = None
        self.__init_device()
        self.__deploy_server()
        self.__init_server_connection()
        self.__send_to_listeners(EVENT_INIT)

        if threaded or daemon_threaded:
            self.stream_loop_thread = threading.Thread(target=self.__stream_loop_silence, daemon=daemon_threaded)
            self.stream_loop_thread.start()
        else:
            self.__stream_loop()

    def stop(self) -> None:
        """
        Stop listening (both threaded and blocked)
        """
        self.alive = False
        if self.__server_stream is not None:
            try:
                self.__server_stream.close()
            except Exception:
                pass

        if self.control_socket is not None:
            try:
                self.control_socket.close()
            except Exception:
                pass

        if self.__video_socket is not None:
            try:
                self.__video_socket.close()
            except Exception:
                pass

    def wait_for_ready(self, timeout: int = 3000) -> None:
        """
        Wait until client receive one frame

        Args:
            timeout: maximum wait time in ms, 0 means wait forever
        """
        start_time = time.time()
        while not self.resolution:
            sleep(0.2)
            if timeout and (time.time() - start_time) * 1000 > timeout:
                raise TimeoutError("Wait for client alive timeout")

    def __stream_loop(self) -> None:
        """
        Core loop for video parsing
        """
        codec = CodecContext.create("h264", "r")
        self.alive = True  # status change to alive
        while self.alive:
            try:
                raw_h264 = self.__video_socket.recv(0x10000)
                if raw_h264 == b"":
                    raise ConnectionError("Video stream is disconnected")
                packets = codec.parse(raw_h264)
                for packet in packets:
                    frames = codec.decode(packet)
                    for frame in frames:
                        if not self._frame_locker.locked():
                            self.last_frame = frame
                        if not self.resolution:
                            self.resolution = (frame.width, frame.height)
                            self.logger.debug(f"resolution: {self.resolution}")
                        self.__send_to_listeners(EVENT_FRAME, frame)
            except BlockingIOError:
                time.sleep(0.01)
                if not self.block_frame:
                    self.__send_to_listeners(EVENT_FRAME, None)
            except (ConnectionError, OSError) as e:  # Socket Closed
                if self.alive:
                    self.__send_to_listeners(EVENT_DISCONNECT)
                    self.stop()
                    raise e

    def __stream_loop_silence(self):
        try:
            self.__stream_loop()
        except (ConnectionError, OSError) as e:
            self.logger.warning(e)

    def add_listener(self, cls: str, listener: Callable[..., Any]) -> None:
        """
        Add a video listener

        Args:
            cls: Listener category, support: init, frame
            listener: A function to receive frame np.ndarray
        """
        self.listeners[cls].append(listener)

    def remove_listener(self, cls: str, listener: Callable[..., Any]) -> None:
        """
        Remove a video listener

        Args:
            cls: Listener category, support: init, frame
            listener: A function to receive frame np.ndarray
        """
        self.listeners[cls].remove(listener)

    def __send_to_listeners(self, cls: str, *args, **kwargs) -> None:
        """
        Send event to listeners

        Args:
            cls: Listener type
            *args: Other arguments
            *kwargs: Other arguments
        """
        for fun in self.listeners[cls]:
            fun(*args, **kwargs)

    def screenshot(self, filepath: str) -> bool:
        """
        Take a screenshot from the last frame
        """
        with self._frame_locker:
            if self.last_frame is not None:
                fullpath = os.path.abspath(filepath)
                dirname = os.path.dirname(fullpath)
                if dirname and not os.path.exists(dirname):
                    os.makedirs(dirname)
                self.last_frame.save(fullpath)
                return True

        return False
