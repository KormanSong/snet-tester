"""SerialTransport -- pyserial wrapper implementing the Transport protocol.

Wraps a pyserial Serial instance with the Transport interface defined
in base.py. Absorbs flush() into write() so callers never need to
worry about it, and uses timeout=0 (non-blocking reads) to match
the polling-style I/O loop in comm/worker.py.
"""

import serial


class SerialTransport:
    """Concrete Transport backed by a real serial port.

    Parameters
    ----------
    port : str
        Serial port name (e.g. "COM6", "/dev/ttyUSB0").
    baud : int
        Baud rate (e.g. 115200).
    parity : str
        Parity setting. Default: serial.PARITY_ODD.
    stopbits : float
        Stop bits. Default: serial.STOPBITS_ONE.
    bytesize : int
        Data bits per byte. Default: serial.EIGHTBITS.
    """

    def __init__(
        self,
        port: str,
        baud: int,
        *,
        parity: str = serial.PARITY_ODD,
        stopbits: float = serial.STOPBITS_ONE,
        bytesize: int = serial.EIGHTBITS,
    ):
        self._port = port
        self._baud = baud
        self._parity = parity
        self._stopbits = stopbits
        self._bytesize = bytesize
        self._ser: serial.Serial | None = None

    # -- Lifecycle --

    def open(self) -> None:
        """Open the serial port with timeout=0 (non-blocking reads)."""
        self._ser = serial.Serial(
            self._port,
            self._baud,
            parity=self._parity,
            stopbits=self._stopbits,
            bytesize=self._bytesize,
            timeout=0,
        )

    def close(self) -> None:
        """Close the serial port if currently open."""
        if self._ser is not None:
            self._ser.close()
            self._ser = None

    # -- Data I/O --

    def write(self, data: bytes) -> None:
        """Write data and flush the output buffer.

        Parameters
        ----------
        data : bytes
            Raw bytes to transmit.

        Raises
        ------
        OSError
            If the port is not open.
        """
        if self._ser is None or not self._ser.is_open:
            raise OSError("SerialTransport: port is not open")
        self._ser.write(data)
        self._ser.flush()

    def read(self, size: int) -> bytes:
        """Read up to *size* bytes (non-blocking, may return fewer).

        Parameters
        ----------
        size : int
            Maximum number of bytes to read.

        Returns
        -------
        bytes
            Data read from the port; may be empty if nothing available.

        Raises
        ------
        OSError
            If the port is not open.
        """
        if self._ser is None or not self._ser.is_open:
            raise OSError("SerialTransport: port is not open")
        return self._ser.read(size)

    # -- Buffer management --

    @property
    def in_waiting(self) -> int:
        """Number of bytes available in the input buffer."""
        if self._ser is None or not self._ser.is_open:
            return 0
        return self._ser.in_waiting

    def reset_input_buffer(self) -> None:
        """Discard all data in the input (read) buffer."""
        if self._ser is not None and self._ser.is_open:
            self._ser.reset_input_buffer()

    def reset_output_buffer(self) -> None:
        """Discard all data in the output (write) buffer."""
        if self._ser is not None and self._ser.is_open:
            self._ser.reset_output_buffer()

    # -- Status --

    @property
    def is_open(self) -> bool:
        """Whether the serial port is currently open."""
        return self._ser is not None and self._ser.is_open
