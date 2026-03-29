"""Transport protocol -- interface for serial and mock backends.

Defines the Transport structural protocol (PEP 544) that both
SerialTransport and MockTransport must satisfy. Using Protocol
instead of ABC enables duck-typing without forced inheritance.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class Transport(Protocol):
    """Structural interface for serial-like I/O backends.

    Implementors must provide open/close lifecycle, read/write data,
    and buffer management methods matching pyserial's Serial API.
    """

    def open(self) -> None:
        """Open the underlying connection."""
        ...

    def close(self) -> None:
        """Close the underlying connection."""
        ...

    def write(self, data: bytes) -> None:
        """Write data to the transport."""
        ...

    def read(self, size: int) -> bytes:
        """Read up to `size` bytes. May return fewer."""
        ...

    @property
    def in_waiting(self) -> int:
        """Number of bytes available to read without blocking."""
        ...

    def reset_input_buffer(self) -> None:
        """Discard all data in the input (read) buffer."""
        ...

    def reset_output_buffer(self) -> None:
        """Discard all data in the output (write) buffer."""
        ...

    @property
    def is_open(self) -> bool:
        """Whether the transport connection is currently open."""
        ...
