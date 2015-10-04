from __future__ import division, print_function

import unittest
import io
import struct
import zlib
import numpy as np
from numpy.testing import assert_, assert_equal, assert_array_equal
import pngw


def next_chunk(s):
    chunk_len = struct.unpack("!I", s[:4])[0]
    chunk_type = s[4:8]
    chunk_data = s[8:8+chunk_len]
    crc = struct.unpack("!I", s[8+chunk_len:8+chunk_len+4])[0]
    check = zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF
    if crc != check:
        raise RuntimeError("CRC not correct, chunk_type=%r" % (chunk_type,))
    return chunk_type, chunk_data, s[8+chunk_len+4:]


def check_signature(s):
    signature = s[:8]
    s = s[8:]
    assert_equal(signature, b'\x89PNG\x0D\x0A\x1A\x0A')
    return s


def check_ihdr(file_contents, width, height, bit_depth, color_type,
               compression_method=0, filter_method=0, interface_method=0):
    chunk_type, chunk_data, file_contents = next_chunk(file_contents)
    assert_equal(chunk_type, b"IHDR")
    values = struct.unpack("!IIBBBBB", chunk_data)
    expected = (width, height, bit_depth, color_type, compression_method,
                filter_method, interface_method)
    assert_equal(values, expected)
    return file_contents


def check_trns(file_contents, color_type, transparent):
    chunk_type, chunk_data, file_contents = next_chunk(file_contents)
    assert_equal(chunk_type, b"tRNS")
    assert_(color_type not in [4, 6],
            msg='Found tRNS chunk, but color_type is %r' % (color_type,))
    if color_type == 0:
        # Grayscale
        trns = struct.unpack("!H", chunk_data)[0]
        assert_equal(trns, transparent)
    elif color_type == 2:
        # RGB
        trns = struct.unpack("!HHH", chunk_data)
        assert_equal(trns, transparent)
    elif color_type == 3:
        # alphas for the first len(chunk_data) palette indices.
        trns = np.fromstring(chunk_data, dtype=np.uint8)
        # TODO: Write a test for the case use_palette=True and
        #       transparent is not None.
        assert_(False, msg="This test is not complete!")
    else:
        raise RuntimeError("check_trns called with invalid color_type %r" %
                           (color_type,))
    return file_contents


def check_idat(file_contents, color_type, bit_depth, img):
    # This function assumes the entire image is in the chunk.
    chunk_type, chunk_data, file_contents = next_chunk(file_contents)
    assert_equal(chunk_type, b"IDAT")
    decompressed = zlib.decompress(chunk_data)
    stream = np.fromstring(decompressed, dtype=np.uint8)
    height, width = img.shape[:2]
    img2 = stream_to_array(stream, width, height, color_type, bit_depth)
    assert_array_equal(img2, img)
    return file_contents


def stream_to_array(stream, width, height, color_type, bit_depth):
    # `stream` is 1-d numpy array with dytpe np.uint8 containing the
    # data from one or more IDAT or fdAT chunks.
    # This function assumes that the PNG filter type is 0.
    #
    # This function converts `stream` to an array.

    # nchannels is a map from color_type to the number of color
    # channels (e.g. an RGB image has three channels).
    nchannels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}

    ncols, rembits = divmod(width*bit_depth, 8)
    ncols += rembits > 0
    lines = stream.reshape(height, nchannels[color_type]*ncols + 1)
    expected_col0 = np.zeros(height, dtype=np.uint8)
    assert_array_equal(lines[:, 0], expected_col0)
    p = lines[:, 1:]

    uint8to16 = np.array([256, 1], dtype=np.uint16)

    if color_type == 0:
        # grayscale
        if bit_depth == 16:
            img = p.reshape(-1, p.shape[1]//2, 2).dot(uint8to16)
        elif bit_depth == 8:
            img = p
        else:  # bit_depth is 1, 2 or 4.
            img = pngw._unpack(p, bitdepth=bit_depth, width=width)

    elif color_type == 2:
        # RGB
        if bit_depth == 16:
            # Combine high and low bytes to 16-bit values.
            img1 = p.reshape(-1, p.shape[1]//2, 2).dot(uint8to16)
            # Reshape to (height, width, 3)
            img = img1.reshape(height, -1, 3)
        else:  # bit_depth is 8.
            # Reshape to (height, width, 3)
            img = p.reshape(height, -1, 3)

    elif color_type == 3:
        # indexed
        raise RuntimeError('check_stream for color_type 3 not implemented.')

    elif color_type == 4:
        # grayscale with alpha
        if bit_depth == 16:
            # Combine high and low bytes to 16-bit values.
            img1 = p.reshape(-1, p.shape[1]//2, 2).dot(uint8to16)
            # Reshape to (height, width, 2)
            img = img1.reshape(height, -1, 2)
        else:  # bit_depth is 8.
            # Reshape to (height, width, 2)
            img = p.reshape(height, -1, 2)

    elif color_type == 6:
        # RGBA
        if bit_depth == 16:
            # Combine high and low bytes to 16-bit values.
            img1 = p.reshape(-1, p.shape[1]//2, 2).dot(uint8to16)
            # Reshape to (height, width, 4)
            img = img1.reshape(height, -1, 4)
        else:  # bit_depth is 8.
            # Reshape to (height, width, 3)
            img = p.reshape(height, -1, 4)

    else:
        raise RuntimeError('invalid color type %r' % (color_type,))

    return img


def check_actl(file_contents, num_frames, num_plays):
    chunk_type, chunk_data, file_contents = next_chunk(file_contents)
    assert_equal(chunk_type, b"acTL")
    values = struct.unpack("!II", chunk_data)
    assert_equal(values, (num_frames, num_plays))
    return file_contents


def check_fctl(file_contents, sequence_number, width, height,
               x_offset=0, y_offset=0, delay_num=0, delay_den=1,
               dispose_op=0, blend_op=1):
    chunk_type, chunk_data, file_contents = next_chunk(file_contents)
    assert_equal(chunk_type, b"fcTL")
    values = struct.unpack("!IIIIIHHBB", chunk_data)
    expected_values = (sequence_number, width, height, x_offset, y_offset,
                       delay_num, delay_den, dispose_op, blend_op)
    assert_equal(values, expected_values)
    return file_contents


def check_time(file_contents, timestamp):
    chunk_type, chunk_data, file_contents = next_chunk(file_contents)
    assert_equal(chunk_type, b"tIME")
    values = struct.unpack("!HBBBBB", chunk_data)
    assert_equal(values, timestamp)
    return file_contents


def check_gama(file_contents, gamma):
    # gamma is the floating point gamma value.
    chunk_type, chunk_data, file_contents = next_chunk(file_contents)
    assert_equal(chunk_type, b"gAMA")
    gama = struct.unpack("!I", chunk_data)[0]
    igamma = int(gamma*100000 + 0.5)
    assert_equal(gama, igamma)
    return file_contents


def check_iend(file_contents):
    chunk_type, chunk_data, file_contents = next_chunk(file_contents)
    assert_equal(chunk_type, b"IEND")
    assert_equal(chunk_data, b"")
    # The IEND chunk is the last chunk, so file_contents should now
    # be empty.
    assert_equal(file_contents, b"")


class TestWritePng(unittest.TestCase):

    def test_write_png_nbit_grayscale(self):
        # Test the creation of grayscale images for bit depths of 1, 2, 4
        # 8 and 16, with or without a `transparent` color selected.
        np.random.seed(123)
        for bitdepth in [1, 2, 4, 8, 16]:
            for transparent in [None, 0]:
                dt = np.uint16 if bitdepth == 16 else np.uint8
                maxval = 2**bitdepth
                img = np.random.randint(0, maxval, size=(3, 11)).astype(dt)
                if transparent is not None:
                    img[2:4, 2:] = transparent

                f = io.BytesIO()
                pngw.write_png(f, img, bitdepth=bitdepth,
                               transparent=transparent)

                file_contents = f.getvalue()

                file_contents = check_signature(file_contents)

                file_contents = check_ihdr(file_contents,
                                           width=img.shape[1],
                                           height=img.shape[0],
                                           bit_depth=bitdepth, color_type=0)

                if transparent is not None:
                    file_contents = check_trns(file_contents, color_type=0,
                                               transparent=transparent)

                file_contents = check_idat(file_contents, color_type=0,
                                           bit_depth=bitdepth, img=img)

                check_iend(file_contents)

    def test_write_png_with_alpha(self):
        # Test creation of grayscale+alpha and RGBA images (color types 4
        # and 6, resp.), with bit depths 8 and 16.
        w = 25
        h = 15
        np.random.seed(12345)
        for color_type in [4, 6]:
            num_channels = 2 if color_type == 4 else 4
            for bit_depth in [8, 16]:
                dt = np.uint8 if bit_depth == 8 else np.uint16
                img = np.random.randint(0, 2**bit_depth,
                                        size=(h, w, num_channels)).astype(dt)
                f = io.BytesIO()
                pngw.write_png(f, img)

                file_contents = f.getvalue()

                file_contents = check_signature(file_contents)

                file_contents = check_ihdr(file_contents, width=w, height=h,
                                           bit_depth=bit_depth,
                                           color_type=color_type)

                file_contents = check_idat(file_contents, color_type=color_type,
                                           bit_depth=bit_depth, img=img)

                check_iend(file_contents)

    def test_write_png_RGB(self):
        # Test creation of RGB images (color type 2), with and without
        # a `transparent` color selected, and with bit depth 8 and 16.
        w = 24
        h = 10
        np.random.seed(12345)
        for transparent in [None, (0, 0, 0)]:
            for bit_depth in [8, 16]:
                dt = np.uint16 if bit_depth == 16 else np.uint8
                maxval = 2**bit_depth
                img = np.random.randint(0, maxval, size=(h, w, 3)).astype(dt)
                if transparent:
                    img[2:4, 2:4] = transparent

                f = io.BytesIO()
                pngw.write_png(f, img, transparent=transparent)

                file_contents = f.getvalue()

                file_contents = check_signature(file_contents)

                file_contents = check_ihdr(file_contents, width=w, height=h,
                                           bit_depth=bit_depth, color_type=2)

                if transparent:
                    file_contents = check_trns(file_contents, color_type=2,
                                               transparent=transparent)

                file_contents = check_idat(file_contents, color_type=2,
                                           bit_depth=bit_depth, img=img)

                check_iend(file_contents)

    def test_write_png_8bit_RGB_palette(self):
        img = np.arange(4*5*3, dtype=np.uint8).reshape(4, 5, 3)
        f = io.BytesIO()
        pngw.write_png(f, img, use_palette=True)

        file_contents = f.getvalue()

        file_contents = check_signature(file_contents)

        file_contents = check_ihdr(file_contents,
                                   width=img.shape[1], height=img.shape[0],
                                   bit_depth=8, color_type=3)

        # Check the PLTE chunk.
        chunk_type, chunk_data, file_contents = next_chunk(file_contents)
        self.assertEqual(chunk_type, b"PLTE")
        p = np.fromstring(chunk_data, dtype=np.uint8).reshape(-1, 3)
        assert_array_equal(p, np.arange(4*5*3, dtype=np.uint8).reshape(-1, 3))

        # Check the IDAT chunk.
        chunk_type, chunk_data, file_contents = next_chunk(file_contents)
        self.assertEqual(chunk_type, b"IDAT")
        decompressed = zlib.decompress(chunk_data)
        b = np.fromstring(decompressed, dtype=np.uint8)
        lines = b.reshape(img.shape[0], img.shape[1]+1)
        img2 = lines[:, 1:].reshape(img.shape[:2])
        expected = np.arange(20, dtype=np.uint8).reshape(img.shape[:2])
        assert_array_equal(img2, expected)

        check_iend(file_contents)

    def test_write_png_max_chunk_len(self):
        # Create an 8-bit grayscale image.
        w = 250
        h = 150
        max_chunk_len = 500
        img = np.random.randint(0, 256, size=(h, w)).astype(np.uint8)
        f = io.BytesIO()
        pngw.write_png(f, img, max_chunk_len=max_chunk_len)

        file_contents = f.getvalue()

        file_contents = check_signature(file_contents)

        file_contents = check_ihdr(file_contents,
                                   width=w, height=h,
                                   bit_depth=8, color_type=0)

        zstream = b''
        while True:
            chunk_type, chunk_data, file_contents = next_chunk(file_contents)
            if chunk_type != b"IDAT":
                break
            self.assertEqual(chunk_type, b"IDAT")
            zstream += chunk_data
            self.assertLessEqual(len(chunk_data), max_chunk_len)
        data = zlib.decompress(zstream)
        b = np.fromstring(data, dtype=np.uint8)
        lines = b.reshape(h, w + 1)
        img2 = lines[:, 1:].reshape(h, w)
        assert_array_equal(img2, img)

        # Check the IEND chunk; chunk_type and chunk_data were read
        # in the loop above.
        self.assertEqual(chunk_type, b"IEND")
        self.assertEqual(chunk_data, b"")

        self.assertEqual(file_contents, b"")

    def test_write_png_timestamp_gamma(self):
        np.random.seed(123)
        img = np.random.randint(0, 256, size=(10, 10)).astype(np.uint8)
        f = io.BytesIO()
        timestamp = (1452, 4, 15, 8, 9, 10)
        gamma = 2.2
        pngw.write_png(f, img, timestamp=timestamp, gamma=gamma)

        file_contents = f.getvalue()

        file_contents = check_signature(file_contents)

        file_contents = check_ihdr(file_contents,
                                   width=img.shape[1], height=img.shape[0],
                                   bit_depth=8, color_type=0)

        file_contents = check_time(file_contents, timestamp)

        file_contents = check_gama(file_contents, gamma)

        file_contents = check_idat(file_contents, color_type=0, bit_depth=8,
                                   img=img)

        check_iend(file_contents)


class TestWriteApng(unittest.TestCase):

    def test_write_apng_8bit_RGBA(self):
        num_frames = 4
        w = 25
        h = 15
        np.random.seed(12345)
        seq_size = (num_frames, h, w, 4)
        seq = np.random.randint(0, 256, size=seq_size).astype(np.uint8)
        f = io.BytesIO()
        pngw.write_apng(f, seq)

        file_contents = f.getvalue()

        file_contents = check_signature(file_contents)

        file_contents = check_ihdr(file_contents, width=w, height=h,
                                   bit_depth=8, color_type=6)

        file_contents = check_actl(file_contents, num_frames=4, num_plays=0)

        sequence_number = 0
        file_contents = check_fctl(file_contents,
                                   sequence_number=sequence_number,
                                   width=w, height=h)
        sequence_number += 1

        file_contents = check_idat(file_contents, color_type=6, bit_depth=8,
                                   img=seq[0])

        for k in range(1, 4):
            file_contents = check_fctl(file_contents,
                                       sequence_number=sequence_number,
                                       width=w, height=h)
            sequence_number += 1

            # Check the fdAT chunk.
            chunk_type, chunk_data, file_contents = next_chunk(file_contents)
            self.assertEqual(chunk_type, b"fdAT")
            actual_seq_num = struct.unpack("!I", chunk_data[:4])[0]
            self.assertEqual(actual_seq_num, sequence_number)
            sequence_number += 1
            decompressed = zlib.decompress(chunk_data[4:])
            b = np.fromstring(decompressed, dtype=np.uint8)
            lines = b.reshape(h, 4*w+1)
            expected_col0 = np.zeros(h, dtype=np.uint8)
            assert_array_equal(lines[:, 0], expected_col0)
            img2 = lines[:, 1:].reshape(h, w, 4)
            assert_array_equal(img2, seq[k])

        check_iend(file_contents)


if __name__ == '__main__':
    unittest.main()
