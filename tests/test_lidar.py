import struct
import unittest

from robot.lidar import Parser, crc8


def frame():
    data = struct.pack("<BBHH", 0x54, 0x2C, 3600, 35900)
    data += b"".join(struct.pack("<HB", 1000 + i, 90) for i in range(12))
    data += struct.pack("<HH", 100, 1234)
    return data + bytes([crc8(data)])


class ParserTests(unittest.TestCase):
    def test_crc_polynomial(self):
        self.assertEqual(crc8(b"\x01"), 0x4D)
        self.assertEqual(crc8(b"\x02"), 0x9A)

    def test_fragmented_frame_and_angle_wrap(self):
        parser = Parser()
        packets = []
        for byte in frame():
            packets.extend(parser.feed(bytes([byte])))
        self.assertEqual(len(packets), 1)
        packet = packets[0]
        self.assertEqual(packet.timestamp_ms, 1234)
        self.assertEqual(packet.speed_deg_s, 3600)
        self.assertEqual(packet.points[0].angle_deg, 359)
        self.assertEqual(packet.points[-1].angle_deg, 1)
        self.assertEqual(packet.points[-1].distance_mm, 1011)

    def test_corruption_and_noise_recovery(self):
        parser = Parser()
        damaged = bytearray(frame())
        damaged[8] ^= 1
        packets = parser.feed(b"noise\x54" + damaged + frame() + frame())
        self.assertEqual(len(packets), 2)
        self.assertEqual(parser.bad_crc, 1)

    def test_split_header_and_bounded_noise(self):
        parser = Parser()
        self.assertEqual(parser.feed(b"x" * 10000 + b"\x54"), [])
        self.assertEqual(len(parser.buffer), 1)
        self.assertEqual(len(parser.feed(frame()[1:])), 1)


if __name__ == "__main__":
    unittest.main()
