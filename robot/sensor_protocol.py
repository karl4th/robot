"""Version 1 serial frames: integer CSV plus CRC-16/CCITT-FALSE."""
import binascii
import re


def decode_frame(text, tag, count, allowed_flags):
    if len(text) > 240:
        raise ValueError('Frame too long')
    body, separator, checksum = text.rpartition('*')
    if not separator or not re.fullmatch(r'[0-9A-Fa-f]{4}', checksum):
        raise ValueError('Missing CRC16')
    if binascii.crc_hqx(body.encode('ascii'), 0xFFFF) != int(checksum, 16):
        raise ValueError('CRC16 mismatch')
    fields = body.split(',')
    if len(fields) != count or fields[0] != tag or not all(re.fullmatch(r'-?\d{1,10}', f) for f in fields[1:]):
        raise ValueError('Malformed versioned frame')
    values = list(map(int, fields[1:]))
    seq, timestamp, flags = values[:3]
    if not 0 <= seq <= 0xFFFFFFFF or not 0 <= timestamp <= 0xFFFFFFFF:
        raise ValueError('Invalid counter')
    if flags < 0 or flags & ~allowed_flags or not flags & 1:
        raise ValueError('Invalid configuration flags')
    return values
