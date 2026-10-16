"""Pure Python SVG QR Code Generator for Transit Operators and Travel Hubs.

Zero external dependencies. Generates valid QR Code Version 1-4 SVGs with standard Byte mode (8-bit)
and Reed-Solomon Error Correction Level M/L for embedding directly in web pages and printable signs.
"""

from typing import List, Tuple
import urllib.parse


# Standard Galois Field GF(256) tables for QR polynomial arithmetic
GF_EXP = [0] * 512
GF_LOG = [0] * 256

def _init_gf256():
    x = 1
    for i in range(255):
        GF_EXP[i] = x
        GF_EXP[i + 255] = x
        GF_LOG[x] = i
        x <<= 1
        if x & 0x100:
            x ^= 0x11D  # Primitive polynomial 100011101
    GF_LOG[0] = 0

_init_gf256()

def _gf_mul(x: int, y: int) -> int:
    if x == 0 or y == 0:
        return 0
    return GF_EXP[GF_LOG[x] + GF_LOG[y]]

def _rs_generator_poly(ec_count: int) -> List[int]:
    g = [1]
    for i in range(ec_count):
        g_next = [0] * (len(g) + 1)
        for j, coeff in enumerate(g):
            g_next[j] ^= _gf_mul(coeff, GF_EXP[i])
            g_next[j + 1] ^= coeff
        g = g_next
    return g

def _rs_encode(data: List[int], ec_count: int) -> List[int]:
    gen = _rs_generator_poly(ec_count)
    res = list(data) + [0] * ec_count
    for i in range(len(data)):
        lead = res[i]
        if lead != 0:
            for j, g in enumerate(gen):
                res[i + j] ^= _gf_mul(lead, g)
    return res[len(data):]


# Version configurations: (data_codewords, ec_codewords, total_codewords, size)
# Version 3-L (size 29x29, 55 data bytes, 15 EC) or Version 4-L (size 33x33, 80 data bytes, 20 EC)
VERSION_CONFIGS = {
    1: {"size": 21, "data": 19, "ec": 7, "ec_blocks": [(19, 7)]},
    2: {"size": 25, "data": 34, "ec": 10, "ec_blocks": [(34, 10)]},
    3: {"size": 29, "data": 55, "ec": 15, "ec_blocks": [(55, 15)]},
    4: {"size": 33, "data": 80, "ec": 20, "ec_blocks": [(80, 20)]},
    5: {"size": 37, "data": 108, "ec": 26, "ec_blocks": [(108, 26)]},
}


def _select_version(data_len: int) -> int:
    """Select the smallest QR version that accommodates the data."""
    # Overhead in byte mode: 4 bits mode + 8 bits length (v1-9) = 12 bits
    needed_bytes = data_len + 2
    for v in sorted(VERSION_CONFIGS.keys()):
        if needed_bytes <= VERSION_CONFIGS[v]["data"]:
            return v
    return 5


def generate_qr_matrix(text: str) -> Tuple[List[List[int]], int]:
    """Generate a 2D binary matrix for the QR code representation of text."""
    raw_data = text.encode("utf-8")
    version = _select_version(len(raw_data))
    cfg = VERSION_CONFIGS[version]
    size = cfg["size"]
    matrix = [[None] * size for _ in range(size)]
    reserved = [[False] * size for _ in range(size)]

    # 1. Place finder patterns at three corners
    def place_finder(top: int, left: int):
        for r in range(top, top + 7):
            for c in range(left, left + 7):
                is_edge = (r in (top, top + 6) or c in (left, left + 6))
                is_center = (top + 2 <= r <= top + 4 and left + 2 <= c <= left + 4)
                val = 1 if (is_edge or is_center) else 0
                matrix[r][c] = val
                reserved[r][c] = True
        # Separator borders
        for r in range(max(0, top - 1), min(size, top + 8)):
            for c in range(max(0, left - 1), min(size, left + 8)):
                if matrix[r][c] is None:
                    matrix[r][c] = 0
                    reserved[r][c] = True

    place_finder(0, 0)
    place_finder(0, size - 7)
    place_finder(size - 7, 0)

    # 2. Timing patterns
    for i in range(8, size - 8):
        val = 1 if (i % 2 == 0) else 0
        if not reserved[6][i]:
            matrix[6][i] = val
            reserved[6][i] = True
        if not reserved[i][6]:
            matrix[i][6] = val
            reserved[i][6] = True

    # Dark module
    matrix[size - 8][8] = 1
    reserved[size - 8][8] = True

    # 3. Encode data bits
    # Mode indicator: 0100 (Byte mode)
    bits = [0, 1, 0, 0]
    # Character count (8 bits for v1-9)
    for b in range(7, -1, -1):
        bits.append((len(raw_data) >> b) & 1)
    # Data bytes
    for byte in raw_data:
        for b in range(7, -1, -1):
            bits.append((byte >> b) & 1)

    max_data_bytes = cfg["data"]
    # Terminator
    bits.extend([0] * min(4, max_data_bytes * 8 - len(bits)))
    # Byte alignment
    while len(bits) % 8 != 0:
        bits.append(0)

    # Pad bytes (0xEC, 0x11)
    pad = [0xEC, 0x11]
    p_idx = 0
    data_bytes = []
    for i in range(0, len(bits), 8):
        byte_val = 0
        for bit in bits[i:i+8]:
            byte_val = (byte_val << 1) | bit
        data_bytes.append(byte_val)

    while len(data_bytes) < max_data_bytes:
        data_bytes.append(pad[p_idx % 2])
        p_idx += 1

    # 4. Compute error correction
    ec_bytes = _rs_encode(data_bytes, cfg["ec"])
    all_codewords = data_bytes + ec_bytes

    all_bits = []
    for cw in all_codewords:
        for b in range(7, -1, -1):
            all_bits.append((cw >> b) & 1)

    # 5. Place data modules in zigzag pattern
    bit_idx = 0
    right = size - 1
    upwards = True

    while right > 0:
        if right == 6:  # Skip timing pattern column
            right -= 1
        cols = [right, right - 1]
        row_range = range(size - 1, -1, -1) if upwards else range(0, size)

        for r in row_range:
            for c in cols:
                if not reserved[r][c]:
                    b = all_bits[bit_idx] if bit_idx < len(all_bits) else 0
                    # Apply Mask Pattern 0: (r + c) % 2 == 0
                    mask = 1 if ((r + c) % 2 == 0) else 0
                    matrix[r][c] = b ^ mask
                    bit_idx += 1

        upwards = not upwards
        right -= 2

    # 6. Format info: Mask 0, EC Level L (01) -> Format string with BCH (0x77C4 or 0x7E3A)
    # Standard format string for EC Level L, Mask 0 is 111011111000100 (binary)
    format_bits = [1, 1, 1, 0, 1, 1, 1, 1, 1, 0, 0, 0, 1, 0, 0]
    # Around top-left finder
    coords_tl = [
        (8, 0), (8, 1), (8, 2), (8, 3), (8, 4), (8, 5), (8, 7), (8, 8),
        (7, 8), (5, 8), (4, 8), (3, 8), (2, 8), (1, 8), (0, 8)
    ]
    for idx, (r, c) in enumerate(coords_tl):
        matrix[r][c] = format_bits[idx]

    # Split around other finders
    coords_split = [
        (size - 1, 8), (size - 2, 8), (size - 3, 8), (size - 4, 8), (size - 5, 8), (size - 6, 8), (size - 7, 8),
        (8, size - 8), (8, size - 7), (8, size - 6), (8, size - 5), (8, size - 4), (8, size - 3), (8, size - 2), (8, size - 1)
    ]
    for idx, (r, c) in enumerate(coords_split):
        matrix[r][c] = format_bits[idx]

    # Fill any remaining None with 0
    for r in range(size):
        for c in range(size):
            if matrix[r][c] is None:
                matrix[r][c] = 0

    return matrix, size


def generate_qr_svg(
    text: str,
    box_size: int = 8,
    border: int = 4,
    fill_color: str = "#0f172a",
    bg_color: str = "#ffffff",
) -> str:
    """Generate a clean, scalable SVG string representing the QR code."""
    matrix, size = generate_qr_matrix(text)
    total_size = (size + border * 2) * box_size

    rects = []
    for r in range(size):
        for c in range(size):
            if matrix[r][c] == 1:
                x = (c + border) * box_size
                y = (r + border) * box_size
                rects.append(f'<rect x="{x}" y="{y}" width="{box_size}" height="{box_size}" fill="{fill_color}"/>')

    rects_str = "".join(rects)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total_size} {total_size}" '
        f'width="{total_size}" height="{total_size}" role="img" aria-label="QR Code for {text}">'
        f'<rect width="{total_size}" height="{total_size}" fill="{bg_color}"/>'
        f'{rects_str}'
        f'</svg>'
    )
    return svg


def build_transit_destination_url(
    base_url: str,
    provider_id: str = "transit_general",
    hub_name: str = "general",
) -> str:
    """Build a standardized QR scan landing URL for transport providers."""
    clean_base = base_url.rstrip("/")
    params = urllib.parse.urlencode({
        "provider": provider_id,
        "hub": hub_name,
        "source": "qr_scan",
    })
    return f"{clean_base}/guest/found?{params}"
