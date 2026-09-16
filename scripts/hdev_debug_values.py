"""Bounded inspection of native serialized tuples, objects and HVCT vectors.

Only the vector envelope is parsed here. HALCON decodes every tuple/object,
including vector headers and element lengths. Child values are decoded on demand.
"""
import ctypes

import halcon as h


def deserialize(raw, iconic=False):
    if not raw:
        raise ValueError("Variable is not initialized at the current stop")
    buffer = ctypes.create_string_buffer(raw)
    item = h.create_serialized_item_ptr(ctypes.addressof(buffer), len(raw), "true")
    try:
        return h.deserialize_object(item) if iconic else h.deserialize_tuple(item)
    finally:
        h.clear_serialized_item(item)


class Vector:
    """A validated vector envelope, keeping child payloads as zero-copy views."""
    def __init__(self, raw, iconic, dimension):
        self.raw = memoryview(raw)
        self.position = 4
        self.iconic, self.dimension = iconic, dimension
        if self.raw[:4] != b"HVCT" or self.raw[-4:] != b"HVCT":
            raise ValueError("Unsupported vector serialization")
        header = self.read_tuple()
        if (len(header) != 4 or header[:3] != [1, int(iconic), dimension]
                or type(header[3]) is not int or not 0 <= header[3] <= 100000
                or not 1 <= dimension <= 64):
            raise ValueError("Unsupported vector header or inspection limit exceeded")
        self.children = []
        for _ in range(header[3]):
            length = self.read_tuple()
            if len(length) != 1 or type(length[0]) is not int or length[0] < 0:
                raise ValueError("Invalid vector element length")
            self.children.append(self.take(length[0]))
        if self.position != len(self.raw) - 4:
            raise ValueError("Unexpected data in vector serialization")

    def take(self, size):
        end = self.position + size
        if end > len(self.raw) - 4:
            raise ValueError("Truncated vector serialization")
        result = self.raw[self.position:end]
        self.position = end
        return result

    def read_tuple(self):
        # Serialized-item envelope: eight-byte marker and big-endian u64 length.
        header = self.take(16)
        if header[:8] != b'hUXhX}\x13"':
            raise ValueError("Unsupported serialized-item envelope")
        size = int.from_bytes(header[8:], "big")
        if size > 1024:  # Metadata is at most four integers, never user data.
            raise ValueError("Oversized vector metadata")
        return deserialize(bytes(header) + bytes(self.take(size)))

    def __len__(self):
        return len(self.children)

    def child(self, index):
        if not 0 <= index < len(self):
            raise ValueError("Vector index out of range (indices are zero-based)")
        raw = self.children[index]
        if not raw:
            raise ValueError("Vector element is not initialized")
        if self.dimension > 1:
            return Vector(raw, self.iconic, self.dimension - 1)
        return deserialize(bytes(raw), self.iconic)


def select_path(value, path):
    for index in path:
        if not isinstance(value, Vector):
            raise ValueError("Vector path is deeper than the variable's dimension")
        value = value.child(index)
    return value
