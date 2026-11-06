"""frames.py -- the replay datasets' frame format: lossless, about 440 KB per Pilatus2M frame (originals 9.9 MB).

A frame is stored as int16 (checked exact: Pilatus counts and the -1/-2 gap and bad-pixel flags fit), byte-shuffled
(all low bytes, then all high bytes) and xz-compressed. decode() returns the original int32 array; write_tiff()
writes it as an uncompressed int32 tiff, the pixel format the detector writes, so the analysis reads exactly the
values it read live.
"""
import hashlib, lzma

import numpy as np
from PIL import Image


def encode(a):
    """int32 array -> bytes; refuses any value that int16 cannot hold."""
    b = a.astype(np.int16)
    if not np.array_equal(b.astype(a.dtype), a):
        raise ValueError("frame values outside int16: min %d max %d" % (a.min(), a.max()))
    shuf = np.frombuffer(b.tobytes(), np.uint8).reshape(-1, 2).T.copy().tobytes()
    return lzma.compress(shuf, preset=9 | lzma.PRESET_EXTREME)


def decode(data, shape, dtype="int32"):
    raw = np.frombuffer(lzma.decompress(data), np.uint8)
    b = raw.reshape(2, -1).T.copy().view(np.int16)
    return b.reshape(shape).astype(dtype)


def pixel_md5(a):
    """md5 of the pixel values as int32 (independent of the file format)."""
    return hashlib.md5(np.ascontiguousarray(a, dtype=np.int32).tobytes()).hexdigest()


def read_tiff(path):
    with Image.open(path) as im:
        return np.array(im)


def write_tiff(a, path):
    Image.fromarray(np.ascontiguousarray(a, dtype=np.int32)).save(path)


def load(path, shape, dtype="int32"):
    with open(path, "rb") as fh:
        return decode(fh.read(), shape, dtype)
