"""国密算法纯 Python 实现（SM2/SM3/SM4）— 信创国产密码合规。

设计（等保 2.0 三级 密码算法合规项，纯 stdlib、无三方依赖）：
- SM3：密码杂凑，输出 256bit。GB/T 32905-2016。
- SM4：128bit 分组密码，支持 ECB/CBC/PKCS7。GB/T 32907-2016。
- SM2：椭圆曲线公钥密码（推荐曲线 sm2p256v1），SM3 杂凑的数字签名/验签。
  用于 License 验签等场景替代 RSA。GB/T 32918-2016。

重要边界（诚实标注）：
- 本模块为**纯 Python 教学/合规参考实现**，算法正确、通过标准向量与 roundtrip 自检；
  生产等保现场应经**密码型号检测合格**的合规库（gmssl / 加密机 / HSM）。
- SM2 加解密（C1C3C2 复合）未实现，仅实现最常用的数字签名/验签。
- 常量与算法均来自公开国标，无第三方源码复制。

全部实现原创；常量表（S 盒、曲线参数）按国标标准值内嵌。
"""
from __future__ import annotations

import hmac
import os


# ============================================================ SM3
# GB/T 32905-2016
_SM3_IV = (
    0x7380166F, 0x4914B2B9, 0x172442D7, 0xDA8A0600,
    0xA96F30BC, 0x163138AA, 0xE38DEE4D, 0xB0FB0E4E,
)

_ROTL = lambda x, n: ((x << (n % 32)) | (x >> ((32 - n % 32) % 32))) & 0xFFFFFFFF


def _sm3_ff(x: int, y: int, z: int, j: int) -> int:
    if j < 16:
        return x ^ y ^ z
    return (x & y) | (x & z) | (y & z)


def _sm3_gg(x: int, y: int, z: int, j: int) -> int:
    if j < 16:
        return x ^ y ^ z
    return (x & y) | (~x & z)


def _sm3_p0(x: int) -> int:
    return x ^ _ROTL(x, 9) ^ _ROTL(x, 17)


def _sm3_p1(x: int) -> int:
    return x ^ _ROTL(x, 15) ^ _ROTL(x, 23)


def sm3(data: bytes) -> bytes:
    """SM3 杂凑，返回 32 字节摘要。"""
    msg = bytearray(data)
    bit_len = len(msg) * 8
    msg.append(0x80)
    while len(msg) % 64 != 56:
        msg.append(0)
    msg += bit_len.to_bytes(8, "big")
    v = list(_SM3_IV)
    t = 0x79CC4519
    for chunk_start in range(0, len(msg), 64):
        block = msg[chunk_start:chunk_start + 64]
        w = [int.from_bytes(block[i:i + 4], "big") for i in range(0, 64, 4)]
        for j in range(16, 68):
            w.append(_sm3_p1(w[j - 16] ^ w[j - 9] ^ (_ROTL(w[j - 3], 15)))
                     ^ _ROTL(w[j - 13], 7) ^ w[j - 6])
        w1 = [w[j] ^ w[j + 4] for j in range(64)]
        a, b, c, d, e, f, g, h = v
        for j in range(64):
            tt = t if j < 16 else 0x7A879D8A
            ss1 = _ROTL((_ROTL(a, 12) + e + _ROTL(tt, j)) & 0xFFFFFFFF, 7)
            ss2 = ss1 ^ _ROTL(a, 12)
            tt1 = (_sm3_ff(a, b, c, j) + d + ss2 + w1[j]) & 0xFFFFFFFF
            tt2 = (_sm3_gg(e, f, g, j) + h + ss1 + w[j]) & 0xFFFFFFFF
            d, c, b, a = c, _ROTL(b, 9), a, tt1
            h, g, f, e = g, _ROTL(f, 19), e, _sm3_p0(tt2)
        v = [((v[i] ^ x)) & 0xFFFFFFFF for i, x in
             enumerate((a, b, c, d, e, f, g, h))]
    return b"".join(x.to_bytes(4, "big") for x in v)


def sm3_hex(data: bytes) -> str:
    return sm3(data).hex()


# ============================================================ SM4
# GB/T 32907-2016
_SM4_SBOX = bytes([
    0xD6, 0x90, 0xE9, 0xFE, 0xCC, 0xE1, 0x3D, 0xB7, 0x16, 0xB6, 0x14, 0xC2, 0x28, 0xFB, 0x2C, 0x05,
    0x2B, 0x67, 0x9A, 0x76, 0x2A, 0xBE, 0x04, 0xC3, 0xAA, 0x44, 0x13, 0x26, 0x49, 0x86, 0x06, 0x99,
    0x9C, 0x42, 0x50, 0xF4, 0x91, 0xEF, 0x98, 0x7A, 0x33, 0x54, 0x0B, 0x43, 0xED, 0xCF, 0xAC, 0x62,
    0xE4, 0xB3, 0x1C, 0xA9, 0xC9, 0x08, 0xE8, 0x95, 0x80, 0xDF, 0x94, 0xFA, 0x75, 0x8F, 0x3F, 0xA6,
    0x47, 0x07, 0xA7, 0xFC, 0xF3, 0x73, 0x17, 0xBA, 0x83, 0x59, 0x3C, 0x19, 0xE6, 0x85, 0x4F, 0xA8,
    0x68, 0x6B, 0x81, 0xB2, 0x71, 0x64, 0xDA, 0x8B, 0xF8, 0xEB, 0x0F, 0x4B, 0x70, 0x56, 0x9D, 0x35,
    0x1E, 0x24, 0x0E, 0x5E, 0x63, 0x58, 0xD1, 0xA2, 0x25, 0x22, 0x7C, 0x3B, 0x01, 0x21, 0x78, 0x87,
    0xD4, 0x00, 0x46, 0x57, 0x9F, 0xD3, 0x27, 0x52, 0x4C, 0x36, 0x02, 0xE7, 0xA0, 0xC4, 0xC8, 0x9E,
    0xEA, 0xBF, 0x8A, 0xD2, 0x40, 0xC7, 0x38, 0xB5, 0xA3, 0xF7, 0xF2, 0xCE, 0xF9, 0x61, 0x15, 0xA1,
    0xE0, 0xAE, 0x5D, 0xA4, 0x9B, 0x34, 0x1A, 0x55, 0xAD, 0x93, 0x32, 0x30, 0xF5, 0x8C, 0xB1, 0xE3,
    0x1D, 0xF6, 0xE2, 0x2E, 0x82, 0x66, 0xCA, 0x60, 0xC0, 0x29, 0x23, 0xAB, 0x0D, 0x53, 0x4E, 0x6F,
    0xD5, 0xDB, 0x37, 0x45, 0xDE, 0xFD, 0x8E, 0x2F, 0x03, 0xFF, 0x6A, 0x72, 0x6D, 0x6C, 0x5B, 0x51,
    0x8D, 0x1B, 0xAF, 0x92, 0xBB, 0xDD, 0xBC, 0x7F, 0x11, 0xD9, 0x5C, 0x41, 0x1F, 0x10, 0x5A, 0xD8,
    0x0A, 0xC1, 0x31, 0x88, 0xA5, 0xCD, 0x7B, 0xBD, 0x2D, 0x74, 0xD0, 0x12, 0xB8, 0xE5, 0xB4, 0xB0,
    0x89, 0x69, 0x97, 0x4A, 0x0C, 0x96, 0x77, 0x7E, 0x65, 0xB9, 0xF1, 0x09, 0xC5, 0x6E, 0xC6, 0x84,
    0x18, 0xF0, 0x7D, 0xEC, 0x3A, 0xDC, 0x4D, 0x20, 0x79, 0xEE, 0x5F, 0x3E, 0xD7, 0xCB, 0x39, 0x48,
])

_SM4_FK = (0xA3B1BAC6, 0x56AA3350, 0x677D9197, 0xB27022DC)
# GB/T 32907-2016 标准 CK 常量表（32 个 32bit）
_SM4_CK = (
    0x00070E15, 0x1C232A31, 0x383F464D, 0x545B6269,
    0x70777E85, 0x8C939AA1, 0xA8AFB6BD, 0xC4CBD2D9,
    0xE0E7EEF5, 0xFC030A11, 0x181F262D, 0x343B4249,
    0x50575E65, 0x6C737A81, 0x888F969D, 0xA4ABB2B9,
    0xC0C7CED5, 0xDCE3EAF1, 0xF8FF060D, 0x141B2229,
    0x30373E45, 0x4C535A61, 0x686F767D, 0x848B9299,
    0xA0A7AEB5, 0xBCC3CAD1, 0xD8DFE6ED, 0xF4FB0209,
    0x10171E25, 0x2C333A41, 0x484F565D, 0x646B7279,
)


def _sm4_tau(x: int) -> int:
    return ((_SM4_SBOX[(x >> 24) & 0xFF] << 24)
            | (_SM4_SBOX[(x >> 16) & 0xFF] << 16)
            | (_SM4_SBOX[(x >> 8) & 0xFF] << 8)
            | _SM4_SBOX[x & 0xFF])


def _sm4_l(b: int) -> int:
    return b ^ _ROTL(b, 2) ^ _ROTL(b, 10) ^ _ROTL(b, 18) ^ _ROTL(b, 24)


def _sm4_l_prime(b: int) -> int:
    return b ^ _ROTL(b, 13) ^ _ROTL(b, 23)


def _sm4_key_schedule(key: bytes) -> list[int]:
    mk = [int.from_bytes(key[i:i + 4], "big") for i in range(0, 16, 4)]
    k = [mk[i] ^ _SM4_FK[i] for i in range(4)]
    rk: list[int] = []
    for i in range(32):
        t = _sm4_l_prime(_sm4_tau(k[1] ^ k[2] ^ k[3] ^ _SM4_CK[i]))
        rk.append(t ^ k[0])
        k = k[1:] + [t ^ k[0]]
    return rk


def _sm4_block_encrypt(rk: list[int], block: bytes) -> bytes:
    x = [int.from_bytes(block[i:i + 4], "big") for i in range(0, 16, 4)]
    for i in range(32):
        t = _sm4_l(_sm4_tau(x[1] ^ x[2] ^ x[3] ^ rk[i]))
        x = x[1:] + [t ^ x[0]]
    return b"".join(z.to_bytes(4, "big") for z in x[::-1])


class SM4:
    """SM4 分组密码（ECB/CBC + PKCS7 填充）。"""

    def __init__(self, key: bytes) -> None:
        if len(key) != 16:
            raise ValueError("SM4 密钥必须为 16 字节")
        self._ek = _sm4_key_schedule(key)
        self._dk = self._ek[::-1]

    @staticmethod
    def _pkcs7(data: bytes) -> bytes:
        pad = 16 - len(data) % 16
        return data + bytes([pad]) * pad

    @staticmethod
    def _unpad(data: bytes) -> bytes:
        pad = data[-1]
        if pad < 1 or pad > 16 or data[-pad:] != bytes([pad]) * pad:
            raise ValueError("PKCS7 填充非法")
        return data[:-pad]

    def encrypt_ecb(self, data: bytes) -> bytes:
        blocks = [data[i:i + 16] for i in range(0, len(data), 16)]
        return b"".join(_sm4_block_encrypt(self._ek, b) for b in blocks)

    def decrypt_ecb(self, data: bytes) -> bytes:
        blocks = [data[i:i + 16] for i in range(0, len(data), 16)]
        return b"".join(_sm4_block_encrypt(self._dk, b) for b in blocks)

    def encrypt_cbc(self, data: bytes, iv: bytes) -> bytes:
        if len(iv) != 16:
            raise ValueError("IV 必须为 16 字节")
        padded = self._pkcs7(data)
        prev = iv
        out = bytearray()
        for i in range(0, len(padded), 16):
            blk = bytes(a ^ b for a, b in zip(padded[i:i + 16], prev))
            enc = _sm4_block_encrypt(self._ek, blk)
            out += enc
            prev = enc
        return bytes(out)

    def decrypt_cbc(self, data: bytes, iv: bytes) -> bytes:
        if len(iv) != 16:
            raise ValueError("IV 必须为 16 字节")
        prev = iv
        out = bytearray()
        for i in range(0, len(data), 16):
            dec = _sm4_block_encrypt(self._dk, data[i:i + 16])
            out += bytes(a ^ b for a, b in zip(dec, prev))
            prev = data[i:i + 16]
        return self._unpad(bytes(out))


def sm4_encrypt(key: bytes, data: bytes) -> bytes:
    """兼容旧接口：CBC + 随机 IV（IV 拼接在密文头部）。"""
    iv = os.urandom(16)
    return iv + SM4(key).encrypt_cbc(data, iv)


def sm4_decrypt(key: bytes, data: bytes) -> bytes:
    """配套 CBC 解密：密文 = IV(16) + body。"""
    if len(data) < 32:
        raise ValueError("SM4 密文过短")
    return SM4(key).decrypt_cbc(data[16:], data[:16])


# ============================================================ SM2 数字签名
# GB/T 32918.2-2016，推荐曲线 sm2p256v1
_SM2_P = 0xFFFFFFFEFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF00000000FFFFFFFFFFFFFFFF
_SM2_A = 0xFFFFFFFEFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF00000000FFFFFFFFFFFFFFFC
_SM2_B = 0x28E9FA9E9D9F5E344D5A9E4BCF6509A7F39789F515AB8F92DDBCBD414D940E93
_SM2_N = 0xFFFFFFFEFFFFFFFFFFFFFFFFFFFFFFFF7203DF6B21C6052B53BBF40939D54123
_SM2_GX = 0x32C4AE2C1F1981195F9904466A39C9948FE30BBFF2660BE1715A4589334C74C7
_SM2_GY = 0xBC3736A2F4F6779C59BDCEE36B692153D0A9877CC62A474002DF32E52139F0A0


def _mod_inv(a: int, m: int) -> int:
    return pow(a, -1, m)


def _ec_add(p1: tuple[int, int] | None, p2: tuple[int, int] | None) -> tuple[int, int] | None:
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2:
        if (y1 + y2) % _SM2_P == 0:
            return None
        lam = ((3 * x1 * x1 + _SM2_A) * _mod_inv(2 * y1, _SM2_P)) % _SM2_P
    else:
        lam = ((y2 - y1) * _mod_inv(x2 - x1, _SM2_P)) % _SM2_P
    x3 = (lam * lam - x1 - x2) % _SM2_P
    y3 = (lam * (x1 - x3) - y1) % _SM2_P
    return x3, y3


def _ec_mul(k: int, pt: tuple[int, int] | None) -> tuple[int, int] | None:
    result: tuple[int, int] | None = None
    addend = pt
    k = k % _SM2_N
    while k:
        if k & 1:
            result = _ec_add(result, addend)
        addend = _ec_add(addend, addend)
        k >>= 1
    return result


def _sm2_z(ida: bytes, pub: tuple[int, int]) -> bytes:
    entl = (len(ida) * 8).to_bytes(2, "big")
    data = (entl + ida
            + _SM2_A.to_bytes(32, "big") + _SM2_B.to_bytes(32, "big")
            + _SM2_GX.to_bytes(32, "big") + _SM2_GY.to_bytes(32, "big")
            + pub[0].to_bytes(32, "big") + pub[1].to_bytes(32, "big"))
    return sm3(data)


def generate_sm2_keypair() -> tuple[bytes, bytes]:
    """生成(d, PA)：(私钥 d, 公钥 x||y 各32字节)。"""
    while True:
        d = int.from_bytes(os.urandom(32), "big") % (_SM2_N - 1) + 1
        pa = _ec_mul(d, (_SM2_GX, _SM2_GY))
        if pa is not None:
            return d.to_bytes(32, "big"), pa[0].to_bytes(32, "big") + pa[1].to_bytes(32, "big")


def sm2_sign(priv: bytes, msg: bytes, ida: bytes = b"1234567812345678") -> tuple[bytes, bytes]:
    """SM2 签名，返回 (r, s) 各 32 字节。"""
    d = int.from_bytes(priv, "big") % _SM2_N
    pub = _ec_mul(d, (_SM2_GX, _SM2_GY))
    assert pub is not None
    z = _sm2_z(ida, pub)
    e = int.from_bytes(sm3(z + msg), "big")
    while True:
        k = int.from_bytes(os.urandom(32), "big") % _SM2_N or 1
        x1, _ = _ec_mul(k, (_SM2_GX, _SM2_GY)) or (0, 0)
        r = (e + x1) % _SM2_N
        if r == 0 or r + k == _SM2_N:
            continue
        s = (_mod_inv(1 + d, _SM2_N) * (k - r * d)) % _SM2_N
        if s == 0:
            continue
        return r.to_bytes(32, "big"), s.to_bytes(32, "big")


def sm2_verify(pub: bytes, msg: bytes, sig: tuple[bytes, bytes], ida: bytes = b"1234567812345678") -> bool:
    """SM2 验签。pub = x||y(各32字节)。校验通过返回 True。"""
    x, y = int.from_bytes(pub[:32], "big"), int.from_bytes(pub[32:], "big")
    r, s = int.from_bytes(sig[0], "big"), int.from_bytes(sig[1], "big")
    if not (1 <= r <= _SM2_N - 1 and 1 <= s <= _SM2_N - 1):
        return False
    z = _sm2_z(ida, (x, y))
    e = int.from_bytes(sm3(z + msg), "big")
    t = (r + s) % _SM2_N
    if t == 0:
        return False
    pt = _ec_add(_ec_mul(s, (_SM2_GX, _SM2_GY)), _ec_mul(t, (x, y)))
    if pt is None:
        return False
    rx, _ = pt
    return (e + rx) % _SM2_N == r

