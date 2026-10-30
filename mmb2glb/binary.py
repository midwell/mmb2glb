"""Bounds-checked little-endian binary reading."""
import math
import struct
from pathlib import Path


class FormatError(ValueError):
    """An input is malformed or uses an unsupported format variant."""


class Reader:
    def __init__(self, path):
        self.path = Path(path)
        self.data = self.path.read_bytes()
        self.pos = 0

    def fail(self, message):
        raise FormatError(f"{self.path.name} at 0x{self.pos:x}: {message}")

    def take(self, size):
        if size < 0 or self.pos + size > len(self.data):
            self.fail(f"truncated input (need {size} bytes)")
        value = self.data[self.pos:self.pos + size]
        self.pos += size
        return value

    def unpack(self, fmt):
        values = struct.unpack('<' + fmt, self.take(struct.calcsize('<' + fmt)))
        if any(isinstance(v, float) and not math.isfinite(v) for v in values):
            self.fail('non-finite numeric value')
        return values

    def u32(self):
        return self.unpack('I')[0]

    def string(self):
        size = self.unpack('H')[0]
        try:
            value = self.take(size).decode('utf-8')
        except UnicodeDecodeError:
            self.fail('invalid UTF-8 name')
        if '\0' in value:
            self.fail('embedded NUL in name')
        return value

    def count(self, minimum_size=1):
        count = self.u32()
        if count > (len(self.data) - self.pos) // minimum_size:
            self.fail(f'impossible record count {count}')
        return count

    def end(self):
        if self.pos != len(self.data):
            self.fail(f'{len(self.data) - self.pos} unconsumed bytes')
