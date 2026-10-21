#!/usr/bin/env python3
"""Inspect MP4 track handlers and fragmentation for local video validation."""
from __future__ import annotations

import struct


class Mp4Error(ValueError):
    """The bytes are not an MP4 this module can read."""


def _boxes(data, start, end):
    """(type, box start, header size, box end) for each box in data[start:end]."""
    position = start
    while position < end:
        if end - position < 8:
            raise Mp4Error("truncated box header")
        size, kind = struct.unpack_from(">I4s", data, position)
        header = 8
        if size == 1:
            if end - position < 16:
                raise Mp4Error("truncated 64-bit box header")
            size = struct.unpack_from(">Q", data, position + 8)[0]
            header = 16
        elif size == 0:
            size = end - position
        if size < header or position + size > end:
            raise Mp4Error(f"box {kind!r} overruns its parent")
        yield kind, position, header, position + size
        position += size


def _child(data, box, kind):
    _, start, header, end = box
    for found in _boxes(data, start + header, end):
        if found[0] == kind:
            return found
    return None


def _path(data, box, *kinds):
    for kind in kinds:
        if box is None:
            return None
        box = _child(data, box, kind)
    return box


def _handler(data, trak):
    hdlr = _path(data, trak, b"mdia", b"hdlr")
    if hdlr is None or hdlr[3] - hdlr[1] - hdlr[2] < 12:
        raise Mp4Error("a track has no handler")
    return bytes(data[hdlr[1] + hdlr[2] + 8: hdlr[1] + hdlr[2] + 12])


def scan(data):
    """{'tracks': [handler types], 'fragmented': bool} without changing anything."""
    top = list(_boxes(data, 0, len(data)))
    moov = [box for box in top if box[0] == b"moov"]
    if len(moov) != 1:
        raise Mp4Error("expected exactly one moov box")
    tracks = [_handler(data, box).decode("latin-1") for box in _boxes(data, moov[0][1] + moov[0][2], moov[0][3])
              if box[0] == b"trak"]
    return {"tracks": tracks, "fragmented": any(box[0] == b"moof" for box in top)}
