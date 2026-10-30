# -*- coding: utf-8 -*-
"""MSFS BGL 机场反编译核心（逆向所得格式，已用 ZSFZ.bgl <-> ZSFZ.xml 配对验证）。

容器结构（在 ZGBH/ZSFZ/ZSXA/ZUHY 上验证）：
  0x00 文件头: magic 0x19920201 | 0x38 | 0 | 0 | magic2 0x08051803 @+0x10 | section 数 @+0x14
  section 表: 20 字节/条  (类型, 标志, 子块数, 目录偏移, 目录大小)
  子块目录  : 16 字节/条  (id, 记录数, 数据偏移, 数据大小)

机场记录（section 类型 0x03，记录 id 0x0113）：
  +0  u16 id | +2 u32 长度 | +6 六个 u8 计数(跑道/COM/起始/进近/停机坪/?)
  +12 u32 经度 | +16 u32 纬度 | +20 i32 海拔(mm)
  +0x5C 起为子记录流：(u16 id, u32 size) + 载荷

坐标定标：lon = raw*360/(3*2^28) - 180 ; lat = 90 - raw*180/2^29 ; 航向 = raw*360/2^32
"""
from __future__ import annotations

import os
import re
import struct
import uuid
import collections
import hashlib
import itertools
import math

VERSION = "1.4.2"

LON_SCALE = 360.0 / (3 * 0x10000000)
LAT_SCALE = 180.0 / (2 * 0x10000000)
HEAD_SCALE = 360.0 / 2 ** 32
FMT = "{:.14f}"

# 画线 / 网格填充画线共用的类型码（用 kmbase.bgl ↔ kmbase.xml 逐条顶点配对得出）
LINE_TYPE = {0x00: "DEFAULT", 0x01: "HOLD_SHORT_FORWARD", 0x02: "HOLD_SHORT_BACKWARD",
             0x03: "EDGE_LINE_DASHED", 0x04: "EDGE_LINE_SOLID", 0x05: "EDGE_SERVICE_DASHED",
             0x06: "EDGE_SERVICE_SOLID", 0x07: "HOLD_SHORT_TAXIWAY", 0x08: "ILS_HOLD_SHORT",
             0x09: "SERVICE_DASHED", 0x0A: "DEFAULT_LIGHTED", 0x0B: "HOLD_SHORT_FORWARD_LIGHTED",
             0x0C: "HOLD_SHORT_BACKWARD_LIGHTED", 0x0D: "EDGE_LINE_DASHED_LIGHTED",
             0x0E: "EDGE_LINE_SOLID_LIGHTED", 0x0F: "EDGE_SERVICE_DASHED_LIGHTED",
             0x10: "EDGE_SERVICE_SOLID_LIGHTED", 0x11: "HOLD_SHORT_TAXIWAY_LIGHTED",
             0x12: "ILS_HOLD_SHORT_LIGHTED", 0x13: "SERVICE_DASHED_LIGHTED", 0x14: "WIDE_YELLOW",
             0x15: "WIDE_YELLOW_LIGHTED", 0x16: "NON_MOVEMENT", 0x17: "NON_MOVEMENT_LIGHTED",
             0x18: "ENHANCED_CENTER", 0x19: "ENHANCED_CENTER_LIGHTED", 0x1A: "WIDE_WHITE",
             0x1B: "WIDE_WHITE_LIGHTED", 0x1C: "NON_MOVEMENT_BACK", 0x1D: "NON_MOVEMENT_BACK_LIGHTED",
             0x1E: "EDGE_SOLID_ORTHO", 0x1F: "EDGE_SOLID_ORTHO_LIGHTED", 0x20: "EDGE_SOLID_ORTHO_BACK",
             0x21: "EDGE_SOLID_ORTHO_BACK_LIGHT", 0x22: "WIDE_RED", 0x23: "WIDE_RED_LIGHTED",
             0x24: "SLIM_RED", 0x25: "SLIM_RED_LIGHTED", 0x26: "HOLD_SHORT_FORWARD_MARKED",
             0x27: "HOLD_SHORT_BACKWARD_MARKED", 0x28: "HOLD_SHORT_FORWARD_MARKED_L",
             0x29: "HOLD_SHORT_BACKWARD_MARKED_L"}

# DeleteAirport 的 48 位标志 → 属性名（位序由差分定位：flags u16 位 0-11，flags2 u8 位 0-7）
DEL_FLAGS = [("deleteAllApproaches", 0), ("deleteAllApronLights", 1), ("deleteAllAprons", 2),
             ("deleteAllFrequencies", 3), ("deleteAllHelipads", 4), ("deleteAllRunways", 5),
             ("deleteAllStarts", 6), ("deleteAllTaxiways", 7), ("deleteAllVectorPlacement", 8),
             ("deleteAllBoundaryFences", 9), ("deleteAllJetways", 10), ("deleteAllControlTowers", 11),
             ("deleteAllDepartures", 32), ("deleteAllArrivals", 33), ("deleteAllPaintedElements", 34),
             ("deleteAllLightSupports", 35), ("deleteAllTaxiwaySigns", 36), ("deleteAllILSs", 37),
             ("deleteAllTerminalWaypoints", 38), ("deleteAllTerminalNDBs", 39)]
DEL_UNMAPPED = ()

# 表面材质 / 直升机坪类型（取自FSTypes 枚举 枚举）
SURFACE_TYPE = {0x00: "CONCRETE", 0x01: "GRASS", 0x02: "WATER", 0x03: "CEMENT", 0x04: "ASPHALT",
                0x07: "CLAY", 0x08: "SNOW", 0x09: "ICE", 0x0C: "DIRT", 0x0D: "CORAL", 0x0E: "GRAVEL",
                0x0F: "OIL_TREATED", 0x10: "STEEL_MATS", 0x11: "BITUMINOUS", 0x12: "BRICK",
                0x13: "MACADAM", 0x14: "PLANKS", 0x15: "SAND", 0x16: "SHALE", 0x17: "TARMAC",
                0xFE: "UNKNOWN", 512: "USE_FS20_MATERIAL", 65283: "USE_FS20_APRON_MATERIAL"}
HELIPAD_TYPE = {0: "NONE", 1: "H", 2: "SQUARE", 3: "CIRCLE", 4: "MEDICAL"}

# 跑道灯光/目视助航（FSTypes 枚举 枚举）
LIGHT_LEVEL = {0: "NONE", 1: "LOW", 2: "MEDIUM", 3: "HIGH"}
VASI_TYPE = {1: "VASI21", 2: "VASI31", 3: "VASI22", 4: "VASI32", 5: "VASI23", 6: "VASI33",
             7: "PAPI2", 8: "PAPI4", 9: "TRICOLOR", 10: "PVASI", 11: "TVASI", 12: "BALL"}
APPROACH_LIGHTS = {1: "ODALS", 2: "MALSF", 3: "MALSR", 4: "SSALF", 5: "SSALR", 6: "ALSF1",
                   7: "ALSF2", 8: "RAIL", 9: "CALVERT", 10: "CALVERT2", 11: "MALS", 12: "SALS",
                   13: "SALSF", 14: "SSALS"}

# Markings 的 16 个位（位序由对照解析程序差分定位确认）
MARKING_BITS = [("edges", 0), ("threshold", 1), ("alternateThreshold", 13), ("fixedDistance", 2),
                ("alternateFixedDistance", 14), ("touchdown", 3), ("alternateTouchdown", 15),
                ("dashes", 4), ("ident", 5), ("precision", 6), ("edgePavement", 7), ("singleEnd", 8),
                ("primaryClosed", 9), ("secondaryClosed", 10), ("primaryStol", 11), ("secondaryStol", 12)]


def markings_attrs(bits, extra=0):
    """Markings 位域 → 属性串。extra 为跑道记录的灯光字节（Markings 的 m_raw 取 +48..50，
    故 alternatePrecision/leadingZeroIdent/noThresholdEndArrows 来自该字节的 bit5/6/7）。"""
    out = []
    for nm, bit in MARKING_BITS:
        out.append('%s="%s"' % (nm, "TRUE" if (bits >> bit) & 1 else "FALSE"))
    out.insert(9, 'leadingZeroIdent="%s"' % _tf_b((extra >> 6) & 1))
    out.insert(11, 'alternatePrecision="%s"' % _tf_b((extra >> 5) & 1))
    out.append('noThresholdEndArrows="%s"' % _tf_b((extra >> 7) & 1))
    return " ".join(out)


def _tf_b(v):
    return "TRUE" if v else "FALSE"


def _surface(kp):
    """表面材质（对照解析程序：raw==0 即默认 CONCRETE 时属性整体省略）"""
    raw = u16(kp, 0)
    return SURFACE_TYPE.get(raw, "UNKNOWN") if raw else None


def _surf_attr(kp):
    s = _surface(kp)
    return ' surface="%s"' % s if s else ""


def runway_children(pay, rep):
    """跑道基记录（0x60 字节）之后的内嵌子记录 → 按 bglcomp.xsd 的顺序拼成跑道子元素"""
    parts = {"def": [], "offset": [], "blast": [], "overrun": [], "approach": [], "vasi": [],
             "material": []}
    pos = 0x60 - 6
    while pos + 6 <= len(pay):
        krid, ksz = u16(pay, pos), u32(pay, pos + 2)
        if ksz < 6 or pos + ksz > len(pay):
            break
        kp = pay[pos + 6:pos + ksz]
        pos += ksz
        if krid == 0x3E and len(kp) >= 18:                     # RunwayDeformation
            cb, ca = f32(kp, 10), f32(kp, 14)
            extra = ""
            if cb == cb and cb != 0.0:
                extra += ' controlPointBefore="%.6f"' % cb
            if ca == ca and ca != 0.0:
                extra += ' controlPointAfter="%.6f"' % ca
            parts["def"].append('\n\t\t\t<RunwayDeformation alt="%.6f" ratio="%.6f"%s/>'
                                % (f32(kp, 6), f32(kp, 2), extra))
            rep["counts"]["runway_deformation"] += 1
        elif krid in (0x0B, 0x0C, 0x0D, 0x0E) and len(kp) >= 18:   # Vasi
            parts["vasi"].append('\n\t\t\t<Vasi end="%s" side="%s" type="%s" biasX="%.6f" '
                                 'biasZ="%.6f" spacing="%.6f" pitch="%.6f"/>'
                                 % ("PRIMARY" if krid in (0x0B, 0x0C) else "SECONDARY",
                                    "LEFT" if krid in (0x0B, 0x0D) else "RIGHT",
                                    VASI_TYPE.get(u16(kp, 0), "PAPI4"),
                                    f32(kp, 2), f32(kp, 6), f32(kp, 10), f32(kp, 14)))
            rep["counts"]["vasi"] += 1
        elif krid in (0x0F, 0x10, 0xDF, 0xE0) and len(kp) >= 18:    # ApproachLights
            bits = u16(kp, 0)
            parts["approach"].append('\n\t\t\t<ApproachLights end="%s" system="%s" strobes="%d" '
                                     'endLights="%s" touchdown="%s" snapToGround="%s" reil="%s" '
                                     'offset="%.6f" spacing="%.6f" slope="%.6f"/>'
                                     % ("PRIMARY" if krid in (0x0F, 0xDF) else "SECONDARY",
                                        APPROACH_LIGHTS.get(bits & 0x0F, "NONE"), (bits >> 8) & 0xFF,
                                        "TRUE" if bits & 0x20 else "FALSE",
                                        "TRUE" if bits & 0x80 else "FALSE",
                                        "TRUE" if (len(kp) > 14 and kp[14]) else "FALSE",
                                        "TRUE" if bits & 0x40 else "FALSE",
                                        f32(kp, 6), f32(kp, 2), f32(kp, 10)))
            rep["counts"]["approach_lights"] += 1
        elif krid in (0x05, 0x06) and len(kp) >= 10:           # OffsetThreshold
            parts["offset"].append('\n\t\t\t<OffsetThreshold end="%s" length="%.14f" width="%.14f"%s/>'
                                   % ("PRIMARY" if krid == 0x05 else "SECONDARY",
                                      f32(kp, 2), f32(kp, 6), _surf_attr(kp)))
            rep["counts"]["offset_threshold"] += 1
        elif krid in (0x07, 0x08) and len(kp) >= 10:           # BlastPad
            parts["blast"].append('\n\t\t\t<BlastPad end="%s" length="%.14f" width="%.14f"%s/>'
                                  % ("PRIMARY" if krid == 0x07 else "SECONDARY",
                                     f32(kp, 2), f32(kp, 6), _surf_attr(kp)))
            rep["counts"]["blast_pad"] += 1
        elif krid in (0x09, 0x0A, 0x65, 0x66) and len(kp) >= 10:    # Overrun
            parts["overrun"].append('\n\t\t\t<Overrun end="%s" length="%.14f" width="%.14f"%s/>'
                                    % ("PRIMARY" if krid in (0x09, 0x65) else "SECONDARY",
                                       f32(kp, 2), f32(kp, 6), _surf_attr(kp)))
            rep["counts"]["overrun"] += 1
        elif krid == 0xCB and len(kp) >= 38:                   # FacilityMaterial → <Material>
            parts["material"].append('\n\t\t\t<Material guid="%s" type="%d" tilingU="%.6f" '
                                     'tilingV="%.6f" width="%.6f" falloff="%.6f"/>'
                                     % (guid(kp[2:18]), kp[0], f32(kp, 22), f32(kp, 26),
                                        f32(kp, 30), f32(kp, 34)))
            rep["counts"]["facility_material"] += 1
        else:
            rep["unknown"].append("runway child id %#06x size %d" % (krid, len(kp)))
    return parts


# 跑道元素内为 Ils / RunwayStart 预留的槽位（子记录可能出现在跑道记录之后，故延后填入）
_IS2020 = False

ILS_SLOT = "\x01ILS\x01"
START_SLOT = "\x01START\x01"
START_TYPE = {0: "UNKNOWN", 1: "RUNWAY", 2: "WATER", 3: "HELIPAD", 4: "TRACK"}


# ======================= CVX（section 0x65 矢量/地形） =======================
# 属性 GUID → (值类型, XML type, XML name)，取自对照解析程序的属性映射表
CVX_ATTR = {
    "CE85242F-4110-4706-8344-1F3A8EE422BE": ("string", "STRING", "Version"),
    "359C73E8-06BE-4FB2-ABCB-EC942F7761D0": ("Guid", "GUID", "AirportBounds"),
    "1B6A15BB-05FB-4401-A8D1-BB520E84904C": ("Guid", "GUID", "Texture"),
    "5548FDB5-2267-4328-8E6F-FD0A45ADEC8F": ("float", "FLOAT32", "FalloffDistance"),
    "065E9D4D-6984-4D2A-91FD-3C33C4F53B22": ("byte", "UINT8", "FlattenMode"),
    "5C1A2387-1F07-47DF-A569-962CF6258E55": ("byte", "UINT8", "ExcludeDetectedBuildings"),
    "F3C2635D-9F2F-458F-8663-90B3837BED09": ("byte", "UINT8", "ExcludeOSMBuildings"),
    "F78A3074-8AD5-4B8B-92C4-C1C948BB7AA5": ("byte", "UINT8", "ExcludeMSBuildings"),
    "6A043F59-E6F2-4117-A2E4-D510E7317C29": ("uint", "UINT32", "VegetationScale"),
    "0A685EB0-0E01-44FE-B9EF-BFFFBC968ADE": ("byte", "UINT8", "LandClassRemap"),
    "CD28EFD0-D3F0-43B6-9F88-4E4707344A04": ("Guid", "GUID", "MaterialGUID"),
    "18B58CBF-AE02-4A19-8AA9-3809E8E73400": ("byte", "UINT8", "ExcludeTIN"),
    "4C252581-63E9-4C22-8A3D-14B31F3C8157": ("byte", "UINT8", "BuildingTIN"),
    "69A63EDD-FBE5-4F0D-88E6-6FA01963D613": ("byte", "UINT8", "ForceDetectedBuilding"),
    "41EFF715-C392-4B31-A457-50A504353A90": ("uint", "UINT32", "VegetationDensity"),
    "9E2B4C3E-7D84-453F-9DCC-B6498FF46703": ("uint", "UINT32", "Layer"),
    "4CACC252-E6DC-419A-B20C-16EC601DF70E": ("uint", "UINT32", "ExclusionFlags"),
    "F60DBBC7-DE6F-4FEA-BE7E-AFB1D73D57E7": ("byte", "UINT8", "AffectRocks"),
    "F104723A-D6D1-4B2E-9B44-ACCD8AB372DC": ("byte", "UINT8", "ExcludeRocks"),
    "9460843D-964B-4E45-AC49-634856FB6E1C": ("byte", "UINT8", "ForceElevation"),
    "E82ABE17-FB4C-4F67-A28C-ED41969AEAD6": ("float", "FLOAT32", "VegetationFalloff"),
    "684AFC09-9B38-4431-8D76-E825F54A4DFF": ("byte", "UINT8", "IsWater"),
    "972B7BAC-F620-4D6E-9724-E70BF8A450DD": ("byte", "UINT8", "IsWaterExclusion"),
    "3F8514F8-FAA8-4B94-AB7F-DC2078A4B888": ("uint", "UINT32", "WaterType"),
    "86A147E9-ACF2-4780-9D3C-416373ECB451": ("byte", "UINT8", "AirportSize"),
    "8C1A396B-F730-4128-981A-C90600F856E0": ("uint", "UINT32", "EcoRegion"),
    "09409810-AD40-48DE-A209-DB1CB10601F7": ("uint", "UINT32", "PotentialNaturalVegetation"),
    "F8A7B13F-BD91-48F8-AC66-6C8601A2F1C6": ("byte", "UINT8", "IsAirportInternational"),
    "C4EC4055-3177-4757-82FB-44038B244BA9": ("byte", "UINT8", "IsArtificialSurface"),
    "63040596-0B21-48FD-8B5F-A9E84A5B7BC9": ("uint", "UINT", "TreeBrightnessFactor"),
    "4D2A51D4-91AC-412F-833E-212CC10E5FBC": ("byte", "UINT8", "PreciseTerraforming"),
    "302AC02A-007B-493D-A1B8-4E7A408304BF": ("bytes", "RAW", "FlattenData"),
    "99312E49-88B1-470E-BD06-CA3A6A8C53CF": ("float", "FLOAT32", "Width"),
    "F0B11821-16FC-407B-BE5A-DBEB67A77571": ("string", "STRING", "GeomeName"),
}
CVX_G_VERSION = "CE85242F-4110-4706-8344-1F3A8EE422BE"
CVX_G_BOUNDS = "359C73E8-06BE-4FB2-ABCB-EC942F7761D0"
CVX_G_WIDTH = "99312E49-88B1-470E-BD06-CA3A6A8C53CF"
CVX_G_FALLOFF = "5548FDB5-2267-4328-8E6F-FD0A45ADEC8F"
CVX_G_TEXTURE = "1B6A15BB-05FB-4401-A8D1-BB520E84904C"
CVX_G_LAYER = "9E2B4C3E-7D84-453F-9DCC-B6498FF46703"
CVX_G_FLATTEN = "065E9D4D-6984-4D2A-91FD-3C33C4F53B22"
CVX_G_PRECISION = "4D2A51D4-91AC-412F-833E-212CC10E5FBC"
CVX_G_FLATTEN_DATA = "302AC02A-007B-493D-A1B8-4E7A408304BF"
CVX_G_FORCE_ELEV = "9460843D-964B-4E45-AC49-634856FB6E1C"
CVX_G_HEIGHTMAP = "B7DCEA33-BD4B-4B3C-B4E2-8ECB145CB629"
CVX_NON_ATTR = (CVX_G_WIDTH, CVX_G_FLATTEN_DATA)
CVX_TOL = 1e-05
CVX_DISPLAY = {0: "None", 1: "PointsOnly", 2: "Lines", 3: "Polygon"}


def _cvx_guid(b, o):
    """CVX 的 GUID：前 3 段按小端 u32/u16/u16 读取（与我们其它地方一致）。"""
    return guid(b[o:o + 16])


def cvx_qmid(raw_a, raw_b):
    """QMID 四叉树单元 → (level, u, v, min_lon, max_lon, min_lat, max_lat)。"""
    u = v = 0
    i = 31
    num4 = raw_a & 0xFFFFFFFF
    num5 = raw_b & 0xFFFFFFFF
    while i > 0 and not (num5 & 0x80000000):
        num5 = ((num5 << 2) + ((num4 & 0xC0000000) >> 30)) & 0xFFFFFFFF
        num4 = (num4 * 4) & 0xFFFFFFFF
        i -= 1
    num5 &= 0x7FFFFFFF
    level = i
    while i >= 0:
        if num5 & 0x80000000:
            v += 1 << i
        if num5 & 0x40000000:
            u += 1 << i
        num5 = (num5 << 2) & 0xFFFFFFFF
        i -= 1
    n = 2.0 ** level
    lon_span = 480.0 / n
    lat_span = 360.0 / n
    min_lon = -180.0 + u * lon_span
    max_lat = 90.0 - v * lat_span
    return level, u, v, min_lon, min_lon + lon_span, max_lat - lat_span, max_lat


def cvx_attr_value(gu, raw):
    """属性原始值 → (value 字符串, fs_type, XML name)；未知 GUID 返回 None。"""
    meta = CVX_ATTR.get(gu)
    if meta is None:
        return None
    vt, fs, name = meta
    if vt == "byte":
        val = str(raw[0]) if raw else ""
    elif vt == "uint":
        val = str(u32(raw, 0)) if len(raw) >= 4 else ""
    elif vt == "float":
        val = repr(f32(raw, 0)) if len(raw) >= 4 else ""
    elif vt == "Guid":
        val = guid(raw[:16]) if len(raw) >= 16 else None
    elif vt == "string":
        val = cstr(raw, 0)
    elif vt == "bytes":
        val = raw.hex() if raw else ""
    else:
        val = None
    return val, fs, name


def cvx_attrs(buf):
    """属性缓冲区：16B GUID + i32 大小 + 值（不补齐），返回 {偏移: 属性}。"""
    out = {}
    i = 0
    while i + 20 <= len(buf):
        gd = _cvx_guid(buf, i)
        size = i32(buf, i + 16)
        if size < 0 or i + 20 + size > len(buf):
            break
        raw = buf[i + 20:i + 20 + size]
        dec = cvx_attr_value(gd.strip("{}").upper(), raw)
        name = dec[2] if dec else None
        out[i] = {"guid": gd, "gu": gd.strip("{}").upper(), "raw": raw, "off": i,
                  "name": name, "fstype": (dec[1] if dec else "UNKNOWN"),
                  "value": (dec[0] if dec else None)}
        i += 20 + size
    return out


def _cvx_method2(data, point_ct):
    """位打包点解码（与对照解析程序逐位等价，含跨 32 位字拼接）。返回 (值数组, 消耗字节数)。"""
    arr = [0] * (2 * point_ct)
    if point_ct == 0:
        return arr, 0
    pos = 0
    b = data[0]
    pos = 1
    i2 = i3 = i4 = 0
    num5 = (b * point_ct * 2 + 7) >> 3
    num6 = (1 << b) - 1
    data_size = num5 + 1
    if num5:
        if num5 >= 4:
            word = u32(data, pos)
            num5 -= 4
            pos += 4
        else:
            chunk = data[pos:pos + num5]
            word = struct.unpack("<I", chunk + b"\x00" * (4 - len(chunk)))[0]
            num5 = 0
            pos = len(data)
        while i3 < point_ct:
            if i4 < 0:
                arr[i3 * 2 + i2] += (word << (-i4)) & num6
            else:
                arr[i3 * 2 + i2] = (word >> i4) & num6
            if b + i4 >= 32:
                if num5 >= 4:
                    word = u32(data, pos)
                    num5 -= 4
                    pos += 4
                else:
                    chunk = data[pos:pos + num5]
                    word = struct.unpack("<I", chunk + b"\x00" * (4 - len(chunk)))[0]
                    num5 = 0
                    pos += len(chunk)
                i4 -= 32
            else:
                i4 += b
                i2 += 1
                if i2 == 2:
                    i3 += 1
                    i2 = 0
    return arr, data_size


def cvx_segment(data, ver, qmid):
    """一条图形段 → (点列表 [(lon,lat,alt)], 记录长度, 是否用到外部解码器)。"""
    if len(data) < 6:
        return [], 0, False
    if ver == 7:
        if len(data) < 10:
            return [], 0, False
        point_ct = u32(data, 4)
        alt_raw, method = data[8], data[9]
        pos = 10
    else:
        point_ct = u32(data, 0)
        alt_raw, method = data[4], data[5]
        pos = 6
    if alt_raw == 1:
        alt_type = "D"
    elif alt_raw == 2 and ver == 6:
        alt_type = "S"
    elif alt_raw == 4 and ver == 7:
        alt_type = "S"
    elif alt_raw == 6:
        # 2024 新出现的高度类型：整条图形只带一个 f32 高度（长度算出来与 2/4 同构），
        # 但点数据的编码还不是这一套 —— 长度照算、图形先跳过，别把解错的坐标写进 XML。
        alt_type = "S"
    elif alt_raw == 0:
        alt_type = "N"
    else:
        return [], 0, False
    alt6 = alt_raw == 6
    unsupported = False
    if method == 0:
        raw_pts, size = [], 8 * point_ct
        i = 0
        while i + 8 <= len(data):
            if i >= size:
                break
            raw_pts.append(u32(data, i))
            raw_pts.append(u32(data, i + 4))
            i += 8
    elif method == 2:
        raw_pts, size = _cvx_method2(data[pos:], point_ct)
    elif method == 1:
        # 对照解析程序也无法解码（需要 ExtractorLibrary.dll），但记录长度可以算出来
        unsupported = True
        raw_pts = []
        pay = u32(data, 22) if (point_ct and len(data) >= 26) else 0
        size = (pay + 20) if point_ct else 0
        pos = 6 + size
        if alt_type == "D":
            pos += 4 * point_ct
        elif alt_type == "S":
            pos += 4
        return [], pos, True
    else:
        return [], 0, False
    pos += size
    if alt6:
        # 点编码未解：长度已知（点数据 + 1 个 f32 高度），实体继续往后走但不产出图形
        return [], pos + 4, True
    alts = []
    if alt_type == "D":
        for _ in range(point_ct):
            if pos + 4 > len(data):
                break
            alts.append(f32(data, pos))
            pos += 4
    elif alt_type == "S":
        if pos + 4 <= len(data):
            alts.append(f32(data, pos))
            pos += 4
    rec = pos
    if len(raw_pts) % 2:
        return [], rec, unsupported
    lon_s = (qmid[4] - qmid[3]) / 32768.0
    lat_s = (qmid[6] - qmid[5]) / 32768.0
    pts = []
    ai = 0
    for i in range(0, len(raw_pts), 2):
        lon = qmid[3] + lon_s * raw_pts[i]
        lat = qmid[5] + lat_s * raw_pts[i + 1]
        alt = None
        if alts:
            if ai >= len(alts):
                return [], rec, unsupported
            alt = alts[ai]
            if len(alts) > 1:
                ai += 1
        pts.append((lon, lat, alt))
    return pts, rec, unsupported


def cvx_entities(blob, base_off, rep):
    """一个 CVX 区块 → 实体列表。"""
    if len(blob) < 32:
        return []
    ver = u32(blob, 0)
    if ver not in (6, 7):
        rep["unknown"].append("CVX 版本 %d 不支持" % ver)
        return []
    qmid = cvx_qmid(u32(blob, 4), u32(blob, 8))
    ent_ct = u32(blob, 12)
    attr_sz = u32(blob, 16)
    pos = 32 if ver == 6 else 24
    attrs = cvx_attrs(blob[pos:pos + attr_sz])
    pos += attr_sz
    out = []
    for _ in range(ent_ct):
        if pos + 10 > len(blob):
            break
        seg_ct = u32(blob, pos)
        disp_raw = u32(blob, pos + 4)
        dtype = CVX_DISPLAY.get(disp_raw, "Unknown")
        act = u16(blob, pos + 8)
        epos = pos + 10 + 4 * act
        if epos > len(blob):
            break
        if dtype == "Unknown" or seg_ct > 10000:
            # 显示方式不在枚举内/段数不合理 = 实体表已经失步，整块放弃（只报一次，别级联出假记录）
            rep["unknown"].append("CVX 块 @0x%x 实体表失步（displayMethod=%d segments=%d），本块后续图形跳过"
                                  % (base_off, disp_raw, seg_ct))
            break
        alist = []
        for k in range(act):
            a = attrs.get(u32(blob, pos + 10 + 4 * k))
            if a is not None:
                alist.append(a)
        segs = []
        for _s in range(seg_ct):
            if epos + 6 > len(blob):
                segs = []
                break
            pts, size, ext = cvx_segment(blob[epos:], ver, qmid)
            if size <= 0:
                break
            if ext:
                rep["counts"]["cvx_ext_segment"] += 1
            segs.append(pts)
            epos += size
        size = epos - pos
        if size <= 0:
            break
        out.append({"type": dtype, "attrs": alist, "segments": segs,
                    "off": base_off + pos, "size": size})
        pos += size
    return out


def _cvx_synth_guid(seed):
    h = hashlib.md5(str(seed).encode()).digest()
    d1 = int.from_bytes(h[0:4], "little")
    d2 = int.from_bytes(h[4:6], "little")
    d3 = (int.from_bytes(h[6:8], "little") & 0x0FFF) | 0x4000
    return "{%08X-%04X-%04X-%s-%s}" % (d1, d2, d3, h[8:10].hex().upper(), h[10:16].hex().upper())


def _cvx_poly_points(ent):
    if not ent["segments"]:
        return []
    pts = [(p[0], p[1]) for p in ent["segments"][0]]
    if len(pts) > 1 and abs(pts[0][0] - pts[-1][0]) < CVX_TOL and abs(pts[0][1] - pts[-1][1]) < CVX_TOL:
        pts = pts[:-1]
    return pts


def _cvx_match(a, b):
    return abs(a[0] - b[0]) < CVX_TOL and abs(a[1] - b[1]) < CVX_TOL


def _cvx_angle_sort(points):
    if not points:
        return []
    cx = sum(p[0] for p in points) / len(points)
    cy = sum(p[1] for p in points) / len(points)
    return sorted(points, key=lambda p: math.atan2(p[1] - cy, p[0] - cx))


def _cvx_merge_pair(pa, pb):
    shared = [a for a in pa for b in pb if _cvx_match(a, b)]
    if len(shared) < 2:
        return None
    merged = []
    for p in list(pa) + list(pb):
        if any(_cvx_match(p, s) for s in shared):
            continue
        if any(_cvx_match(p, q) for q in merged):
            continue
        merged.append(p)
    return _cvx_angle_sort(merged)


def _cvx_attrs_sorted(ent):
    out = []
    for a in sorted(ent["attrs"], key=lambda x: x["off"]):
        if a["gu"] == CVX_G_VERSION or a["gu"] in CVX_NON_ATTR:
            continue
        if a["name"]:
            out.append(a)
    return out


def _cvx_attr_xml(a):
    return '\n\t\t<Attribute name="%s" guid="%s" type="%s" value="%s"/>' % (
        xesc(a["name"]), a["guid"], xesc(a["fstype"]), xesc(a["value"]))


def _cvx_polygon_single(ent, uniq, pg, gi):
    """单实体多边形（cvx_to_polygon_element：属性顺序 version,parentGroupID,groupIndex,altitude）"""
    head = ""
    for a in ent["attrs"]:
        if not _IS2020 and a["gu"] == CVX_G_VERSION and a["value"] and str(a["value"]).startswith("0.4"):
            head += ' version="%s"' % xesc(a["value"])
            break
    pts = ent["segments"][0] if ent["segments"] else []
    body = ""
    if pts and pts[0][2] is not None:
        body += ' altitude="%.14f"' % pts[0][2]
    out = ('\n\t<Polygon%s parentGroupID="%d" groupIndex="%d"%s>'
           % (head, pg, gi, body))
    out += ('\n\t\t<Attribute name="UniqueGUID" guid="{%s}" type="GUID" value="%s"/>'
            % (CVX_G_BOUNDS, uniq))
    for a in _cvx_attrs_sorted(ent):
        out += _cvx_attr_xml(a)
    pl = [(p[0], p[1]) for p in pts]
    if len(pl) > 1 and abs(pl[0][0] - pl[-1][0]) < 1e-09 and abs(pl[0][1] - pl[-1][1]) < 1e-09:
        pl = pl[:-1]
    for lon, lat in pl:
        out += '\n\t\t<Vertex lat="%.14f" lon="%.14f"/>' % (lat, lon)
    return out + "\n\t</Polygon>"


def _cvx_polygon_merged(points, pg, gi, uniq, ent):
    """合并多边形（_polygon_from_points：属性顺序 version,altitude,parentGroupID,groupIndex）"""
    head = ""
    if ent is not None:
        for a in ent["attrs"]:
            if not _IS2020 and a["gu"] == CVX_G_VERSION and a["value"] and str(a["value"]).startswith("0.4"):
                head += ' version="%s"' % xesc(a["value"])
        seg = ent["segments"][0] if ent["segments"] else []
        if seg and seg[0][2] is not None:
            head += ' altitude="%.14f"' % seg[0][2]
    out = ('\n\t<Polygon%s parentGroupID="%d" groupIndex="%d">' % (head, pg, gi))
    out += ('\n\t\t<Attribute name="UniqueGUID" guid="{%s}" type="GUID" value="%s"/>'
            % (CVX_G_BOUNDS, uniq))
    if ent is not None:
        for a in _cvx_attrs_sorted(ent):
            out += _cvx_attr_xml(a)
    for lon, lat in points:
        out += '\n\t\t<Vertex lat="%.14f" lon="%.14f"/>' % (lat, lon)
    return out + "\n\t</Polygon>"


def _cvx_rectangle(ent, pg, gi):
    if not ent["segments"] or len(ent["segments"][0]) < 2:
        return ""
    width = falloff = surface = None
    precision = True
    flatten_data = b""
    layer = 0
    hm_raw = None
    force_elev = False
    for a in ent["attrs"]:
        g, raw = a["gu"], a["raw"]
        if g == CVX_G_WIDTH and len(raw) == 4:
            width = f32(raw, 0)
        elif g == CVX_G_FALLOFF and a["value"]:
            falloff = float(a["value"])
        elif g == CVX_G_TEXTURE and a["value"]:
            surface = a["value"]
        elif g == CVX_G_PRECISION and raw:
            precision = raw[0] != 0
        elif g == CVX_G_FLATTEN_DATA and raw:
            flatten_data = raw
        elif g == CVX_G_LAYER and len(raw) >= 4:
            layer = u32(raw, 0)
        elif g == CVX_G_HEIGHTMAP and raw:
            hm_raw = raw
        elif g == CVX_G_FORCE_ELEV and raw:
            force_elev = raw[0] != 0
    p0, p1 = ent["segments"][0][0], ent["segments"][0][1]
    out = ('\n\t<Rectangle parentGroupID="%d" groupIndex="%d" width="%.6f" falloff="%.6f"%s '
           'priority="%d" precision="%s"%s'
           % (pg, gi, width if width is not None else 0.0,
              falloff if falloff is not None else 0.0,
              (' surface="%s"' % xesc(surface)) if surface else "", layer,
              "TRUE" if precision else "FALSE",
              ' forceElevation="TRUE"' if (force_elev and not _IS2020) else ""))
    out += ' latitude="%.14f" longitude="%.14f" altitude="%.14f"' % (
        p0[1], p0[0], p0[2] if p0[2] is not None else 0.0)
    out += ' latitude2="%.14f" longitude2="%.14f" altitude2="%.14f"' % (
        p1[1], p1[0], p1[2] if p1[2] is not None else 0.0)
    kids = ""
    i = 0
    while i + 16 <= len(flatten_data):
        alt, ratio, cpb, cpa = struct.unpack_from("<4f", flatten_data, i)
        kids += '\n\t\t<RunwayDeformation alt="%.6f" ratio="%.6f"' % (alt, ratio)
        if ratio != 0.0 and ratio != 1.0:
            if cpb == cpb:
                kids += ' controlPointBefore="%.6f"' % cpb
            if cpa == cpa:
                kids += ' controlPointAfter="%.6f"' % cpa
        kids += "/>"
        i += 16
    if hm_raw and len(hm_raw) >= 12:
        hm_w, hm_h = u16(hm_raw, 0), u16(hm_raw, 2)
        hm_min, hm_max = f32(hm_raw, 4), f32(hm_raw, 8)
        scale = (hm_max - hm_min) / 32768.0
        vals = []
        for k in range(min(hm_w * hm_h, (len(hm_raw) - 12) // 2)):
            vals.append("%.6f" % (hm_min + u16(hm_raw, 12 + k * 2) * scale))
        if vals:
            kids += '\n\t\t<Heightmap width="%d" data="%s"/>' % (hm_w, " ".join(vals))
    if not kids:
        return out + "/>"
    return out + ">" + kids + "\n\t</Rectangle>"


def cvx_elements(g, rep):
    """所有 CVX 区块 → FSData 级的 Polygon / Rectangle 元素（对照解析程序顺序：先多边形后矩形）。"""
    ents = []
    for blob, chunk in g.data_of(0x65):
        ents.extend(cvx_entities(blob, chunk["off"], rep))
    polys, rects, poly_ents = [], [], []
    for e in ents:
        if not e["segments"] or not e["segments"][0]:
            continue
        gids = [a["gu"] for a in e["attrs"]]
        pg = 7 if CVX_G_FLATTEN in gids else 2
        if e["type"] == "Polygon":
            poly_ents.append((e, pg))
        elif e["type"] == "Lines" and len(e["segments"][0]) == 2:
            rects.append(_cvx_rectangle(e, pg, len(rects) + 1))
    used = set()
    for i in range(len(poly_ents)):
        if i in used:
            continue
        used.add(i)
        ent_i, pg_i = poly_ents[i]
        merged = _cvx_poly_points(ent_i)
        changed = True
        while changed:
            changed = False
            for j in range(len(poly_ents)):
                if j in used or poly_ents[j][1] != pg_i:
                    continue
                m = _cvx_merge_pair(merged, _cvx_poly_points(poly_ents[j][0]))
                if m is None:
                    continue
                merged = m
                used.add(j)
                changed = True
        gi = len(polys) + 1
        uniq = _cvx_synth_guid(ent_i["off"])
        if len(used) > 1:
            polys.append((pg_i, _cvx_polygon_merged(merged, pg_i, gi, uniq, ent_i)))
        else:
            polys.append((pg_i, _cvx_polygon_single(ent_i, uniq, pg_i, gi)))
    polys.sort(key=lambda t: t[0])
    rep["counts"]["cvx_polygon"] += len(polys)
    rep["counts"]["cvx_rectangle"] += len([r for r in rects if r])
    out = [p[1] for p in polys] + [r for r in rects if r]
    return out


# ======================= 排除矩形（section 0x2E） =======================
# 标志位 → 属性名（misc_missing.ExclusionRectangle._FLAG_BITS）
EXCL_FLAGS = [(3, "excludeAllObjects"), (4, "excludeBeaconObjects"), (5, "excludeEffectObjects"),
              (6, "excludeGenericBuildingObjects"), (7, "excludeLibraryObjects"),
              (8, "excludeTaxiwaySignObjects"), (9, "excludeTriggerObjects"),
              (10, "excludeWindsockObjects"), (11, "excludeExtrusionBridgeObjects"),
              (12, "excludeSimObjects"), (13, "excludeWorldScripts"), (14, "excludeCarParking"),
              (15, "excludeRectangles"), (16, "excludePolygons")]


def _cvx_lon(raw):
    return 0.0 if raw == 0 else raw * 4.470348358154297e-07 - 180.0


def _cvx_lat(raw):
    return 0.0 if raw == 0 else 90.0 - raw * 3.3527612686157227e-07


def exclusion_elements(g, rep):
    """section 0x2E：定长 20 字节记录（无记录头）→ FSData 级 <ExclusionRectangle>。"""
    out = []
    for blob, chunk in g.data_of(0x2E):
        n = min(chunk["nrec"], len(blob) // 20)
        for k in range(n):
            rec = blob[k * 20:(k + 1) * 20]
            if len(rec) < 20:
                break
            flags = u32(rec, 0)
            lon_min = _cvx_lon(i32(rec, 4))
            lat_max = _cvx_lat(i32(rec, 8))
            lon_max = _cvx_lon(i32(rec, 12))
            lat_min = _cvx_lat(i32(rec, 16))
            s = ('\t<ExclusionRectangle latitudeMinimum="%.14f" latitudeMaximum="%.14f" '
                 'longitudeMinimum="%.14f" longitudeMaximum="%.14f"'
                 % (lat_min, lat_max, lon_min, lon_max))
            for bit, name in EXCL_FLAGS:
                s += ' %s="%s"' % (name, "TRUE" if (flags >> bit) & 1 else "FALSE")
            out.append(s + "/>")
            rep["counts"]["exclusion"] += 1
    return out


# ======================= 导航台（section 0x13 VorIls） =======================
ILS_SUB_LOCALIZER = 0x14
ILS_SUB_GLIDESLOPE = 0x15
ILS_SUB_DME = 0x16
ILS_SUB_NAME = 0x19
ILS_SUB_LOCALIZER_2024 = 0x115
ILS_SUB_DME_2024 = 0x114
RUNWAY_NUMBER_ENUM = dict([(i, "%02d" % i) for i in range(36)] +
                          [(36, "NORTH"), (37, "NORTHEAST"), (38, "EAST"), (39, "SOUTHEAST"),
                           (40, "SOUTH"), (41, "SOUTHWEST"), (42, "WEST"), (43, "NORTHWEST")])
DESIGNATOR_ENUM = {0: "NONE", 1: "LEFT", 2: "RIGHT", 3: "CENTER", 4: "WATER", 5: "A", 6: "B"}


def _fmt_short(v):
    """_fmt_short：repr(float) 去掉结尾的 .0"""
    s = repr(float(v))
    return s[:-2] if s.endswith(".0") else s


def _fmt_f32(v):
    """_fmt_f32：单精度往返，整数不带小数位，否则取最短能往返的小数位。"""
    f = struct.unpack("<f", struct.pack("<f", float(v)))[0]
    if f != f:
        return "NaN"
    if f == 0.0:
        return "0"
    if abs(f) >= 1e15:
        return repr(f)
    if f == int(f):
        return str(int(f))
    for dec in range(1, 9):
        s = "%.*f" % (dec, f)
        if struct.unpack("<f", struct.pack("<f", float(s)))[0] == f:
            return s
    return repr(f)


def _nav_lon(raw):
    return 0.0 if raw == 0 else raw * 4.470348358154297e-07 - 180.0


def _nav_lat(raw):
    return 0.0 if raw == 0 else 90.0 - raw * 3.3527612686157227e-07


def _nav_alt(raw):
    """海拔（毫米 → 米）：Altitude.meters = f32(raw * f32(0.001))，两次单精度舍入。"""
    return struct.unpack("<f", struct.pack("<f", raw * _F32_0001))[0]


_F32_0001 = struct.unpack("<f", struct.pack("<f", 0.001))[0]


def icao(raw, shift=5):
    """ICAO 标识：base-38 打包（FSTypes.Icao，bit_shift 默认 5）。"""
    n = raw >> shift
    chars = []
    while n > 0:
        n, rem = divmod(n, 38)
        if rem == 0:
            chars.append(" ")
        elif 2 <= rem <= 11:
            chars.append(chr(rem + 46))
        else:
            chars.append(chr(rem + 53))
    return "".join(reversed(chars))


def airport_ident(blob, hid):
    """机场记录的 ICAO 标识：0x0113（2024）@+76 移位 6；0x0056（2020）@+40 移位 5。"""
    if hid == 0x0113 and len(blob) >= 80:
        return icao(u32(blob, 76), 6)
    if len(blob) >= 44:
        return icao(u32(blob, 40), 5)
    return ""


def icao_2024(raw_code, bit_shift=6):
    """icao_2024：2024 版 VorIls 的 ident 可能被整体加了 2^26，按解码可读性择一。"""
    stored = raw_code >> bit_shift

    def valid(v):
        return 1 <= len(v) <= 5 and all(("0" <= ch <= "9") or ("A" <= ch <= "Z") for ch in v)

    c0 = icao(stored, 0)
    if valid(c0) and (len(c0) <= 4 or c0[0].isalpha()):
        return stored
    if valid(icao(stored + 0x04000000, 0)):
        return stored + 0x04000000
    return stored


def nav_records(g, rep):
    """section 0x13：逐条 (u16 类型, u32 长度) 记录 → Ils 结构体列表。"""
    out = []
    for blob, chunk in g.data_of(0x13):
        pos = 0
        while pos + 6 <= len(blob):
            rt, rs = u16(blob, pos), u32(blob, pos + 2)
            if rs < 6 or pos + rs > len(blob):
                break
            if rt in (19, 261, 263):
                rec = blob[pos:pos + rs]
                is24 = rt in (261, 263)
                base = 48 if is24 else 40
                d = {"airport_ident": icao(((u32(rec, 36) if not is24 else u32(rec, 40)) >> 11) & 0x1FFFFF, 0),
                     "ident": icao(icao_2024(u32(rec, 32)), 0) if is24 else icao(u32(rec, 32)),
                     "lon": lonlat(u32(rec, 8), u32(rec, 12))[0],
                     "lat": lonlat(u32(rec, 8), u32(rec, 12))[1],
                     "alt": _nav_alt(i32(rec, 16)),
                     "frequency": u32(rec, 20) / 1000000.0,
                     "range": f32(rec, 24),
                     "magvar": f32(rec, 28),
                     "name": "", "number": "", "designator": "NONE",
                     "heading": 0.0, "width": 0.0, "back_course": False,
                     "dme": [], "glide": []}
                p = base
                while p + 6 <= rs:
                    st, ss = u16(rec, p), u32(rec, p + 2)
                    if ss < 6 or p + ss > rs:
                        break
                    body = rec[p:p + ss]
                    if st in (ILS_SUB_LOCALIZER, ILS_SUB_LOCALIZER_2024) and ss >= 16:
                        d["number"] = RUNWAY_NUMBER_ENUM.get(body[6], "NONE")
                        d["designator"] = DESIGNATOR_ENUM.get(body[7], "NONE")
                        d["heading"] = f32(body, 8)
                        d["width"] = f32(body, 12)
                    elif st == ILS_SUB_GLIDESLOPE and ss >= 28:
                        d["glide"].append({"lon": lonlat(i32(body, 8), i32(body, 12))[0],
                                           "lat": lonlat(i32(body, 8), i32(body, 12))[1],
                                           "alt": _nav_alt(i32(body, 16)), "range": f32(body, 20),
                                           "pitch": f32(body, 24)})
                    elif st in (ILS_SUB_DME, ILS_SUB_DME_2024) and ss >= 24:
                        d["dme"].append({"lon": lonlat(i32(body, 8), i32(body, 12))[0],
                                         "lat": lonlat(i32(body, 8), i32(body, 12))[1],
                                         "alt": _nav_alt(i32(body, 16)), "range": f32(body, 20)})
                    elif st == ILS_SUB_NAME:
                        d["name"] = cstr(body, 6)
                    else:
                        rep["unknown"].append("Ils 子记录 %#06x 长度 %d" % (st, ss))
                    p += ss
                rep["counts"]["ils"] += 1
                out.append(d)
            pos += rs
    return out


def ils_xml(d, end, rep):
    """一条 Ils → <Ils> XML（含 Dme/GlideSlope 子元素）。"""
    freq = ("%.3f" % d["frequency"]).rstrip("0").rstrip(".")
    s = ('\n\t\t\t<Ils lat="%.14f" lon="%.14f" alt="%.14f"' % (d["lat"], d["lon"], d["alt"]))
    if end:
        s += ' end="%s"' % end
    s += ' range="%.14f" ident="%s" magvar="%.6f" heading="%.14f" frequency="%s"' % (
        d["range"], xesc(d["ident"]), d["magvar"], d["heading"], freq)
    if d["name"]:
        s += ' name="%s"' % xesc(d["name"])
    s += ' backCourse="%s">' % ("TRUE" if d["back_course"] else "FALSE")
    for dm in d["dme"]:
        s += ('\n\t\t\t\t<Dme lat="%s" lon="%s" alt="%s" range="%s" />'
              % (_fmt_short(dm["lat"]), _fmt_short(dm["lon"]), _fmt_short(dm["alt"]),
                 _fmt_f32(dm["range"])))
    for gs in d["glide"]:
        s += ('\n\t\t\t\t<GlideSlope lat="%s" lon="%s" alt="%s" range="%s" pitch="%s" />'
              % (_fmt_short(gs["lat"]), _fmt_short(gs["lon"]), _fmt_short(gs["alt"]),
                 _fmt_f32(gs["range"]), _fmt_f32(gs["pitch"])))
    return s + "\n\t\t\t</Ils>"


def _end_matches(ils_desig, rw_desig):
    return (not ils_desig) or ils_desig == "NONE" or ils_desig == rw_desig


def attach_ils(g, ap, runway_meta, airport_nodes, rep):
    """按「机场 + 跑道号 + 方位」把 Ils 挂到跑道上（_propagate 的规则）。"""
    unattached = []
    for d in nav_records(g, rep):
        end = None
        if d["number"] and d["airport_ident"]:
            for rw in runway_meta:
                if d["number"] == rw["sec_num"] and _end_matches(d["designator"], rw["sec_desig"]):
                    rw["ils"].append(ils_xml(d, "SECONDARY", rep))
                    end = "SECONDARY"
                    break
                if d["number"] == rw["pri_num"] and _end_matches(d["designator"], rw["pri_desig"]):
                    rw["ils"].append(ils_xml(d, "PRIMARY", rep))
                    end = "PRIMARY"
                    break
        if end is None:
            unattached.append(ils_xml(d, None, rep))
    for rw in runway_meta:
        if rw["ils"]:
            node = airport_nodes[rw["node"]]
            airport_nodes[rw["node"]] = node.replace(ILS_SLOT, ILS_SLOT + "".join(rw["ils"]))
    return unattached


# ======================= 分组（Group / parentGroupID / groupIndex） =======================
GROUP_DISPLAY = {1: "Buildings", 2: "Exclusion", 3: "Lights", 4: "Other Models",
                 5: "ParkingSigns", 6: "Static Jetways", 7: "Terrain"}
DEFAULT_GROUP = 4
# 库对象 GUID → 分组（group_tables.GUID_TO_GROUP，102 条）
GUID_TO_GROUP = {}
for _gid, _guids in (
    (1, "491E6BE8-25E5-4DC3-8FAF-DEFA14404131 7E5C0613-61EA-4CFD-9537-76C7572BE5E9"),
    (3, "0458C636-D8D2-4860-AB9C-C6E4F3B0EE75 163C942C-189A-4380-8B03-FDEE4ABC525B "
        "25486B7C-2448-4BA3-ADEC-5306C24D3933 470F9B8F-4572-4F10-A3B3-6AB2C278ED03 "
        "8CCCA24B-825F-402D-8D62-AF62D35DB4F4 8EF4C350-65F3-455B-AF52-64511D7F9510 "
        "AEAFBBC0-0436-401C-96DE-384B435FF8A7 C233E165-298F-4606-97AB-4F22DD8EB1B2 "
        "D8F767C2-C20E-4F56-FC9C-0B735CC345F7 DB0162E7-91A2-46E9-81B7-55A66CEC8839 "
        "F3A90285-66E3-4BE7-998F-FDB9CE2091AB"),
    (4, "580D226E-2F7B-4634-9B62-F5163D53259A"),
    (5, "00B2409E-5191-4CDB-9CAC-2AEF86610F17 0221F79A-A6F0-4D12-830D-703166668B89 "
        "06B4607F-D089-45B2-B2BC-C1CAF1B3AA18 0CFB4EE7-F3FC-4EBD-960C-BC3BB0F99B87 "
        "0D36BF7A-5698-4A48-BCB3-5DDD53904999 10925290-FD71-4E17-A3E5-3DE0E22E32D2 "
        "129D1D7E-F668-458E-9E77-01C43E1D3337 142B3D7D-C33D-4713-9B6C-37663B66FA4D "
        "16739808-7DD6-4429-82B2-E72A27557531 17E0D6F5-47E3-4C83-8CE6-3AE4385C2486 "
        "1881ACE9-C886-4304-BD82-E27AABF94285 1AA606E0-8471-42AD-BC1D-EED0937FF08B "
        "1C241AA1-9979-492E-B478-86CAFA4C11DC 1CF1E705-0FF7-4F18-8E1A-A1F12CD15EA9 "
        "2079007E-C359-4FF6-9D29-F27BEB48849A 2ABAA5E8-5960-421C-8C65-D06B421F65E7 "
        "2FC0439E-85BF-4053-B1F2-910D67DBAD08 35134FF7-96F7-4D79-BFBE-9531FA1DB5CD "
        "385691E4-F6AD-41DA-BBB7-DD1BD77C9DF1 38FC15A2-86BF-4FF0-8B4B-45D961A80407 "
        "3F24B66D-1000-4273-8199-E4BB19A4C237 401C107E-8AD6-48EF-BDB7-4B7C9CCAEB57 "
        "461BBB04-C332-4739-ACB0-ACB324FAB58D 4D085A96-39AD-415A-A47F-FA3F886A148D "
        "4D2295A0-5AC0-45D2-9629-14BE4F73478F 50941EF6-AC34-41A9-8CF8-AE42410D0BA1 "
        "512536DF-628F-4E8D-9F90-434C65989A78 51A7DAC7-6CCF-4C70-92DB-80EB441AD6DF "
        "51E9C5C0-3F91-4CF6-857A-4B79757CC677 521E2E9E-12F5-4161-B9CA-62F71B04C83B "
        "5AD54249-AE61-41C9-91CB-6A1E65598473 5C0C733F-A692-4D05-B6CE-7F18D4F58088 "
        "5CF7B9EF-CFED-4E74-B63C-B416944FD2FB 61634292-13E6-4720-AE76-8B5342437DB2 "
        "66138E0B-673E-4908-9C34-21D59ABD0D8F 6D35B8EF-1D49-40E4-B00A-00DF80E7EF7F "
        "6DFE0132-B63F-4278-8744-C218A92FCCD2 70CE6D33-A787-486B-8B22-9BFF76951108 "
        "713E7332-67E0-4524-BD5E-DC0A7E3EDB15 7147B2A9-B275-4A3B-92F7-98F9C29F2113 "
        "72CB3575-DB3B-4E93-A36D-7A3D82D57D13 73F4E3D8-5D70-470E-BD54-393C56BB2D30 "
        "7D52FB16-DF28-4706-84C7-DB071AF45EDE 8040F27F-4247-47A6-86AD-60CEF6E50AC7 "
        "82417EBB-EBBF-4384-AD92-9EA909C58AD7 84F7FA9F-BB2F-401C-AC79-71EE03678BF0 "
        "88C92697-DC9D-4CBD-B25D-698FC01B8D96 90E21025-83C8-4CF7-9E6B-108603398A43 "
        "91183B97-231E-4CA0-AA7E-B0C865999E21 9825E2CE-D3D4-4EC2-8D3A-6229A50EEFAF "
        "99D63003-E93B-4966-AE7C-B05C39350C78 9BE27D74-A0F4-4BB3-991F-794CFFAE6134 "
        "9DC242ED-B303-4896-B103-5A94AA9FFBA0 A477DB0D-DD11-4200-8658-6C846C892862 "
        "ABB0A713-7A59-4192-91D8-BB929159FD8B AEDA1335-7388-4BAD-A66A-0ED674007E2D "
        "B34245C3-CDFC-4956-8707-9852D1272E96 B4C0ABE3-4AF3-4E12-A638-8986B9A9EFCA "
        "B5784522-2CCC-48FB-89F0-1F110091321E B65B486A-BB85-4F5F-B37E-058AA9D91582 "
        "C55F5310-05E5-46AF-868F-35BE47A56702 C57B04EB-ED39-4222-94C3-D0EAB3AEAF39 "
        "CB510ACC-6AD3-4905-AF0D-369D9185D9E0 CE981420-7AB9-414E-90F0-A1462D607719 "
        "D3007B5D-D095-4056-A2C1-C54FB0A337DB D5C0935A-E320-4CC2-9442-32E8B384716C "
        "D654A19D-AFA3-4233-A071-8C539A59C5E5 D69D7878-E2F1-493F-8F50-BFC53F25FFD5 "
        "D6FE7602-643F-43CF-89AE-EC19A8688950 DA00E7DD-BB18-4D87-9814-D310E58E08EB "
        "DA4C8D61-0C2F-46D9-B5B9-B29A75165787 E0A5E1FC-5F14-40AE-82CF-600995310722 "
        "E126A049-B0B1-40B4-AD61-A01BBBE5F6D4 E4E6D353-526B-4039-937C-B8B14B91D468 "
        "EA9F0DA2-DB78-489C-9265-381A41BB26A3 EB282665-8943-4060-A944-50C85CEBEFFC "
        "EB2E40C7-AD80-43D6-A852-27897F9234C5 EB68143B-9F11-42E0-B7F2-BB85C3EBB154 "
        "ED64D5A6-3F4C-4038-91A0-E88CA6D172A8 EDED2F0D-96AF-41DC-A130-256456F73F66 "
        "F2ABF2F9-58D4-4666-9F4B-86FA6BE9424F F4A1438C-0BA8-4556-8F19-578C2B640040 "
        "F9963317-667F-4E3B-B860-A668A4CA9AAA FA556B45-F108-458D-A5E5-CFD4F2844159 "
        "FF06B5A1-612C-4144-8A04-BAE58DD00609"),
    (6, "2F6B0ED1-5A59-4DEA-92FF-5909A95F9D76 31528024-3011-4C43-A8B6-4713BA8C633A "
        "40942401-3BF4-4D47-8F12-554A91EFD0BD"),
):
    for _gu in _guids.split():
        GUID_TO_GROUP["{%s}" % _gu] = _gid
del _gid, _guids, _gu

AIRPORT_SUB_GROUPS = ["Runway", "RunwayMarkings", "PaintedMarkings", "GroundBase", "Centerlines",
                      "Taxiways", "Parkings", "Taxipaths", "Edgelines", "Runway Alarm Lights",
                      "Centerlights", "Edgelights", "TaxiSigns"]
AIRPORT_SUB_PARENTS = {"Runway": None, "RunwayMarkings": "Runway", "PaintedMarkings": None,
                       "GroundBase": None, "Centerlines": "Taxiways", "Taxiways": None,
                       "Parkings": None, "Taxipaths": "Taxiways", "Edgelines": "Taxiways",
                       "Runway Alarm Lights": "Taxiways", "Centerlights": "Taxiways",
                       "Edgelights": "Taxiways", "TaxiSigns": "Taxiways"}
AIRPORT_GROUP_ID = 8            # 7 个景物顶层组（1..7）之后，机场自身组固定为 8
AIRPORT_GROUP_INDEX = 7         # 机场组在组序列中的序号（与对照解析程序一致）
AIRPORT_LEVEL_GROUPS = 7
_SUB_GID = dict((n, AIRPORT_GROUP_ID + i + 1) for i, n in enumerate(AIRPORT_SUB_GROUPS))

SURF_CENTERLINE = "{A789C134-4487-43CB-8981-BAF5FCA23981}"
SURF_EDGELINE_SOLID = "{4EBBBBB6-08A3-4009-BD38-1BA096B75D45}"
SURF_RUNWAY_LINE = "{DAEEABDD-69FC-4E8E-A693-BA2E332533D1}"
SURF_RUNWAY_MARKINGS = "{06C65325-BD2E-41F8-A062-710DC32E42E4}"

# 顶层 SceneryObject 的 LibraryObject GUID → 7 个顶层组（对照解析程序 group_tables.GUID_TO_GROUP，
# 由 2020 ZLIC / ZWTL 参考 XML 统计得到；未知 GUID 归 "Other Models"=4）
DEFAULT_SCENERY_GROUP = 4
GUID_TO_GROUP = {
    '{491E6BE8-25E5-4DC3-8FAF-DEFA14404131}': 1, '{7E5C0613-61EA-4CFD-9537-76C7572BE5E9}': 1,
    '{0458C636-D8D2-4860-AB9C-C6E4F3B0EE75}': 3, '{163C942C-189A-4380-8B03-FDEE4ABC525B}': 3,
    '{25486B7C-2448-4BA3-ADEC-5306C24D3933}': 3, '{470F9B8F-4572-4F10-A3B3-6AB2C278ED03}': 3,
    '{8CCCA24B-825F-402D-8D62-AF62D35DB4F4}': 3, '{8EF4C350-65F3-455B-AF52-64511D7F9510}': 3,
    '{AEAFBBC0-0436-401C-96DE-384B435FF8A7}': 3, '{C233E165-298F-4606-97AB-4F22DD8EB1B2}': 3,
    '{D8F767C2-C20E-4F56-FC9C-0B735CC345F7}': 3, '{DB0162E7-91A2-46E9-81B7-55A66CEC8839}': 3,
    '{F3A90285-66E3-4BE7-998F-FDB9CE2091AB}': 3, '{580D226E-2F7B-4634-9B62-F5163D53259A}': 4,
    '{00B2409E-5191-4CDB-9CAC-2AEF86610F17}': 5, '{0221F79A-A6F0-4D12-830D-703166668B89}': 5,
    '{06B4607F-D089-45B2-B2BC-C1CAF1B3AA18}': 5, '{0CFB4EE7-F3FC-4EBD-960C-BC3BB0F99B87}': 5,
    '{0D36BF7A-5698-4A48-BCB3-5DDD53904999}': 5, '{10925290-FD71-4E17-A3E5-3DE0E22E32D2}': 5,
    '{129D1D7E-F668-458E-9E77-01C43E1D3337}': 5, '{142B3D7D-C33D-4713-9B6C-37663B66FA4D}': 5,
    '{16739808-7DD6-4429-82B2-E72A27557531}': 5, '{17E0D6F5-47E3-4C83-8CE6-3AE4385C2486}': 5,
    '{1881ACE9-C886-4304-BD82-E27AABF94285}': 5, '{1AA606E0-8471-42AD-BC1D-EED0937FF08B}': 5,
    '{1C241AA1-9979-492E-B478-86CAFA4C11DC}': 5, '{1CF1E705-0FF7-4F18-8E1A-A1F12CD15EA9}': 5,
    '{2079007E-C359-4FF6-9D29-F27BEB48849A}': 5, '{2ABAA5E8-5960-421C-8C65-D06B421F65E7}': 5,
    '{2FC0439E-85BF-4053-B1F2-910D67DBAD08}': 5, '{35134FF7-96F7-4D79-BFBE-9531FA1DB5CD}': 5,
    '{385691E4-F6AD-41DA-BBB7-DD1BD77C9DF1}': 5, '{38FC15A2-86BF-4FF0-8B4B-45D961A80407}': 5,
    '{3F24B66D-1000-4273-8199-E4BB19A4C237}': 5, '{401C107E-8AD6-48EF-BDB7-4B7C9CCAEB57}': 5,
    '{461BBB04-C332-4739-ACB0-ACB324FAB58D}': 5, '{4D085A96-39AD-415A-A47F-FA3F886A148D}': 5,
    '{4D2295A0-5AC0-45D2-9629-14BE4F73478F}': 5, '{50941EF6-AC34-41A9-8CF8-AE42410D0BA1}': 5,
    '{512536DF-628F-4E8D-9F90-434C65989A78}': 5, '{51A7DAC7-6CCF-4C70-92DB-80EB441AD6DF}': 5,
    '{51E9C5C0-3F91-4CF6-857A-4B79757CC677}': 5, '{521E2E9E-12F5-4161-B9CA-62F71B04C83B}': 5,
    '{5AD54249-AE61-41C9-91CB-6A1E65598473}': 5, '{5C0C733F-A692-4D05-B6CE-7F18D4F58088}': 5,
    '{5CF7B9EF-CFED-4E74-B63C-B416944FD2FB}': 5, '{61634292-13E6-4720-AE76-8B5342437DB2}': 5,
    '{66138E0B-673E-4908-9C34-21D59ABD0D8F}': 5, '{6D35B8EF-1D49-40E4-B00A-00DF80E7EF7F}': 5,
    '{6DFE0132-B63F-4278-8744-C218A92FCCD2}': 5, '{70CE6D33-A787-486B-8B22-9BFF76951108}': 5,
    '{713E7332-67E0-4524-BD5E-DC0A7E3EDB15}': 5, '{7147B2A9-B275-4A3B-92F7-98F9C29F2113}': 5,
    '{72CB3575-DB3B-4E93-A36D-7A3D82D57D13}': 5, '{73F4E3D8-5D70-470E-BD54-393C56BB2D30}': 5,
    '{7D52FB16-DF28-4706-84C7-DB071AF45EDE}': 5, '{8040F27F-4247-47A6-86AD-60CEF6E50AC7}': 5,
    '{82417EBB-EBBF-4384-AD92-9EA909C58AD7}': 5, '{84F7FA9F-BB2F-401C-AC79-71EE03678BF0}': 5,
    '{88C92697-DC9D-4CBD-B25D-698FC01B8D96}': 5, '{90E21025-83C8-4CF7-9E6B-108603398A43}': 5,
    '{91183B97-231E-4CA0-AA7E-B0C865999E21}': 5, '{9825E2CE-D3D4-4EC2-8D3A-6229A50EEFAF}': 5,
    '{99D63003-E93B-4966-AE7C-B05C39350C78}': 5, '{9BE27D74-A0F4-4BB3-991F-794CFFAE6134}': 5,
    '{9DC242ED-B303-4896-B103-5A94AA9FFBA0}': 5, '{A477DB0D-DD11-4200-8658-6C846C892862}': 5,
    '{ABB0A713-7A59-4192-91D8-BB929159FD8B}': 5, '{AEDA1335-7388-4BAD-A66A-0ED674007E2D}': 5,
    '{B34245C3-CDFC-4956-8707-9852D1272E96}': 5, '{B4C0ABE3-4AF3-4E12-A638-8986B9A9EFCA}': 5,
    '{B5784522-2CCC-48FB-89F0-1F110091321E}': 5, '{B65B486A-BB85-4F5F-B37E-058AA9D91582}': 5,
    '{C55F5310-05E5-46AF-868F-35BE47A56702}': 5, '{C57B04EB-ED39-4222-94C3-D0EAB3AEAF39}': 5,
    '{CB510ACC-6AD3-4905-AF0D-369D9185D9E0}': 5, '{CE981420-7AB9-414E-90F0-A1462D607719}': 5,
    '{D3007B5D-D095-4056-A2C1-C54FB0A337DB}': 5, '{D5C0935A-E320-4CC2-9442-32E8B384716C}': 5,
    '{D654A19D-AFA3-4233-A071-8C539A59C5E5}': 5, '{D69D7878-E2F1-493F-8F50-BFC53F25FFD5}': 5,
    '{D6FE7602-643F-43CF-89AE-EC19A8688950}': 5, '{DA00E7DD-BB18-4D87-9814-D310E58E08EB}': 5,
    '{DA4C8D61-0C2F-46D9-B5B9-B29A75165787}': 5, '{E0A5E1FC-5F14-40AE-82CF-600995310722}': 5,
    '{E126A049-B0B1-40B4-AD61-A01BBBE5F6D4}': 5, '{E4E6D353-526B-4039-937C-B8B14B91D468}': 5,
    '{EA9F0DA2-DB78-489C-9265-381A41BB26A3}': 5, '{EB282665-8943-4060-A944-50C85CEBEFFC}': 5,
    '{EB2E40C7-AD80-43D6-A852-27897F9234C5}': 5, '{EB68143B-9F11-42E0-B7F2-BB85C3EBB154}': 5,
    '{ED64D5A6-3F4C-4038-91A0-E88CA6D172A8}': 5, '{EDED2F0D-96AF-41DC-A130-256456F73F66}': 5,
    '{F2ABF2F9-58D4-4666-9F4B-86FA6BE9424F}': 5, '{F4A1438C-0BA8-4556-8F19-578C2B640040}': 5,
    '{F9963317-667F-4E3B-B860-A668A4CA9AAA}': 5, '{FA556B45-F108-458D-A5E5-CFD4F2844159}': 5,
    '{FF06B5A1-612C-4144-8A04-BAE58DD00609}': 5, '{2F6B0ED1-5A59-4DEA-92FF-5909A95F9D76}': 6,
    '{31528024-3011-4C43-A8B6-4713BA8C633A}': 6, '{40942401-3BF4-4D47-8F12-554A91EFD0BD}': 6,
}

_ATTR_RE = re.compile(r'([A-Za-z_][\w.]*)\s*=\s*"([^"]*)"')


def node_attrs(s):
    """取节点串首元素上的属性字典（与属性顺序无关）。"""
    p = s.find("<")
    if p < 0:
        return {}
    q = s.find(">", p)
    return dict(_ATTR_RE.findall(s[p:q if q > 0 else len(s)]))


def node_tag(s):
    """取节点串首元素名（与 tag_name 同义，分组分类用）。"""
    return tag_name(s)


def classify_apron(a):
    """classify_apron：非 localUV 的停机坪 → GroundBase；跑道标线材质 → RunwayMarkings。"""
    if str(a.get("localUV", "FALSE")).upper() != "TRUE":
        return "GroundBase"
    if a.get("priority") == "1000000012":
        return "RunwayMarkings"
    if a.get("surface") == SURF_RUNWAY_MARKINGS:
        return "RunwayMarkings"
    return "PaintedMarkings"


def classify_painted_line(t, ta, surf):
    """classify_painted_line：与对照解析程序逐分支一致。"""
    t = (t or "").upper()
    ta = (ta or "").upper()
    if t == "WIDE_YELLOW":
        return "RunwayMarkings" if ta == "ALL_POINTS" else "Edgelines"
    if t == "WIDE_WHITE":
        if ta == "ALL_POINTS" and surf == SURF_CENTERLINE:
            return "RunwayMarkings"
        if ta == "NONE" and surf == SURF_RUNWAY_LINE:
            return "RunwayMarkings"
        return "PaintedMarkings"
    if t == "EDGE_LINE_SOLID":
        return "Edgelines" if surf in (SURF_EDGELINE_SOLID, SURF_RUNWAY_LINE) else "Centerlines"
    if t in ("ENHANCED_CENTER", "DEFAULT"):
        return "Centerlines"
    if t == "EDGE_SERVICE_DASHED":
        return "PaintedMarkings" if ta == "ALL_POINTS" else "Centerlines"
    return "PaintedMarkings"


def classify_edge_lights(preset):
    """classify_edge_lights：Runway Alarm / Center* 单独成组，其余进 Edgelights。"""
    preset = preset or ""
    if preset == "Runway Alarm":
        return "Runway Alarm Lights"
    if preset.startswith("Center"):
        return "Centerlights"
    return "Edgelights"


# 机场子元素 → 分组（对照解析程序 assign_airport_groups 的集合顺序）
GROUP_OF_TAG = {
    "Runway": lambda a: "Runway",
    "LightSupport": lambda a: "Runway",
    "TaxiwayPoint": lambda a: "Taxipaths",
    "TaxiwayPath": lambda a: "Taxipaths",
    "TaxiwayParking": lambda a: "Parkings",
    "TaxiwaySign": lambda a: "TaxiSigns",
    "PaintedHatchedArea": lambda a: "PaintedMarkings",
    "PaintedPolygon": lambda a: "PaintedMarkings",
    "Apron": classify_apron,
    "PaintedLine": lambda a: classify_painted_line(a.get("type"), a.get("trueAngle"),
                                                  a.get("surface")),
    "EdgeLights": lambda a: classify_edge_lights(a.get("preset")),
}
GROUP_OF_ORDER = ["Runway", "LightSupport", "TaxiwayPoint", "TaxiwayPath", "TaxiwayParking",
                  "TaxiwaySign", "PaintedHatchedArea", "PaintedPolygon", "Apron",
                  "PaintedLine", "EdgeLights"]


def group_elements_xml(indent="\t"):
    """FSData 层 7 个景物顶层分组（始终输出，groupID 1..7）。"""
    return ['%s<Group displayName="%s" groupID="%d" groupGenerated="FALSE"/>'
            % (indent, GROUP_DISPLAY[i + 1], i + 1) for i in range(AIRPORT_LEVEL_GROUPS)]


def tag_name(s):
    """取节点串的第一个元素名（跳过前导空白）。"""
    p = s.find("<")
    if p < 0:
        return ""
    q, r = s.find(" ", p), s.find(">", p)
    end = min([x for x in (q, r) if x > 0] or [-1])
    return s[p + 1:end] if end > 0 else ""


def airport_sub_group_xml():
    """<Airport> 内 13 个子分组 <Group>（airport_sub_group_elements）。"""
    out = []
    for name in AIRPORT_SUB_GROUPS:
        parent = AIRPORT_SUB_PARENTS[name]
        pid = AIRPORT_GROUP_ID if parent is None else _SUB_GID[parent]
        out.append('\t\t<Group displayName="%s" parentGroupID="%d" groupID="%d" '
                   'groupGenerated="FALSE"/>' % (name, pid, _SUB_GID[name]))
    return out


def _inject_group(s, gid, idx):
    p = s.find(" ")
    if p < 0 or s.find("parentGroupID", 0, p + 2) >= 0:
        return s
    return "%s parentGroupID=\"%d\" groupIndex=\"%d\"%s" % (s[:p], gid, idx, s[p:])


def assign_scenery_groups(objs):
    """顶层 SceneryObject 按其 LibraryObject GUID 归入 7 个顶层组；未知 GUID 归 Other Models(4)。
    groupIndex 为组内按输出顺序的序号（与对照解析程序 assign_scenery_groups 一致）。"""
    counters = {}
    for i, s in enumerate(objs):
        if not s or node_tag(s) != "SceneryObject":
            continue
        p = s.find("<LibraryObject")
        guid = node_attrs(s[p:]).get("name") if p >= 0 else None
        gid = GUID_TO_GROUP.get(guid or "", DEFAULT_SCENERY_GROUP)
        counters[gid] = counters.get(gid, 0) + 1
        objs[i] = _inject_group(s, gid, counters[gid])
    return counters


def assign_airport_groups(lists, counters=None):
    """按对照解析程序 assign_airport_groups 的集合顺序，给机场子元素补 parentGroupID/groupIndex。
    分组内序号（groupIndex）按分组各自从 1 递增；TaxiwayPoint/TaxiwayPath 共享 Taxipaths 计数。"""
    counters = {} if counters is None else counters

    def put(lst, i, s, gname):
        counters[gname] = counters.get(gname, 0) + 1
        lst[i] = _inject_group(s, _SUB_GID[gname], counters[gname])

    for tag in GROUP_OF_ORDER:
        pick = GROUP_OF_TAG[tag]
        for lst in lists:
            for i, s in enumerate(lst):
                if not s or "parentGroupID" in s or node_tag(s) != tag:
                    continue
                put(lst, i, s, pick(node_attrs(s)))

    # ProjectedMesh 不进子组，直接挂在机场组（groupID=8）下单独计数
    for lst in lists:
        for i, s in enumerate(lst):
            if not s or "parentGroupID" in s or node_tag(s) != "ProjectedMesh":
                continue
            counters["__airport__"] = counters.get("__airport__", 0) + 1
            lst[i] = _inject_group(s, AIRPORT_GROUP_ID, counters["__airport__"])
    return counters


# ======================= NDB / 航路点 / 地标（section 0x17 / 0x22 / 0x31） =======================
WAYPOINT_TYPE = {1: "NAMED", 2: "UNNAMED", 3: "VOR", 4: "NDB", 5: "OFF_ROUTE",
                 6: "IAF", 7: "FAF", 8: "RNAV", 9: "VFR"}
NDB_TYPE = {0: "COMPASS_POINT", 1: "MH", 2: "H", 3: "HH"}
NDB_REC_ID = 0x0106


def _fmt_unit(v, unit):
    """_fmt_altitude_derived：按米保留 1-3 位小数并加 M 后缀（0 用 0.0F）。"""
    s = "%.3f" % float(v)
    if "." in s:
        s = s.rstrip("0")
        if s.endswith("."):
            s += "0"
    return s + unit


def _fmt_alt_derived(raw_mm):
    m = struct.unpack("<f", struct.pack("<f", raw_mm * struct.unpack("<f", struct.pack("<f", 0.001))[0]))[0]
    if m == 0:
        return "0.0F"
    return _fmt_unit(m, "M")


def ndb_elements(g, rep):
    """section 0x17：NDB（记录 id 0x0106）→ FSData 级 <Ndb>。

    基址 40 字节：+4 u32 rec_size、+6 u16 type、+8 u32 freq(KHz)、+12 i32 lon、
    +16 i32 lat、+20 i32 alt(mm)、+24 f32 range、+28 f32 magvar、+32 u32 ident、
    +36 u32（低 11 位 region，高 21 位所在机场）；随后为 (u16 st, u32 len) 子记录，
    st=0x19 为名称（cstring 从 +6 开始）。
    """
    out = []
    for blob, chunk in g.data_of(0x17):
        pos = 0
        while pos + 6 <= len(blob):
            tid, size = u16(blob, pos), u32(blob, pos + 2)
            if size < 6 or pos + size > len(blob):
                break
            raw = blob[pos:pos + size]
            if tid != NDB_REC_ID or len(raw) < 40:
                pos += size
                continue
            d = {"lat": _nav_lat(i32(raw, 16)), "lon": _nav_lon(i32(raw, 12)),
                 "alt": _nav_alt(i32(raw, 20)), "type": NDB_TYPE.get(raw[6], str(raw[6])),
                 "freq": u32(raw, 8) / 1000.0, "range": f32(raw, 24), "magvar": f32(raw, 28),
                 "region": icao(u32(raw, 36) & 2047, 0), "ident": icao(u32(raw, 32)), "name": ""}
            p = 40
            while p + 6 <= size:
                st, ss = u16(raw, p), u32(raw, p + 2)
                if ss < 6 or p + ss > size:
                    break
                if st == ILS_SUB_NAME:
                    d["name"] = cstr(raw[p:p + ss], 6)
                else:
                    rep["unknown"].append("Ndb 子记录 %#06x 长度 %d" % (st, ss))
                p += ss
            out.append('\t<Ndb lat="%s" lon="%s" alt="%s" type="%s" frequency="%.3f" '
                       'range="%s" magvar="%s" region="%s" ident="%s"%s/>'
                       % (_fmt_short(d["lat"]), _fmt_short(d["lon"]), _fmt_short(d["alt"]),
                          d["type"], d["freq"], _fmt_f32(d["range"]), _fmt_f32(d["magvar"]),
                          xesc(d["region"]), xesc(d["ident"]),
                          (' name="%s"' % xesc(d["name"])) if d["name"] else ""))
            rep["counts"]["ndb"] += 1
            pos += size
    return out


def waypoint_elements(g, rep):
    """section 0x22：航路点 → FSData 级 <Waypoint>。"""
    out = []
    for blob, chunk in g.data_of(0x22):
        pos = 0
        while pos + 6 <= len(blob):
            tid, size = u16(blob, pos), u32(blob, pos + 2)
            if size < 6 or pos + size > len(blob):
                break
            raw = blob[pos:pos + size]
            if len(raw) < 28:
                rep["unknown"].append("waypoint record id %#06x size %d" % (tid, size))
                pos += size
                continue
            is24 = (tid == 0x0108 and len(raw) >= 36)
            if is24:
                w_region = icao(u32(raw, 28) & 2047, 0)
                w_ident = icao(icao_2024(u32(raw, 20)), 0)
            else:
                w_region = icao(u32(raw, 24) & 2047, 0)
                w_ident = icao(u32(raw, 20))
            out.append('\t<Waypoint lon="%.14f" lat="%.14f" magvar="%s" waypointType="%s" '
                       'waypointRegion="%s" waypointIdent="%s"/>'
                       % (_nav_lon(i32(raw, 8)), _nav_lat(i32(raw, 12)), _fmt_f32(f32(raw, 16)),
                          WAYPOINT_TYPE.get(raw[6], str(raw[6])), w_region, w_ident))
            rep["counts"]["waypoint"] += 1
            pos += size
    return out


def landmark_elements(g, rep):
    """section 0x31：地标 → FSData 级 <LandmarkLocation>。"""
    out = []
    for blob, chunk in g.data_of(0x31):
        pos = 0
        while pos + 6 <= len(blob):
            tid, size = u16(blob, pos), u32(blob, pos + 2)
            if size < 6 or pos + size > len(blob):
                break
            raw = blob[pos:pos + size]
            if size >= 38:
                nlen, tlen, olen = raw[34], raw[35], raw[36]

                def _s(off, ln):
                    return raw[off:off + ln].split(b"\x00")[0].decode("utf-8", "replace")

                name = _s(38, nlen)
                typ = _s(38 + nlen, tlen)
                owner = _s(38 + nlen + tlen, olen)
                s = ('\t<LandmarkLocation instanceId="%s" lat="%.14f" lon="%.14f" alt="%s" name="%s" type="%s"'
                     % (guid(raw[6:22]), _nav_lat(i32(raw, 17)), _nav_lon(i32(raw, 22)),
                        _fmt_alt_derived(i32(raw, 30)), xesc(name), xesc(typ)))
                if owner:
                    s += ' owner="%s"' % xesc(owner)
                out.append(s + "/>")
                rep["counts"]["landmark"] += 1
            pos += size
    return out


# ======================= 飞行程序（section 0xFA Approach） =======================
LEG_TYPE = {1: "AF", 2: "CA", 3: "CD", 4: "CF", 5: "CI", 6: "CR", 7: "DF", 8: "FA", 9: "FC",
            10: "FD", 11: "FM", 12: "HA", 13: "HF", 14: "HM", 15: "IF", 16: "PI", 17: "RF",
            18: "TF", 19: "VA", 20: "VD", 21: "VI", 22: "VM", 23: "VR"}
APPROACH_TYPE = {0: "UNKNOWN", 1: "GPS", 2: "VOR", 3: "NDB", 4: "ILS", 5: "LOCALIZER", 6: "SDF",
                 7: "LDA", 8: "VORDME", 9: "NDBDME", 10: "RNAV", 11: "LOCALIZER_BACKCOURSE"}
TRANSITION_TYPE = {1: "FULL", 2: "DME", 3: "NDB", 4: "VOR", 5: "GPS", 6: "AIRWAY", 7: "ILS"}
ALTITUDE_DESCRIPTOR = {0: "", 1: "A", 2: "+", 3: "-", 4: "B", 5: "C", 6: "G", 7: "H", 8: "I",
                       9: "J", 10: "V"}
TURN_DIRECTION = {0: "NULL", 1: "L", 2: "R", 3: "E"}
FIX_TYPE = {0: "UNKNOWN", 1: "AIRPORT", 2: "VOR", 3: "NDB", 4: "TERMINAL_NDB", 5: "WAYPOINT",
            6: "TERMINAL_WAYPOINT", 8: "LOCALIZER", 9: "RUNWAY"}
_FT_PER_M = 3.2808399200439453


def _fmt_hash(v):
    s = _fmt_0_0hash(v)
    return s[:-2] if s.endswith(".0") else s


def _fmt_0_0hash(v):
    s = "%.3f" % float(v)
    if "." in s:
        s = s.rstrip("0")
        if s.endswith("."):
            s += "0"
    return s


def _fmt_alt_str(meters):
    feet = meters * _FT_PER_M
    return "%.1fF" % feet


def _plain_meters(v):
    s = "%.3f" % float(v)
    return s.rstrip("0").rstrip(".") if "." in s else s


def _dist_str(v, use_unit):
    """对照程序的 _dist_str：整海里（±0.01）→“NN”；use_unit 且整米 →“MM”；否则纯米。"""
    m = float(v)
    nm = m / 1852.0
    if round(nm) != 0 and abs(round(nm) - nm) < 0.01:
        return "%dN" % int(round(nm))
    if use_unit and abs(round(m) - m) < 0.01:
        return "%dM" % int(round(m))
    return _plain_meters(m)


def _leg_attrs(t, ad, turn, course_true, time_spec, fly_over, fix_type, fix_ident, fix_region,
               rtype, rident, rregion, theta, rho, course, dist, a1, a2, speed, vang, flags, ind):
    s = '\n%s<Leg type="%s"' % (ind, t)
    if t in _LEG_FIX:
        s += ' fixType="%s" fixRegion="%s" fixIdent="%s"' % (fix_type, xesc(fix_region), xesc(fix_ident))
    if t in _LEG_FLY_OVER:
        s += ' flyOver="%s"' % ("TRUE" if fly_over else "FALSE")
    if turn != "NULL":
        s += ' turnDirection="%s"' % turn
    if rtype not in (None, "", "UNKNOWN"):
        s += ' recommendedType="%s"' % rtype
        if rregion:
            s += ' recommendedRegion="%s"' % xesc(rregion)
        s += ' recommendedIdent="%s"' % xesc(rident)
    if t in _LEG_THETA and theta:
        s += ' theta="%s"' % _fmt_hash(theta)
    if t in _LEG_RHO and rho is not None and (float(rho) != 0.0 or t == "CF"):
        if float(rho) == 0.0:
            s += ' rho="0"'
        elif abs(round(float(rho)) - float(rho)) < 0.01:
            s += ' rho="%dM"' % int(round(float(rho)))
        else:
            s += ' rho="%s"' % _plain_meters(rho)
    if t in _LEG_COURSE:
        if course_true:
            s += ' trueCourse="%s"' % _fmt_f32(course)
        else:
            s += ' magneticCourse="%s"' % _fmt_f32(course)
    if t in _LEG_TIME_DIST:
        if time_spec:
            if dist:
                s += ' time="%s"' % _fmt_short(dist)
        elif dist:
            s += ' distance="%s"' % _dist_str(dist, False)
    if ad:
        s += ' altitudeDescriptor="%s"' % ad
    if ad:
        s += ' altitude1="%s"' % _fmt_alt_str(a1)
    if t in _LEG_ALTITUDE2 and a2:
        s += ' altitude2="%s"' % _fmt_alt_str(a2)
    if speed >= 0:
        s += ' speedLimit="%d"' % int(speed)
    if t in _LEG_VERTICAL_ANGLE and vang:
        s += ' verticalAngle="%s"' % _fmt_short(vang)
    for nm, bit in (("isIAF", 1), ("isIF", 2), ("isFAF", 4), ("isMAP", 8)):
        if flags & bit:
            s += ' %s="TRUE"' % nm
    return s + "/>"


def _leg_xml(leg, rep, ind="\t\t\t\t"):
    """FS9/FS20 腿记录（60 或 72 字节）。"""
    fl = u16(leg, 2)
    fu = u32(leg, 4)
    rec = u32(leg, 12)
    fix_region = icao(u32(leg, 8) & 2047, 0)
    return _leg_attrs(LEG_TYPE.get(leg[0], str(leg[0])), ALTITUDE_DESCRIPTOR.get(leg[1], ""),
                      TURN_DIRECTION.get(fl & 3, "NULL"), (fl >> 8) & 1, (fl >> 9) & 1, (fl >> 10) & 1,
                      FIX_TYPE.get(fu & 31, "UNKNOWN"), icao(fu), fix_region,
                      FIX_TYPE.get(rec & 31, "UNKNOWN"), icao(rec),
                      icao(u32(leg, 16) & 2047, 0) or fix_region,
                      f32(leg, 20), f32(leg, 24), f32(leg, 28), f32(leg, 32),
                      f32(leg, 36), f32(leg, 40), f32(leg, 44), f32(leg, 48),
                      u32(leg, 68) if len(leg) >= 72 else 0, ind)


def _leg2024_xml(leg, rep, ind="\t\t\t\t"):
    """MSFS2024 腿记录（96 字节）。"""
    if len(leg) < 96:
        return _leg_xml(leg, rep, ind)
    fl = u16(leg, 2)
    fu = u32(leg, 4)
    rec = u32(leg, 20)
    fix_region = icao(u32(leg, 12) & 2047, 0)
    return _leg_attrs(LEG_TYPE.get(leg[0], str(leg[0])), ALTITUDE_DESCRIPTOR.get(leg[1], ""),
                      TURN_DIRECTION.get(fl & 3, "NULL"), (fl >> 8) & 1, (fl >> 9) & 1, (fl >> 10) & 1,
                      FIX_TYPE.get(fu & 63, "UNKNOWN"), icao(icao_2024(fu), 0), fix_region,
                      FIX_TYPE.get(rec & 63, "UNKNOWN"), icao(icao_2024(rec), 0),
                      icao(u32(leg, 28) & 2047, 0) or fix_region,
                      f32(leg, 36), f32(leg, 40), f32(leg, 44), f32(leg, 48),
                      f32(leg, 52), f32(leg, 56), f32(leg, 60), f32(leg, 64),
                      u32(leg, 92), ind)


_LEG_ALTITUDE2 = frozenset({"AF", "IF", "FC", "VD", "CD", "VR", "RF", "FD", "DF", "VI", "CR", "TF", "CI", "CF"})
_LEG_COURSE = frozenset({"AF", "VD", "HF", "HM", "FM", "PI", "FC", "VM", "CD", "VA", "VR", "FD", "VI",
                         "CR", "TF", "CA", "CI", "HA", "RF", "FA", "CF"})
_LEG_FIX = frozenset({"AF", "IF", "FC", "VM", "HF", "HA", "RF", "FD", "DF", "FA", "HM", "FM", "PI", "TF", "CF"})
_LEG_FLY_OVER = frozenset({"AF", "FC", "HF", "VR", "HA", "RF", "FD", "DF", "CR", "TF", "CI", "CF"})
_LEG_RHO = frozenset({"AF", "IF", "FC", "HF", "HA", "FD", "DF", "FA", "HM", "FM", "PI", "TF", "CF"})
_LEG_THETA = frozenset({"AF", "IF", "FC", "HF", "VR", "HA", "RF", "FD", "DF", "FA", "HM", "FM", "CR",
                        "PI", "TF", "CF"})
_LEG_TIME_DIST = frozenset({"FC", "VD", "CD", "HF", "HA", "RF", "FD", "HM", "PI", "TF", "CF"})
_LEG_TURN_DIRECTION = frozenset({"AF", "VD", "HF", "HM", "FM", "PI", "FC", "VM", "CD", "VA", "VR", "FD",
                                 "VI", "CR", "TF", "CA", "CI", "HA", "RF", "DF", "FA", "CF"})
_LEG_VERTICAL_ANGLE = frozenset({"RF", "TF", "CF"})


def _legs_xml(container, name, rep, ind="\t\t\t"):
    """0xF4/0xF5/0xF6 容器（u16 计数 @+6，腿从 +8 起，FS20 步长 72）。"""
    n = u16(container, 6)
    stride = 72 if len(container) >= 8 + n * 72 else 60
    out = '\n%s<%s>' % (ind, name)
    for i in range(n):
        off = 8 + i * stride
        if off + stride > len(container):
            break
        out += _leg_xml(container[off:off + stride], rep, ind + "\t")
        rep["counts"]["leg"] += 1
    return out + '\n%s</%s>' % (ind, name)


_LEG_IDS_COMMON = (0xE5, 0xF8, 0x10E)
_LEG_IDS_RUNWAY_TRANS = (0x46, 0x116)
_LEG_IDS_ENROUTE_TRANS = (0x47, 0x4A)
_LEG_IDS_RUNWAY = (0xE4, 0xF7, 0x10D, 0x116)
_LEG_IDS_ENROUTE = (0xE6, 0xF9, 0x10A, 0x10B, 0x4A)


def _legs_container(body, name, attrs, ind, rep):
    """腿容器：u16 计数 @+6，腿从 +8 起（2024 步长 96，FS20 72，FS9 60）。"""
    n = u16(body, 6)
    if len(body) >= 8 + n * 96:
        stride, fn = 96, _leg2024_xml
    elif len(body) >= 8 + n * 72:
        stride, fn = 72, _leg_xml
    else:
        stride, fn = 60, _leg_xml
    out = '\n%s<%s%s>' % (ind, name, attrs)
    for i in range(n):
        off = 8 + i * stride
        if off + stride > len(body):
            break
        out += fn(body[off:off + stride], rep, ind + "\t")
        rep["counts"]["leg"] += 1
    return out + '\n%s</%s>' % (ind, name)


def _transition_container(body, st, rep):
    """跑道/航线过渡容器内部串。"""
    pos = 8
    attrs = ""
    if st in (0x46, 0x116):
        attrs = ' number="%s" designator="%s"' % (RUNWAY_NUMBER_ENUM.get(body[7], "00"),
                                                 DESIGNATOR_ENUM.get(body[8], "NONE"))
        pos = 12
    elif st == 0x4A:
        nm = body[8:16].split(b"\x00")[0].decode("utf-8", "replace")
        if nm:
            attrs = ' name="%s"' % xesc(nm)
        pos = 16
    s = ""
    while pos + 6 <= len(body):
        cs, cs_len = u16(body, pos), u32(body, pos + 2)
        if cs_len < 6 or pos + cs_len > len(body):
            break
        sub = body[pos:pos + cs_len]
        if cs in _LEG_IDS_RUNWAY:
            s += _legs_container(sub, "RunwayTransitionLegs", attrs, "\t\t\t\t", rep)
        elif cs in _LEG_IDS_ENROUTE:
            s += _legs_container(sub, "EnrouteTransitionLegs", "", "\t\t\t\t", rep)
        pos += cs_len
    return s


def _procedure_xml(pay, tag, rep):
    """0x42 Departure / 0x48 Arrival 载荷 → <Departure>/<Arrival>。"""
    nm = pay[6:14].split(b"\x00")[0].decode("utf-8", "replace")
    rw, en, cl = [], [], []
    pos = 14
    while pos + 6 <= len(pay):
        st, ss = u16(pay, pos), u32(pay, pos + 2)
        if ss < 6 or pos + ss > len(pay):
            break
        sub = pay[pos:pos + ss]
        if st in _LEG_IDS_RUNWAY_TRANS:
            rw.append((st, sub))
        elif st in _LEG_IDS_ENROUTE_TRANS:
            en.append((st, sub))
        elif st in _LEG_IDS_COMMON:
            cl.append((st, sub))
        pos += ss

    def block(name, items):
        inner = "".join(_transition_container(sub, st, rep) for st, sub in items)
        if not inner:
            return '\n\t\t\t<%s/>' % name
        return '\n\t\t\t<%s>%s\n\t\t\t</%s>' % (name, inner, name)

    def common():
        if not cl:
            return '\n\t\t\t<CommonRouteLegs/>'
        return "".join(_legs_container(sub, "CommonRouteLegs", "", "\t\t\t", rep)
                       for st, sub in cl)

    head = '\n\t\t<%s' % tag
    if nm:
        head += ' name="%s"' % xesc(nm)
    head += ">"
    if tag == "Arrival":
        parts = [block("EnrouteTransitions", en), common(), block("RunwayTransitions", rw)]
    else:
        parts = [block("RunwayTransitions", rw), common(), block("EnrouteTransitions", en)]
    return head + "".join(parts) + '\n\t\t</%s>' % tag


def _transition_xml(b, rep):
    tt = TRANSITION_TYPE.get(b[6], str(b[6]))
    fu = u32(b, 8)
    freg = u32(b, 12)
    name = b[20:28].split(b"\x00")[0].decode("utf-8", "replace")
    s = ('\n\t\t\t<Transition transitionType="%s" fixType="%s" fixRegion="%s" fixIdent="%s" '
         'altitude="%s" name="%s">'
         % (tt, FIX_TYPE.get(fu & 31, "UNKNOWN"), xesc(icao(freg & 2047, 0)), xesc(icao(fu)),
            _fmt_alt_str(f32(b, 16)), xesc(name)))
    pos = 28
    while pos + 6 <= len(b):
        st, ss = u16(b, pos), u32(b, pos + 2)
        if ss < 6 or pos + ss > len(b):
            break
        if st in (0xF6, 0x10C):
            s += _legs_xml(b[pos:pos + ss], "TransitionLegs", rep, "\t\t\t\t")
            rep["counts"]["transition_legs"] += 1
        pos += ss
    return s + '\n\t\t\t</Transition>'


def procedure_elements(g, rep):
    """section 0x03 内的 0xFA 记录由 decompile_bytes 调用；此处仅保留给独立入口。"""
    return []


def _transition2024_xml(b, rep):
    """0x110 Transition2024：tt@0、legCt@1、fix(6 位类型 + ident<<6)@2、region+机场@10、
    海拔 f32@14、8 字节名称@18，腿容器（0x10C）从 26 起。"""
    tt = TRANSITION_TYPE.get(b[0], str(b[0]))
    fu = u32(b, 2)
    freg = u32(b, 10)
    name = b[22:30].split(b"\x00")[0].decode("utf-8", "replace")
    s = ('\n\t\t\t<Transition transitionType="%s" fixType="%s" fixRegion="%s" fixIdent="%s" '
         'altitude="%s"%s>'
         % (tt, FIX_TYPE.get(fu & 63, "UNKNOWN"), xesc(icao(freg & 2047, 0)),
            xesc(icao(icao_2024(fu), 0)), _fmt_alt_str(f32(b, 18)),
            (' name="%s"' % xesc(name)) if name else ""))
    pos = 30
    while pos + 6 <= len(b):
        st, ss = u16(b, pos), u32(b, pos + 2)
        if ss < 6 or pos + ss > len(b):
            break
        if st in (0xF6, 0x10C):
            s += _legs_container(b[pos:pos + ss], "TransitionLegs", "", "\t\t\t\t", rep)
            rep["counts"]["transition_legs"] += 1
        pos += ss
    return s + '\n\t\t\t</Transition>'


def approach2024_xml(pay, rep):
    """0x111 Approach（2024）：44 字节基址（含 6 字节头），腿容器从载荷 +38 起。"""
    b = pay[2]
    suf = chr(pay[0]) if pay[0] and pay[0] != 0x30 else ""
    fu = u32(pay, 6)
    freg = u32(pay, 14)
    s = ('\n\t\t<Approach type="%s" runway="%s" designator="%s"%s gpsOverlay="%s" '
         'fixType="%s" fixRegion="%s" fixIdent="%s" altitude="%s" heading="%s" missedAltitude="%s"'
         % (APPROACH_TYPE.get(b & 15, "UNKNOWN"), RUNWAY_NUMBER_ENUM.get(pay[1], "00"),
            DESIGNATOR_ENUM.get((b >> 4) & 7, "NONE"), (' suffix="%s"' % suf) if suf else "",
            _tf(b >> 7), FIX_TYPE.get(fu & 63, "UNKNOWN"),
            xesc(icao(freg & 2047, 0)), xesc(icao(icao_2024(fu), 0)),
            _fmt_alt_str(f32(pay, 22)), _fmt_f32(f32(pay, 26)),
            _fmt_alt_str(f32(pay, 30))))
    fl = u32(pay, 34) if len(pay) > 38 else 0
    for nm, bit in (("lnav", 1), ("lnavvnav", 2), ("lpv", 4), ("lp", 8)):
        s += ' %s="%s"' % (nm, _tf(fl & bit))
    s += ">"
    body, trans = "", ""
    pos = 38
    while pos + 6 <= len(pay):
        st, ss = u16(pay, pos), u32(pay, pos + 2)
        if ss < 6 or pos + ss > len(pay):
            break
        chunk = pay[pos:pos + ss]
        if st in (0xF4, 0x10A):
            body += _legs_container(chunk, "ApproachLegs", "", "\t\t\t", rep)
            rep["counts"]["approach_legs"] += 1
        elif st in (0xF5, 0x10B):
            body += _legs_container(chunk, "MissedApproachLegs", "", "\t\t\t", rep)
            rep["counts"]["missed_legs"] += 1
        elif st in (0x49, 0x110):
            trans += _transition2024_xml(chunk[6:], rep)
            rep["counts"]["transition"] += 1
        pos += ss
    rep["counts"]["approach"] += 1
    return s + body + trans + '\n\t\t</Approach>'


def approach_xml(pay, rep):
    """0xFA Approach 载荷（不含 6 字节记录头）→ <Approach>。"""
    b = pay[2]
    suf = chr(pay[0]) if pay[0] and pay[0] != 0x30 else ""
    s = ('\n\t\t<Approach type="%s" runway="%s" designator="%s"%s gpsOverlay="%s" '
         'fixType="%s" fixRegion="%s" fixIdent="%s" altitude="%s" heading="%s" missedAltitude="%s"'
         % (APPROACH_TYPE.get(b & 15, "UNKNOWN"), RUNWAY_NUMBER_ENUM.get(pay[1], "00"),
            DESIGNATOR_ENUM.get((b >> 4) & 7, "NONE"), (' suffix="%s"' % suf) if suf else "",
            _tf(b >> 7), FIX_TYPE.get(u32(pay, 6) & 31, "UNKNOWN"),
            xesc(icao(u32(pay, 10) & 2047, 0)), xesc(icao(u32(pay, 6))),
            _fmt_alt_str(f32(pay, 14)), _fmt_short(f32(pay, 18)),
            _fmt_alt_str(f32(pay, 22))))
    fl = pay[26] if len(pay) > 26 else 0
    for nm, bit in (("lnav", 1), ("lnavvnav", 2), ("lpv", 4), ("lp", 8)):
        if fl & bit:
            s += ' %s="TRUE"' % nm
    s += ">"
    body, trans = "", ""
    pos = 30
    while pos + 6 <= len(pay):
        st, ss = u16(pay, pos), u32(pay, pos + 2)
        if ss < 6 or pos + ss > len(pay):
            break
        chunk = pay[pos:pos + ss]
        if st in (0xF4, 0x10A):
            body += _legs_xml(chunk, "ApproachLegs", rep)
            rep["counts"]["approach_legs"] += 1
        elif st in (0xF5, 0x10B):
            body += _legs_xml(chunk, "MissedApproachLegs", rep)
            rep["counts"]["missed_legs"] += 1
        elif st in (0x49, 0x110):
            trans += _transition_xml(chunk, rep)
            rep["counts"]["transition"] += 1
        pos += ss
    rep["counts"]["approach"] += 1
    return s + body + trans + '\n\t\t</Approach>'


# 内部枚举（由 ZSFZ 真值配对 + SDK bglcomp.xsd 推导）
PAINTED_LINE_TYPE = {0: "DEFAULT", 1: "HOLD_SHORT_FORWARD", 2: "HOLD_SHORT_BACKWARD", 3: "EDGE_LINE_DASHED",
                     4: "EDGE_LINE_SOLID", 5: "EDGE_SERVICE_DASHED", 6: "EDGE_SERVICE_SOLID",
                     7: "HOLD_SHORT_TAXIWAY", 8: "ILS_HOLD_SHORT", 9: "SERVICE_DASHED", 10: "DEFAULT_LIGHTED",
                     11: "HOLD_SHORT_FORWARD_LIGHTED", 12: "HOLD_SHORT_BACKWARD_LIGHTED",
                     13: "EDGE_LINE_DASHED_LIGHTED", 14: "EDGE_LINE_SOLID_LIGHTED",
                     15: "EDGE_SERVICE_DASHED_LIGHTED", 16: "EDGE_SERVICE_SOLID_LIGHTED",
                     17: "HOLD_SHORT_TAXIWAY_LIGHTED", 18: "ILS_HOLD_SHORT_LIGHTED", 19: "SERVICE_DASHED_LIGHTED",
                     20: "WIDE_YELLOW", 21: "WIDE_YELLOW_LIGHTED", 22: "NON_MOVEMENT", 23: "NON_MOVEMENT_LIGHTED",
                     24: "ENHANCED_CENTER", 25: "ENHANCED_CENTER_LIGHTED", 26: "WIDE_WHITE",
                     27: "WIDE_WHITE_LIGHTED", 28: "NON_MOVEMENT_BACK", 29: "NON_MOVEMENT_BACK_LIGHTED",
                     30: "EDGE_SOLID_ORTHO", 31: "EDGE_SOLID_ORTHO_LIGHTED", 32: "EDGE_SOLID_ORTHO_BACK",
                     33: "EDGE_SOLID_ORTHO_BACK_LIGHT", 34: "WIDE_RED", 35: "WIDE_RED_LIGHTED",
                     36: "SLIM_RED", 37: "SLIM_RED_LIGHTED", 38: "HOLD_SHORT_FORWARD_MARKED",
                     39: "HOLD_SHORT_BACKWARD_MARKED", 40: "HOLD_SHORT_FORWARD_MARKED_L",
                     41: "HOLD_SHORT_BACKWARD_MARKED_L"}
LINE_TYPE = PAINTED_LINE_TYPE
PAINTED_LINE_TRUE_ANGLE = {0: "NONE", 1: "BEGIN", 2: "END", 3: "BOTH_ENDS", 4: "ALL_POINTS"}
PAINTED_LINE_OUTLINE = ("NO_OUTLINE", "LINE", "FIT", "BORDER")
GUID_RUNWAY_MARKINGS = "{06C65325-BD2E-41F8-A062-710DC32E42E4}"
GUID_EDGELINE_SOLID = "{4EBBBBB6-08A3-4009-BD38-1BA096B75D45}"
GUID_CENTERLINE = "{A789C134-4487-43CB-8981-BAF5FCA23981}"
GUID_RUNWAY_LINE = "{DAEEABDD-69FC-4E8E-A693-BA2E332533D1}"


def _tf(v):
    return "TRUE" if v else "FALSE"


def classify_painted_line(ltype, tang, surf):
    """groups.classify_painted_line：画线 → 子分组名。"""
    if ltype == "WIDE_YELLOW":
        return "RunwayMarkings" if tang == "ALL_POINTS" else "Edgelines"
    if ltype == "WIDE_WHITE":
        if (tang == "ALL_POINTS" and surf == GUID_CENTERLINE) or (tang == "NONE" and surf == GUID_RUNWAY_LINE):
            return "RunwayMarkings"
        return "PaintedMarkings"
    if ltype == "EDGE_LINE_SOLID":
        return "Edgelines" if surf in (GUID_EDGELINE_SOLID, GUID_RUNWAY_LINE) else "Centerlines"
    if ltype in ("ENHANCED_CENTER", "DEFAULT"):
        return "Centerlines"
    if ltype == "EDGE_SERVICE_DASHED":
        return "PaintedMarkings" if tang == "ALL_POINTS" else "Centerlines"
    return "PaintedMarkings"


def classify_edge_lights(preset):
    if preset == "Runway Alarm":
        return "Runway Alarm Lights"
    if preset.startswith("Center"):
        return "Centerlights"
    return "Edgelights"


PATH_TYPE = {0: "UNKNOWN", 1: "TAXI", 2: "RUNWAY", 3: "PARKING", 4: "PATH", 5: "CLOSED", 6: "VEHICLE", 7: "ROAD"}
TAXI_POINT_ORIENT = {0: "FORWARD", 1: "REVERSE"}
POINT_TYPE = {0: "UNKNOWN", 1: "NORMAL", 2: "HOLD_SHORT", 4: "ILS_HOLD_SHORT",
              5: "HOLD_SHORT_NO_DRAW", 6: "ILS_HOLD_SHORT_NO_DRAW"}
PARK_NAME = {0: "NONE", 1: "PARKING", 2: "N_PARKING", 3: "NE_PARKING", 4: "E_PARKING", 5: "SE_PARKING",
             6: "S_PARKING", 7: "SW_PARKING", 8: "W_PARKING", 9: "NW_PARKING", 10: "GATE", 11: "DOCK",
             12: "GATE_A", 13: "GATE_B", 14: "GATE_C", 15: "GATE_D", 16: "GATE_E", 17: "GATE_F",
             18: "GATE_G", 19: "GATE_H", 20: "GATE_I", 21: "GATE_J", 22: "GATE_K", 23: "GATE_L",
             24: "GATE_M", 25: "GATE_N", 26: "GATE_O", 27: "GATE_P", 28: "GATE_Q", 29: "GATE_R",
             30: "GATE_S", 31: "GATE_T", 32: "GATE_U", 33: "GATE_V", 34: "GATE_W", 35: "GATE_X",
             36: "GATE_Y", 37: "GATE_Z"}
PARK_TYPE = {0: "NONE", 1: "RAMP_GA", 2: "RAMP_GA_SMALL", 3: "RAMP_GA_MEDIUM", 4: "RAMP_GA_LARGE", 5: "RAMP_CARGO", 6: "RAMP_MIL_CARGO", 7: "RAMP_MIL_COMBAT", 8: "GATE_SMALL", 9: "GATE_MEDIUM", 10: "GATE_HEAVY", 11: "DOCK_GA", 12: "FUEL", 13: "VEHICLE", 14: "RAMP_GA_EXTRA", 15: "GATE_EXTRA"}
TOWER_SIZE = {0: "NONE", 1: "SMALL", 2: "MEDIUM", 3: "LARGE"}
PARK_SUFFIX = {0: "NONE", 1: "GATE_A", 2: "GATE_B", 3: "GATE_C", 4: "GATE_D", 5: "GATE_E", 6: "GATE_F", 7: "GATE_G", 8: "GATE_H", 9: "GATE_I", 10: "GATE_J", 11: "GATE_K", 12: "GATE_L", 13: "GATE_M", 14: "GATE_N", 15: "GATE_O", 16: "GATE_P", 17: "GATE_Q", 18: "GATE_R", 19: "GATE_S", 20: "GATE_T", 21: "GATE_U", 22: "GATE_V", 23: "GATE_W", 24: "GATE_X", 25: "GATE_Y", 26: "GATE_Z"}
COM_TYPE = {1: "ATIS", 2: "MULTICOM", 3: "UNICOM", 4: "CTAF", 5: "GROUND", 6: "TOWER", 7: "CLEARANCE", 8: "APPROACH", 9: "DEPARTURE", 10: "CENTER", 11: "FSS", 12: "AWOS", 13: "ASOS", 14: "CLEARANCE_PRE_TAXI", 15: "REMOTE_CLEARANCE_DELIVERY"}
SUFFIX_OK = frozenset(PARK_SUFFIX.values())
# 机场头 +48 的 u32 燃油位图：每种油占 2 位（bit[2i]=flag、bit[2i+1]=flag2）
FUEL_TYPES = ("73", "87", "100", "130", "145", "MOGAS", "JET", "JETA", "JETA1",
              "JETAP", "JETB", "JET4", "JET5", "UNKNOWN")


def services_elements(mask):
    """机场头燃油位图 → <Services> 内的 14 条 <Fuel>（顺序固定）。"""
    out = ['\t\t<Services>']
    for i, ftype in enumerate(FUEL_TYPES):
        flag = (mask >> (2 * i)) & 1
        flag2 = (mask >> (2 * i + 1)) & 1
        avail = "YES" if (flag and flag2) else ("PRIOR_REQUEST" if flag2 else ("UNKNOWN" if flag else "NO"))
        out.append('\t\t\t<Fuel type="%s" availability="%s"/>' % (ftype, avail))
    out.append('\t\t</Services>')
    return out

SECTION_AIRPORT = 0x03
SECTION_OBJECTS = 0x25
SECTION_META = 0x35


class BglError(Exception):
    """输入不是本工具支持的 BGL。"""


def u16(b, o):
    return struct.unpack_from("<H", b, o)[0]


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def i32(b, o):
    return struct.unpack_from("<i", b, o)[0]


def i16(b, o):
    return struct.unpack_from("<h", b, o)[0]


def f32(b, o):
    return struct.unpack_from("<f", b, o)[0]


def lonlat(lo, la):
    return lo * LON_SCALE - 180.0, 90.0 - la * LAT_SCALE


def guid(raw):
    return "{%s}" % str(uuid.UUID(bytes_le=bytes(raw))).upper()


def cstr(pay, o):
    if o >= len(pay):
        return ""
    e = pay.find(b"\x00", o)
    if e < 0:
        e = len(pay)
    return pay[o:e].decode("utf-8", "replace")


def xesc(s):
    """XML 属性/文本转义：滑行道牌等文本里会出现 < > & 之类的字符。"""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def obj_pose(rec):
    """景物记录（id/size 包装）的经纬度、海拔、航向。

    lon@+4 lat@+8 alt@+12；航向是 +22 处的 i16 × 360/65536（+20 起的 u32 高 16 位相同，
    低位固定 0xFFFF，按 u32 读会带来最多 0.0055° 的偏差）。
    """
    lon, lat = lonlat(u32(rec, 4), u32(rec, 8))
    hdg = i16(rec, 22) * 360.0 / 65536.0
    alt = struct.unpack_from("<f", struct.pack("<f", i32(rec, 12) * _F32_0001))[0]
    return lon, lat, alt, hdg


def _pm_add(pay, rep, nodes):
    """投影网格记录（0xE8 载荷，或 0x56 重复表里的同构子记录载荷）→ <ProjectedMesh>。"""
    if len(pay) < 74 or u16(pay, 8) != 0x0B:
        return False
    isz = u16(pay, 10)
    if not (64 <= isz <= len(pay) - 8):
        return False
    rec = pay[8:8 + isz]
    lon, lat, alt, hdg = obj_pose(rec)
    rep["counts"]["projected_mesh"] += 1
    nodes.append(
        '\t\t<ProjectedMesh priority="%d" groundMerging="%s">\n'
        '\t\t\t<SceneryObject lat="%.14f" lon="%.14f" alt="%.14f" altitudeIsAgl="TRUE" '
        'snapToGround="FALSE" snapToNormal="FALSE" pitch="%.6f" bank="%.6f" '
        'heading="%.6f" imageComplexity="%s"/>\n\t\t</ProjectedMesh>'
        % (pay[0], _tf(pay[2] & 1), lat, lon, alt,
           i16(rec, 18) * 360.0 / 65536.0, i16(rec, 20) * 360.0 / 65536.0, hdg,
           COMPLEXITY.get(u16(rec, 24), "NORMAL")))
    return True


# 景物记录标志字节 @+16 的位 → 对照输出的空子元素（位序由差分定位）
OBJ_FLAG_KIDS = [("NoAutogenSuppression", 1), ("NoCrash", 2), ("NoFog", 3), ("NoShadow", 4)]
OBJ_FLAG_KIDS2 = [("NoZWrite", 5), ("NoZTest", 6), ("HideOnTIN", 7)]
COMPLEXITY = {0: "VERY_SPARSE", 1: "SPARSE", 2: "NORMAL", 3: "DENSE", 4: "VERY_DENSE",
              5: "EXTREMELY_DENSE"}


def scenery_base(rec, rep):
    """景物记录的公共部分：SceneryObject 属性串 + No* 空子元素串。

    标志字节 @+16：位0 altitudeIsAgl、位1-4 NoAutogenSuppression/NoCrash/NoFog/NoShadow、
    位5-7 NoZWrite/NoZTest/HideOnTIN；+26 的 bit0 = NoSnow。
    pitch@+18 / bank@+20 / heading@+22 都是 i16 × 360/65536；+24 是 imageComplexity 枚举；
    +28 起 16 字节 instanceId（全 0 时省略）；snapToGround = 原始海拔字段是否为 0。
    """
    flags = rec[16] if len(rec) > 16 else 0
    kids = [nm for nm, bit in OBJ_FLAG_KIDS if (flags >> bit) & 1]
    if len(rec) > 26 and u16(rec, 26) & 1:
        kids.append("NoSnow")
    kids += [nm for nm, bit in OBJ_FLAG_KIDS2 if (flags >> bit) & 1]
    kids = "".join("\n\t\t<%s/>" % nm for nm in kids)
    iid = rec[28:44] if len(rec) >= 44 else b""
    attrs = "" if not any(iid) else ' instanceId="%s"' % guid(iid)
    lon, lat, alt, hdg = obj_pose(rec)
    return ('%s lat="%.14f" lon="%.14f" alt="%.14f" pitch="%.6f" bank="%.6f" heading="%.6f" '
            'imageComplexity="%s" altitudeIsAgl="%s" snapToGround="%s" snapToNormal="FALSE">%s'
            % (attrs, lat, lon, alt,
               i16(rec, 18) * 360.0 / 65536.0, i16(rec, 20) * 360.0 / 65536.0, hdg,
               COMPLEXITY.get(u16(rec, 24), "NORMAL"), "TRUE" if flags & 1 else "FALSE",
               "TRUE" if i32(rec, 12) == 0 else "FALSE", kids))


def sim_object(rec):
    """id 0x19 的容器对象记录：f32 scale@+44 | u32 名称长度@+48 | 名称@+52。返回 (title, scale)。"""
    title, scale = "", 1.0
    if len(rec) >= 56:
        nlen = u32(rec, 48)
        if 0 < nlen <= min(64, len(rec) - 52):
            txt = rec[52:52 + nlen].decode("utf-8", "replace").strip("\x00")
            if txt.isprintable():
                title = txt
        sc = f32(rec, 44)
        scale = sc if 0.001 < sc < 100 else 1.0
    return title, scale


class Bgl:
    """只解析容器骨架（文件头 + section 表 + 子块目录）。"""

    def __init__(self, data: bytes):
        self.b = data
        if len(data) < 0x38 or data[:4] != b"\x01\x02\x92\x19":
            raise BglError("不是 MSFS/FSX BGL（文件头 magic 不符）")
        self.nsec = u32(self.b, 0x14)
        if self.nsec > 1000:
            raise BglError("section 数量异常，可能不是机场 BGL")
        self.sections = []
        for i in range(self.nsec):
            if 0x38 + i * 20 + 20 > len(self.b):
                break
            st, fl, cn, sb, ss = struct.unpack_from("<5I", self.b, 0x38 + i * 20)
            stride = ((fl & 0x10000) | 0x40000) >> 14
            chunks = []
            for c in range(cn):
                o = sb + c * stride + stride - 16
                if o + 16 > len(self.b):
                    break
                g = struct.unpack_from("<4I", self.b, o)
                chunks.append({"id": g[0], "nrec": g[1], "off": g[2], "size": g[3]})
            self.sections.append({"type": st, "flags": fl, "chunks": chunks})

    def data_of(self, stype):
        for s in self.sections:
            if s["type"] == stype:
                for c in s["chunks"]:
                    yield self.b[c["off"]:c["off"] + c["size"]], c

    def section_types(self):
        return [s["type"] for s in self.sections]


def chain(blob, start=0x5C):
    """机场记录内部的 (u16 id, u32 size) 子记录流。"""
    pos, out = start, []
    while pos + 6 <= len(blob):
        rid, sz = u16(blob, pos), u32(blob, pos + 2)
        if sz < 6 or pos + sz > len(blob):
            break
        out.append((rid, blob[pos + 6:pos + sz]))
        pos += sz
    return out


def chain_end(blob, start):
    """从 start 起按 (u16 id, u32 size) 走链，返回走到的结束偏移。"""
    pos = start
    while pos + 6 <= len(blob):
        sz = u32(blob, pos + 2)
        if sz < 6 or pos + sz > len(blob):
            break
        pos += sz
    return pos


def chain_start(blob, header_id=0x0113):
    """两种机场记录格式的子记录链起点：0x0113 → +0x5C，FSX 系 0x0056 → +0x44。

    先用头部 id 猜，再用实际走链长度（能否走到记录尾）校验，必要时在候选起点里挑最优。
    """
    prefer = 0x5C if header_id == 0x0113 else 0x44
    best, best_end = prefer, chain_end(blob, prefer)
    if best_end < len(blob) * 0.9:
        for s in (0x5C, 0x44, 0x64, 0x68):
            if s + 6 > len(blob):
                continue
            e = chain_end(blob, s)
            if e > best_end:
                best, best_end = s, e
    return best


def _vertices_form_parallelogram(latlon, tol=0.05):
    """Apron._vertices_form_parallelogram：四顶点能否排序成平行四边形（容差 5%）。"""
    if len(latlon) != 4:
        return False

    def eq(a, b):
        la = math.hypot(a[0], a[1])
        lb = math.hypot(b[0], b[1])
        if la < 1e-12 or lb < 1e-12:
            return False
        return (abs(la - lb) / max(la, lb) < tol
                and abs(a[0] * b[1] - a[1] * b[0]) / (la * lb) < tol)

    for v in itertools.permutations(latlon):
        e0 = (v[1][0] - v[0][0], (v[1][1] - v[0][1]) * math.cos(math.radians(v[0][0])))
        e2 = (v[3][0] - v[2][0], (v[3][1] - v[2][1]) * math.cos(math.radians(v[2][0])))
        e1 = (v[2][0] - v[1][0], (v[2][1] - v[1][1]) * math.cos(math.radians(v[1][0])))
        e3 = (v[0][0] - v[3][0], (v[0][1] - v[3][1]) * math.cos(math.radians(v[3][0])))
        if eq(e0, e2) and eq(e1, e3):
            return True
    return False


def apron_is_rect(verts, pay):
    """Apron._is_rectangle：4 顶点 + 无附着物 + （有朝向或呈平行四边形）。"""
    if len(verts) != 4 or u32(pay, 38) != 0:
        return False
    if f32(pay, 26) != 0.0:
        return True
    return _vertices_form_parallelogram([(v[2], v[1]) for v in verts])


def vertex_runs(pay, ref=None, minrun=2):
    """找出最长的“8 字节步长、按定标经纬度存储”的顶点串。"""
    rlon, rlat = ref if ref else (0.0, 0.0)
    pairs = []
    for o in range(0, len(pay) - 7):
        lo, la = u32(pay, o), u32(pay, o + 4)
        lon, lat = lonlat(lo, la)
        if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
            continue
        if abs(lon - rlon) > 0.5 or abs(lat - rlat) > 0.5:
            continue
        pairs.append((o, lon, lat))
    runs, cur = [], []
    for p in pairs:
        if cur and p[0] == cur[-1][0] + 8:
            cur.append(p)
        else:
            if len(cur) >= minrun:
                runs.append(cur)
            cur = [p]
    if len(cur) >= minrun:
        runs.append(cur)
    runs.sort(key=len, reverse=True)
    return runs


def decompile_bytes(data: bytes, source_name: str = "input.bgl", ident: str = "",
                    profile: str = "2024") -> tuple[str, dict]:
    """把 BGL 字节反编译成 XML。返回 (xml 文本, 统计信息 dict)。

    profile="2020" 时按 MSFS 2020 的 bglcomp.xsd 输出：EdgeLights 用 preset 且包在
    <ApronEdgeLights> 里、PaintedLine 不带 width、Windsock 不带颜色属性。
    """
    is2020 = (str(profile) == "2020")
    global _IS2020
    _IS2020 = is2020
    g = Bgl(data)
    rep = {"records": collections.Counter(), "unknown": [], "counts": collections.Counter(),
           "decoded_notes": [], "start_unmatched": 0}
    out = []
    A = out.append
    ap = {"lat": 0.0, "lon": 0.0, "alt": 0.0, "name": "", "ident": ident, "counts": []}
    airport_nodes = []
    runway_meta = []
    pending_starts = []
    arch_open = [-1]          # 最近一条 <AirportArchetype> 在 airport_nodes 里的下标
    arch_over = {}            # 下标 → 该 archetype 的 <ParamOverride> 行
    edge_light_nodes = []
    jetway_nodes = []
    airport_object_nodes = []
    apron_nodes = []
    apron_groups = []
    painted_nodes = []
    painted_groups = []
    edge_groups = []
    presets = []
    del_airport = [None]
    rw_children = []          # 需要挂进跑道元素里的子记录（0xE9 等）
    state = {"npts": 1 << 30, "n_edge": 0, "tower": 0}

    # ---------------- 机场记录 ----------------
    for blob, chunk in g.data_of(SECTION_AIRPORT):
        hid = u16(blob, 0) if len(blob) >= 6 else 0
        if len(blob) < 0x50:
            rep["unknown"].append("airport section: unexpected header")
            continue
        if hid not in (0x0113, 0x0056):
            # 头部字段只用来挑子记录链起点，chain_start 会自行纠正，故这里只记录不跳过
            rep["unknown"].append("airport header %#06x（按 0x0056 处理）" % hid)
        ap["counts"] = list(blob[6:12])
        ap["lon"], ap["lat"] = lonlat(u32(blob, 12), u32(blob, 16))
        ap["alt"] = _nav_alt(i32(blob, 20))
        ap["fs24"] = (hid == 0x0113)      # PaintedLine 的 is_fs24：机场记录类型 == 0x0113
        # Airport.__init__ 的标志位：+53 流量系数、+54 bit0 starAirport / bit1 isOnTIN、+59 bit0 applyFlatten
        ap["traffic"] = blob[53] / 255.0 if len(blob) > 59 else 1.0
        ap["star"] = bool(blob[54] & 1) if len(blob) > 59 else True
        ap["tin"] = bool(blob[54] & 2) if len(blob) > 59 else False
        ap["flatten"] = bool(blob[59] & 1) if len(blob) > 59 else True
        ap["fuel_mask"] = u32(blob, 48) if len(blob) >= 52 else 0
        # 机场记录的 ident 是压缩 ICAO：0x0113（2024）在 @+76、移位 6；
        # 0x0056（2020）在 @+40、移位 5。历史实现一律按「@+76 / 移位 5」读，
        # 2024 记录会多解出一位前导无效字符（如 ZSFZ → 6ZKXY），故按记录版本取。
        # magvar 在 @+36（f32）。0x2C FsAirportSummary 里的 ICAO 只是 4 字机场代码兜底用。
        _idn = airport_ident(blob, hid)
        if _idn:
            ap["ident"] = _idn
            ap["ident_from_airport"] = True
        if len(blob) >= 40:
            ap["magvar"] = f32(blob, 36)
        cstart = chain_start(blob, hid)
        rep["airport_format"] = "%#06x chain@%#04x" % (hid, cstart)
        recs = chain(blob, cstart)
        rep["record_ids"] = [hex(r[0]) for r in recs]
        for rid, pay in recs:
            rep["records"][hex(rid)] += 1
            if rid == 0x19:                                    # 机场名
                ap["name"] = cstr(pay, 0)
            elif rid == 0xCE:                                  # 跑道
                nw1, nw2 = u16(pay, 2), u16(pay, 4)
                num, sec = nw1 & 0xFF, nw2 & 0xFF
                pri_desig, sec_desig = (nw1 >> 8) & 0x0F, (nw2 >> 8) & 0x0F
                lon, lat = lonlat(u32(pay, 14), u32(pay, 18))
                alt = i32(pay, 22) / 1000.0
                length, width, hdg = f32(pay, 26), f32(pay, 30), f32(pay, 34)
                surf = guid(pay[70:86])
                col = tuple(pay[86:90])
                rep["counts"]["runway"] += 1
                kids = runway_children(pay, rep)
                runway_meta.append({
                    "node": len(airport_nodes), "ils": [],
                    "pri_num": RUNWAY_NUMBER_ENUM.get(num, "00"),
                    "pri_desig": DESIGNATOR_ENUM.get(pri_desig, "NONE"),
                    "sec_num": RUNWAY_NUMBER_ENUM.get(sec, "00"),
                    "sec_desig": DESIGNATOR_ENUM.get(sec_desig, "NONE")})
                # 跑道颜色：对照解析程序只在非全零时输出（Color(raw,92,96,order='BGRA')）
                rw_color = ("" if not any(col) else
                            '\n\t\t\t<Coloration red="%d" green="%d" blue="%d" alpha="%d" override="TRUE"/>'
                            % (col[2], col[1], col[0], col[3]))
                airport_nodes.append(
                    '\t\t<Runway lat="%s" lon="%s" alt="%.14f" heading="%.14f" length="%.14f" width="%.14f" '
                    'surface="%s" number="%02d" designator="%s" transparent="%s" primaryLanding="%s" '
                    'primaryTakeoff="%s" primaryPattern="%s" secondaryLanding="%s" secondaryTakeoff="%s" '
                    'secondaryPattern="%s" patternAltitude="%.14f"%s groundMerging="%s" '
                    'excludeVegetationAround="%s" primaryMarkingBias="%.14f" secondaryMarkingBias="%.14f">%s'
                    '%s'
                    '\n\t\t\t<Markings %s/>'
                    '\n\t\t\t<Lights center="%s" edge="%s"%s/>'
                    '%s%s%s%s%s%s%s%s'
                    '\n\t\t</Runway>'
                    % (FMT.format(lat), FMT.format(lon), _nav_alt(i32(pay, 22)), hdg, length, width, surf, num,
                       DESIGNATOR_ENUM.get(pri_desig, "NONE"),
                       _tf((pay[0] >> 7) & 1),
                       # 跑道标志位（对照解析程序：raw[51] → 载荷 +45）
                       # bit0 主起降 / bit1 主着陆（取反）、bit2 主起落航线（0 左 1 右）、
                       # bit3 次起降 / bit4 次着陆（取反）、bit5 次起落航线
                       _tf(not ((pay[45] >> 1) & 1)), _tf(not (pay[45] & 1)),
                       "RIGHT" if (pay[45] >> 2) & 1 else "LEFT",
                       _tf(not ((pay[45] >> 4) & 1)), _tf(not ((pay[45] >> 3) & 1)),
                       "RIGHT" if (pay[45] >> 5) & 1 else "LEFT",
                       f32(pay, 38),
                       (' falloff="%.6f"' % f32(pay, 66)) if f32(pay, 66) > 0 else "",
                       _tf(not ((pay[45] >> 6) & 1)), _tf(not ((pay[45] >> 7) & 1)),
                       0.0, 0.0, "".join(kids["def"]), rw_color,
                       markings_attrs(u16(pay, 0x2A), pay[0x2C] if len(pay) > 0x2C else 0),
                       LIGHT_LEVEL.get((pay[0x2C] >> 2) & 3, "MEDIUM"),
                       LIGHT_LEVEL.get(pay[0x2C] & 3, "MEDIUM"),
                       ' centerRed="TRUE"' if (pay[0x2C] >> 4) & 1 else "",
                       "".join(kids["offset"]), "".join(kids["blast"]), "".join(kids["overrun"]),
                       "".join(kids["approach"]), "".join(kids["vasi"]),
                       ILS_SLOT, START_SLOT, "".join(kids["material"]) + "".join(rw_children)))
                rw_children.clear()
            elif rid == 0x111 and len(pay) >= 38:              # 飞行程序（进近，2024 布局）
                airport_nodes.append(approach2024_xml(pay, rep))
                rw_children.clear()
            elif rid == 0xFA and len(pay) >= 30:               # 飞行程序（进近）
                airport_nodes.append(approach_xml(pay, rep))
                rw_children.clear()
            elif rid in (0x42, 0x48):                          # 飞行程序（SID / STAR）
                rep["counts"]["departure" if rid == 0x42 else "arrival"] += 1
                if len(pay) >= 14:
                    airport_nodes.append(_procedure_xml(pay, "Departure" if rid == 0x42 else "Arrival", rep))
                rw_children.clear()
            elif rid == 0xFC and len(pay) >= 2:                # 航司代码表（2024）：u16 条数 + N × (4 字符代码 + 4 字节)
                cnt = u16(pay, 0)
                codes = []
                for k in range(cnt):
                    slot = pay[2 + k * 8:2 + k * 8 + 4]
                    if len(slot) < 4:
                        break
                    cd = slot.rstrip(b"\x00").decode("latin-1").strip()
                    if cd:
                        codes.append(cd)
                rep["counts"]["airline_code_table"] += 1
                rep.setdefault("airline_codes", []).extend(codes)
                rep["decoded_notes"].append("航司代码表(0xFC): %s（记录里没有逐机位的引用字段，故不写入 XML）"
                                            % ", ".join(codes))
            elif rid == 0xE9 and len(pay) >= 10:               # 地面合并明暗阈值（Airport 的两个属性）
                # Airport._dispatch_child：ctype 233 → bright = f32(body, 8)、dark = f32(body, 12)
                # （body 含 6 字节记录头，故对应我方载荷 +2 / +6）
                rep["counts"]["ground_merging"] += 1
                ap["gm_bright"] = f32(pay, 2)
                ap["gm_dark"] = f32(pay, 6)
            elif rid == 0x66 and len(pay) >= 10:               # 塔台 Tower
                # +0 u16 子记录长度 · +2 标志字节 · +3 高度覆盖；之后是内嵌景物对象，或默认塔台的经纬高（三个 double）
                flags = pay[2]
                isz = u16(pay, 6)
                rep["counts"]["tower"] += 1
                if u16(pay, 4) == 0x0B and 64 <= isz <= len(pay) - 4:
                    rec = pay[4:4 + isz]
                    airport_nodes.append(
                        '\t\t<Tower>\n'
                        '\t\t\t<SceneryObject %s\n'
                        '\t\t\t\t<LibraryObject name="%s" scale="%.6f"/>\n'
                        '\t\t\t</SceneryObject>\n\t\t</Tower>'
                        % (scenery_base(rec, rep),
                           guid(rec[44:60]),
                           (f32(rec, 60) if 0.001 < f32(rec, 60) < 100 else 1.0)))
                elif len(pay) >= 28:                           # 默认塔台：直接给经纬高
                    lat, lon, alt = struct.unpack_from("<ddd", pay, 4)
                    # 高度按对照语义量化到 float32 再以 double 输出
                    alt = struct.unpack("<f", struct.pack("<f", alt))[0]
                    # flags bit0 = 默认塔台、bit1..3 = 尺寸覆盖；alt 用 double 原样输出（对照行为）
                    airport_nodes.append(
                        '\t\t<Tower lat="%s" lon="%s" alt="%s" overrideSize="%s" '
                        'overrideLevel="%d"/>'
                        % (FMT.format(lat), FMT.format(lon), FMT.format(alt),
                           TOWER_SIZE.get((flags >> 1) & 3, "NONE"), pay[3]))
                else:
                    rep["unknown"].append("tower record without embedded object")
            elif rid == 0x26 and len(pay) >= 30:               # 直升机坪 Helipad
                tcode = pay[1] & 0x0F
                lon, lat = lonlat(u32(pay, 6), u32(pay, 10))
                rep["counts"]["helipad"] += 1
                airport_nodes.append(
                    '\t\t<Helipad lat="%s" lon="%s" alt="%.3f" surface="%s" heading="%.6f" length="%.3f" '
                    'width="%.3f" type="%s" closed="%s" transparent="%s" red="%d" green="%d" blue="%d"/>'
                    % (FMT.format(lat), FMT.format(lon), i32(pay, 14) / 1000.0,
                       SURFACE_TYPE.get(pay[0], "CONCRETE"), f32(pay, 26),
                       u32(pay, 18) / 100.0, u32(pay, 22) / 100.0, HELIPAD_TYPE.get(tcode, "SQUARE"),
                       "TRUE" if (pay[1] >> 5) & 1 else "FALSE",
                       "TRUE" if (pay[1] >> 4) & 1 else "FALSE",
                       pay[4], pay[3], pay[2]))
            elif rid == 0x5D and len(pay) >= 18:                # 机场 archetype（一个 GUID，2024 专有元素）
                rep["counts"]["archetype"] += 1
                if not is2020:
                    airport_nodes.append('\t\t<AirportArchetype archetypeGUID="%s"/>' % guid(pay[2:18]))
                    arch_open[0] = len(airport_nodes) - 1
            elif rid == 0x5C and len(pay) >= 14:                # archetype 参数覆盖（u16 + 参数名哈希 + f32 值）
                c = rep["counts"]
                c["arch_param"] += 1
                if is2020:
                    continue
                if arch_open[0] < 0:
                    c["arch_param_orphan"] += 1
                    continue
                v = f32(pay, 10)
                if not (v == 0.0 or (1e-6 <= abs(v) <= 1e6)):   # 写入方未清内存 → 不是有效参数值
                    v = 0.0
                    c["arch_param_junk"] += 1
                arch_over.setdefault(arch_open[0], []).append(
                    '\n\t\t\t<ParamOverride name="0x%016X" value="%s"/>'
                    % (struct.unpack_from("<Q", pay, 2)[0], _fmt_f32(v)))
            elif rid in (0x11, 0x6A):                          # 跑道入口（end 需与跑道主/次端比对后判定）
                rep["counts"]["start"] += 1
                if len(pay) < 18:
                    rep["unknown"].append("runway start payload %d bytes" % len(pay))
                    continue
                pending_starts.append((len(airport_nodes), pay))
                airport_nodes.append("")
            elif rid == 0x11A:                                 # COM
                code = u16(pay, 0)
                freq = u32(pay, 2) / 1e6
                nm = cstr(pay, len(pay) - 16).strip() if len(pay) > 16 else ""
                nm = "".join(ch for ch in nm if ch.isprintable())
                rep["counts"]["com"] += 1
                ctype = COM_TYPE.get(code)
                if ctype is None:
                    ctype = "TOWER"
                    rep["unknown"].append("com type code %#x" % code)
                airport_nodes.append('\t\t<Com type="%s" frequency="%.6f" name="%s"/>'
                                     % (ctype, freq, xesc(nm)))
            elif rid == 0x12 and len(pay) >= 10:               # COM（另一种写法：u16 类型 + u32 频率(Hz) + 名称）
                code = u16(pay, 0)
                freq = u32(pay, 2) / 1e6
                nm = pay[6:].split(b"\x00")[0].decode("utf-8", "replace")
                nm = "".join(ch for ch in nm if ch.isprintable())
                rep["counts"]["com"] += 1
                ctype = COM_TYPE.get(code)
                if ctype is None:
                    ctype = "TOWER"
                    rep["unknown"].append("com type code %#x" % code)
                airport_nodes.append('\t\t<Com type="%s" frequency="%.6f" name="%s"/>'
                                     % (ctype, freq, xesc(nm)))
            elif rid == 0x1A:                                  # 滑行道点
                n = u16(pay, 0)
                state["npts"] = n
                for i in range(n):
                    fl_, lo, la = struct.unpack_from("<III", pay, 2 + i * 12)
                    lon, lat = lonlat(lo, la)
                    t = POINT_TYPE.get(fl_ & 0xFF)
                    if t is None:
                        t = "HOLD_SHORT" if (fl_ & 0x100) else "NORMAL"
                        rep["unknown"].append("taxiway point flag %#x" % fl_)
                    rep["counts"]["taxiway_point"] += 1
                    airport_nodes.append(
                        '\t\t<TaxiwayPoint index="%d" type="%s" orientation="%s" lat="%s" lon="%s"/>'
                        % (i, t, TAXI_POINT_ORIENT.get((fl_ >> 8) & 0xFF, "FORWARD"),
                           FMT.format(lat), FMT.format(lon)))
            elif rid == 0xD4:                                  # 滑行道路径
                n = u16(pay, 0)

                def add_path(e, end_off=46):
                    start, tcode, name_i = u16(e, 0), e[4], e[5]
                    ptype = PATH_TYPE.get(tcode & 0x07, "TAXI")
                    pdesig = DESIGNATOR_ENUM.get((u16(e, 2) >> 12) & 0x0F, "NONE")
                    rep["counts"]["taxiway_path"] += 1
                    airport_nodes.append(
                        '\t\t<TaxiwayPath type="%s" start="%d" end="%d" width="%.6f"%s '
                        'surface="%s" centerLine="%s"%s%s%s drawSurface="%s" '
                        'drawDetail="%s" groundMerging="%s" excludeVegetationAround="%s" '
                        'excludeVegetationInside="%s" weightLimit="%d"/>'
                        % (ptype, start, u16(e, end_off), f32(e, 8),
                           (' name="%d"' % name_i) if ptype != "RUNWAY" else
                           (' number="%s"' % RUNWAY_NUMBER_ENUM.get(e[5], "00")),
                           guid(e[24:40]), _tf(e[6] & 1),
                           ' centerLineLighted="TRUE"' if (e[6] >> 1) & 1 else "",
                           ' enhanced="TRUE"' if (e[4] >> 4) & 1 else "",
                           (' designator="%s"' % pdesig) if ptype == "RUNWAY" else "",
                           _tf((e[4] >> 5) & 1), _tf((e[4] >> 6) & 1),
                           _tf((e[45] >> 0) & 1), _tf(not ((e[45] >> 1) & 1)),
                           _tf(not ((e[45] >> 2) & 1)), u32(e, 12)))

                # 定长数组（长度能被条数整除）是最可靠的形态：直接按步长切
                stride = (len(pay) - 2) // n if n and (len(pay) - 2) % n == 0 else 0
                if 24 <= stride <= 80:
                    rep["path_stride"] = stride
                    for i in range(n):
                        add_path(pay[2 + i * stride:2 + (i + 1) * stride], stride - 2)
                else:
                    pos, made = 2, 0
                    while made < n and pos + 48 <= len(pay):
                        e = pay[pos:pos + 48]
                        start, tcode, name_i = u16(e, 0), e[4], e[5]
                        width = f32(e, 8)
                        end = u16(e, 46)
                        plausible = ((tcode & 0x07) in (1, 2, 3) and 1.0 < width < 200.0
                                     and end < state["npts"])
                        if not plausible:
                            # 数组里夹带的独立子记录（ZGBH 里是 0xD5，44 字节：标志 + GUID + 参数）
                            nid, nsz = u16(pay, pos), u32(pay, pos + 2)
                            if 6 <= nsz <= len(pay) - pos:
                                if nid == 0xD5:
                                    rep["counts"]["path_material"] += 1
                                    _g = guid(pay[pos + 7:pos + 23]) if nsz >= 44 else ""
                                    _v = [f32(pay, pos + 28 + 4 * k) for k in range(4)] if nsz >= 44 else []
                                    rep["decoded_notes"].append(
                                        "滑行道材质记录(0xD5): guid=%s 参数=%d/%s（无对照实现，未写入 XML）"
                                        % (_g, pay[pos + 23] if nsz >= 44 else 0,
                                           "/".join("%.4f" % v for v in _v)))
                                else:
                                    rep["unknown"].append("taxiway path array: nested sub-record id %#06x size %d at +%d"
                                                          % (nid, nsz, pos))
                                pos += nsz
                                continue
                            skipped = None
                            for d in range(1, 64):
                                if pos + d + 48 > len(pay):
                                    break
                                e2 = pay[pos + d:pos + d + 48]
                                if ((e2[4] & 0x0F) in (1, 2, 3) and 1.0 < f32(e2, 8) < 200.0
                                        and u16(e2, 46) < state["npts"]):
                                    skipped = d
                                    break
                            if skipped is None:
                                rep["unknown"].append("taxiway path array desync at +%d" % pos)
                                break
                            rep["unknown"].append("taxiway path array: skipped %d bytes at +%d (%s)"
                                                  % (skipped, pos, pay[pos:pos + skipped].hex(" ")))
                            pos += skipped
                            continue
                        add_path(e)
                        pos += 48
                        made += 1
            elif rid == 0xE7:                                  # 机位
                n = u16(pay, 0)
                # 机位条目是变长的：56 字节固定主体 + 每条航司码 4 字节（数量在位域 24..31）
                pos = 2
                for i in range(n):
                    e = pay[pos:pos + 56]
                    if len(e) < 56:
                        break
                    packed = u32(e, 0)
                    # 位域（_extract：msb 含端点）：名称 0..5、推回 6..7、类型 8..11、机位号 12..23、航司码数 24..31
                    pname, ptype, number = packed & 0x3F, (packed >> 8) & 0xF, (packed >> 12) & 0xFFF
                    code_ct = (packed >> 24) & 0xFF
                    radius, hdg = f32(e, 4), f32(e, 8)
                    lon, lat = lonlat(u32(e, 28), u32(e, 32))
                    num_mark = "TRUE" if e[36] == 1 else "FALSE"
                    # 对照解析程序：suffix = PARKING_NAME[raw[37]]；值 1..11 会落到 PARKING/N_PARKING 等
                    # 非 GATE 名称上，而 Schema 的 stParkingSuffix 只收 NONE + GATE_A..Z，
                    # 这类值没有合法写法，统一降级为 NONE 并计数
                    suffix = PARK_NAME.get(e[37], "NONE")
                    if suffix not in SUFFIX_OK:
                        suffix = "NONE"
                        rep["park_suffix_bad"] = rep.get("park_suffix_bad", 0) + 1
                    mesh = "TRUE" if (e[38] & 1) else "FALSE"
                    codes = []
                    for j in range(code_ct):
                        c4 = pay[pos + 56 + j * 4:pos + 60 + j * 4]
                        codes.append(c4.split(b"\x00")[0].decode("ascii", "replace"))
                    codes = [c for c in codes if c]
                    rep["counts"]["parking"] += 1
                    airport_nodes.append(
                        '\t\t<TaxiwayParking index="%d" type="%s" lat="%s" lon="%s" heading="%.6f" '
                        'radius="%.6f" name="%s" number="%d" suffix="%s" numberMarking="%s" '
                        'has3DMesh="%s" numberBiasX="%.6f" numberBiasZ="%.6f" numberHeading="%.6f"%s/>'
                        % (i, PARK_TYPE.get(ptype, "NONE"), FMT.format(lat), FMT.format(lon), hdg, radius,
                           PARK_NAME.get(pname, "NONE"), number, suffix, num_mark, mesh,
                           f32(e, 44), f32(e, 48), f32(e, 52),
                           (' airlineCodes="%s"' % xesc(",".join(codes))) if codes else ""))
                    pos += 56 + 4 * code_ct
            elif rid == 0xD0:                                  # 停机坪
                runs = vertex_runs(pay, (ap["lon"], ap["lat"]))
                if runs:
                    verts = runs[0]
                    # 载荷布局（Apron）：+0 标志位（bit0 绘制面、bit1 细节、bit2 localUV、
                    #   bit3 stretchUV、bit7 flipUV）| +1 不透明度 | +2 RGBA | +6 表面 GUID | +34 优先级
                    flags = pay[0]
                    surf = guid(pay[6:22])
                    prior = i32(pay, 34)
                    local_uv = (flags >> 2) & 1
                    if not local_uv:
                        grp = "GroundBase"
                    elif prior == 1000000012 or surf == "{06C65325-BD2E-41F8-A062-710DC32E42E4}":
                        grp = "RunwayMarkings"
                    else:
                        grp = "PaintedMarkings"
                    color = ("" if not any(pay[2:6]) else
                             '\n\t\t\t\t<Coloration red="%d" green="%d" blue="%d" alpha="%d" override="TRUE"/>'
                             % (pay[4], pay[3], pay[2], pay[5]))
                    body = "".join('\n\t\t\t\t<Vertex lat="%s" lon="%s"/>' % (FMT.format(v[2]), FMT.format(v[1]))
                                   for v in verts)
                    rep["counts"]["apron"] += 1
                    rep["counts"]["vertex"] += len(verts)
                    apron_nodes.append(
                        '\t\t\t<Apron surface="%s" drawSurface="%s" drawDetail="%s" localUV="%s" '
                        'stretchUV="%s" flipUV="%s" groundMerging="%s" excludeVegetationAround="%s" '
                        'excludeVegetationInside="%s" opacity="%d" tiling="%.6f" heading="%.6f" '
                        'falloff="%.6f" isRectangle="%s"%s%s priority="%d">%s%s\n\t\t\t</Apron>'
                        % (surf, _tf(flags & 1), _tf((flags >> 1) & 1), _tf(local_uv),
                           _tf((flags >> 3) & 1), _tf((flags >> 7) & 1),
                           _tf(not ((flags >> 4) & 1)), _tf(not ((flags >> 5) & 1)),
                           _tf(not ((flags >> 6) & 1)), pay[1],
                           f32(pay, 22), f32(pay, 26), f32(pay, 30),
                           _tf(apron_is_rect(verts, pay)),
                           (' offsetU="%d"' % pay[38]) if pay[38] else "",
                           (' offsetV="%d"' % pay[39]) if pay[39] else "",
                           prior, color, body))
                    if color:
                        rep["counts"]["coloration"] += 1
                    apron_groups.append(grp)
                else:
                    rep["unknown"].append("apron record without vertex run")
            elif rid == 0xFF and len(pay) >= 114:              # 2024 文字标记（地面文字）
                rep["counts"]["text_marking"] += 1
                if is2020:
                    continue
                cols = ""
                for _tag, _off in (("ColorText", 36), ("ColorBackground", 40), ("ColorOutline", 44)):
                    _b, _g, _r, _a = pay[_off], pay[_off + 1], pay[_off + 2], pay[_off + 3]
                    if _b or _g or _r or _a:
                        cols += ('\n\t\t\t\t<%s red="%d" green="%d" blue="%d" alpha="%d"/>'
                                 % (_tag, _r, _g, _b, _a))
                        rep["counts"]["coloration"] += 1
                # 标签长度取 u16@48（对照解析程序按该长度截断，而不是按 NUL）
                _tlen = u16(pay, 48)
                _lbl = pay[50:50 + min(_tlen, 64)].decode("utf-8", "replace").split("\x00")[0] if _tlen else ""
                # 载荷布局（去掉 6 字节记录头）：lon i32@0、lat i32@4、alt f32@8、heading f32@12、
                # paddingY f32@16、scale f32@20、letterSpacing f32@24、lineSpacing f32@28、
                # paddingX f32@32、三色 BGRA @36/40/44、u16 文本长度@48、64 字节标签@50
                _head = ('\t\t\t<TextMarking lat="%s" lon="%s" heading="%.6f" scale="%.6f" '
                         'letterSpacing="%.6f" lineSpacing="%.6f" paddingX="%.6f" paddingY="%.6f"%s'
                         % (FMT.format(_cvx_lat(struct.unpack_from("<i", pay, 4)[0])),
                            FMT.format(_cvx_lon(struct.unpack_from("<i", pay, 0)[0])),
                            f32(pay, 12), f32(pay, 20), f32(pay, 24), f32(pay, 28),
                            f32(pay, 32), f32(pay, 16),
                            (' label="%s"' % xesc(_lbl)) if _lbl else ""))
                if cols:
                    airport_nodes.append(_head + ">" + cols + "\n\t\t\t</TextMarking>")
                else:
                    airport_nodes.append(_head + "/>")
            elif rid == 0xFB and len(pay) >= 54:               # 2024 灯柱（字段映射为推测：<MastLight>）
                rep["counts"]["mast_light"] += 1
                if is2020:
                    continue
                airport_nodes.append(
                    '\t\t<MastLight lat="%s" lon="%s" heading="%.6f"/>'
                    % (FMT.format(_nav_lat(u32(pay, 10))), FMT.format(_nav_lon(u32(pay, 6))),
                       f32(pay, 26)))
            elif rid == 0x0102:                                # 2024 WASM 模块声明（NUL 填充的路径串）
                rep["counts"]["wasm_module"] += 1
                if is2020:
                    continue
                _wpath = pay.split(b"\x00")[0].decode("utf-8", "replace")
                if _wpath:
                    airport_nodes.append('\t\t<WasmModule name="%s"/>'
                                         % _wpath.replace("&", "&amp;").replace('"', "&quot;")
                                         .replace("<", "&lt;").replace(">", "&gt;"))
            elif rid == 0xCF:                                  # 画线
                runs = vertex_runs(pay, (ap["lon"], ap["lat"]))
                if runs:
                    verts = runs[0]
                    body = "".join('\n\t\t\t\t<Vertex lat="%s" lon="%s"/>' % (FMT.format(v[2]), FMT.format(v[1]))
                                   for v in verts)
                    rep["counts"]["painted_line"] += 1
                    rep["counts"]["vertex"] += len(verts)
                    ltype = PAINTED_LINE_TYPE.get(pay[0])
                    if ltype is None:
                        ltype = "DEFAULT"
                        rep["unknown"].append("painted line type code %#x" % pay[0])
                    tang = PAINTED_LINE_TRUE_ANGLE.get(pay[1], "NONE")
                    psurf = guid(pay[6:22])
                    # 对照解析程序：机场记录为 0x0113 时（is_fs24）多输出 outlineType，取自载荷 +4 的 u16。
                    # outlineType 不在 2020 版 bglcomp.xsd 里，故 2020 profile 下不输出（保证可直接编译）
                    oltype = ((' outlineType="%s"' % PAINTED_LINE_OUTLINE[min(u16(pay, 4), 3)])
                              if (ap.get("fs24") and not is2020) else "")
                    painted_nodes.append('\t\t\t<PaintedLine type="%s"%s trueAngle="%s"%s%s>%s'
                                         '\n\t\t\t</PaintedLine>'
                                         % (ltype, oltype, tang,
                                            ("" if psurf == "{00000000-0000-0000-0000-000000000000}" else
                                             ' surface="%s"' % psurf),
                                            "" if is2020 else "", body))
                    painted_groups.append(classify_painted_line(ltype, tang, psurf))
                else:
                    rep["unknown"].append("painted line without vertex run")
            elif rid == 0xD8 and len(pay) >= 22:               # 网格填充画线
                # +0 u32 类型码 | +4 u16 顶点数 | +6 f32 朝向 | +10 f32 间距 | +14 起 (u32 经度, u32 纬度)
                cnt = u16(pay, 4)
                if 14 + cnt * 8 <= len(pay):
                    hdg = f32(pay, 6)
                    htype = LINE_TYPE.get(pay[0])
                    if htype is None:
                        htype = "DEFAULT"
                        rep["unknown"].append("hatched area type code %#x" % pay[0])
                    body = "".join('\n\t\t\t\t<Vertex lat="%s" lon="%s"/>'
                                   % (FMT.format(lonlat(u32(pay, 14 + i * 8), u32(pay, 18 + i * 8))[1]),
                                      FMT.format(lonlat(u32(pay, 14 + i * 8), u32(pay, 18 + i * 8))[0]))
                                   for i in range(cnt))
                    rep["counts"]["painted_hatched"] += 1
                    rep["counts"]["vertex"] += cnt
                    painted_nodes.append('\t\t\t<PaintedHatchedArea heading="%.14f" '
                                         'spacing="%.14f" type="%s">%s\n\t\t\t</PaintedHatchedArea>'
                                         % (hdg, f32(pay, 10), htype, body))
                else:
                    rep["unknown"].append("hatched area vertex count %d out of range" % cnt)
            elif rid == 0x58:                                  # 灯光预设（后面的 0x59 是它的灯）
                nlen = pay[1] if len(pay) > 1 else 0
                name = ""
                if 0 < nlen <= min(64, len(pay) - 26):
                    name = pay[26:26 + nlen].decode("utf-8", "replace").strip("\x00")
                presets.append({"name": name, "mesh": guid(pay[6:22]) if len(pay) >= 22 else "",
                                "phase": f32(pay, 22) if len(pay) >= 26 else 0.0, "lights": []})
            elif rid == 0x59 and len(pay) >= 60:               # 预设里的一盏灯
                flags = u16(pay, 0)
                dur, per = f32(pay, 50), f32(pay, 54)
                light = ('\t\t\t<Light relativePosition="%.6f %.6f %.6f" direction="%.6f %.6f %.6f" '
                         'direction2="%.6f %.6f %.6f" type="%s" fade="%s" radius="%.6f" color="%d %d %d" '
                         'intensity="%.6f" duration="%.6f" period="%.6f" phase="%.6f"/>'
                         % (f32(pay, 2), f32(pay, 6), f32(pay, 10), f32(pay, 14), f32(pay, 18), f32(pay, 22),
                            f32(pay, 26), f32(pay, 30), f32(pay, 34),
                            "OMNIDIRECTIONAL" if (flags & 0x100) else "UNIDIRECTIONAL",
                            "FADE_IN_OUT" if (dur > 0 or per > 0) else "NO_FADE",
                            f32(pay, 38), pay[44], pay[43], pay[42],
                            f32(pay, 46), dur, per, f32(pay, 58)))
                if presets:
                    presets[-1]["lights"].append(light)
                else:
                    rep["unknown"].append("light record without preceding preset")
            elif rid == 0x33 and len(pay) >= 6:                # 机场删除标志 DeleteAirport
                # +0 u16 标志位 0-11 · +2/+3/+4 跑道/入口/频率计数 · +5 u8 标志位 0-7
                bits = u16(pay, 0) | (pay[5] << 32)
                attrs = []
                for nm, bit in DEL_FLAGS:
                    attrs.append('%s="%s"' % (nm, "TRUE" if (bits >> bit) & 1 else "FALSE"))
                del_airport[0] = '\t\t<DeleteAirport %s/>' % " ".join(attrs)
            elif rid == 0x31:                                  # 停机坪边灯
                spacing = f32(pay, 14)
                runs = vertex_runs(pay, (ap["lon"], ap["lat"]))
                verts = runs[0] if runs else []
                name = cstr(pay, 18 + len(verts) * 8).strip() if verts else ""
                body = "".join('\n\t\t\t<Vertex lat="%s" lon="%s"/>' % (FMT.format(v[2]), FMT.format(v[1]))
                               for v in verts)
                rep["counts"]["edge_lights"] += 1
                rep["counts"]["vertex"] += len(verts)
                # 2020/2024 两版 bglcomp.xsd 的 ctEdgeLights 都只认 preset（无 type/name）
                edge_light_nodes.append('\t\t\t<EdgeLights preset="%s" spacing="%.6f">%s\n\t\t\t</EdgeLights>'
                                        % (xesc(name), spacing, body))
                edge_groups.append(classify_edge_lights(name))
            # ---- 登机桥 (0xDE)：u16 机位号 | 定标经纬度 @+16/+20 | 航向 u16@+34 × 360/65536
            #      | 双精度经纬度 @+56/+64 | scale @+84 | 名称长度 @+88 | 容器名 @+94
            elif rid == 0xDE:
                pnum = u16(pay, 0)
                lon, lat = lonlat(u32(pay, 16), u32(pay, 20))
                hdg = u16(pay, 34) * 360.0 / 65536.0
                title = ""
                scale = 1.0
                inner = None
                # 载荷 +12 起内嵌 1~2 条 SceneryObject 记录：`u16 id + u16 size` 连续排列
                # （0x1D=SimObject 容器、0x0B=LibraryObject），各自带自己的定标数据
                vj_children = []
                vj_pos = 12
                while vj_pos + 4 <= len(pay):
                    csz = u16(pay, vj_pos + 2)
                    if csz < 4 or vj_pos + csz > len(pay):
                        break
                    vj_children.append(pay[vj_pos:vj_pos + csz])
                    vj_pos += csz
                if vj_children:
                    inner = vj_children[0]
                if not vj_children and len(pay) >= 76 and u16(pay, 12) == 0x19:
                    isz = u32(pay, 8)
                    if 64 <= isz <= len(pay) - 12:
                        inner = pay[12:12 + isz]
                if inner is not None:
                    title, scale = sim_object(inner)
                    cnlen = u32(inner, 48)
                    if 0 < cnlen <= 64:
                        for c_off in (54, 52):
                            if c_off + cnlen <= len(inner):
                                t = inner[c_off:c_off + cnlen].decode("utf-8", "replace")
                                if t.isprintable() and "\x00" not in t:
                                    title = t
                                    break
                elif len(pay) >= 94:
                    nlen = u32(pay, 88)
                    if 0 < nlen <= min(64, len(pay) - 94):
                        title = pay[94:94 + nlen].decode("utf-8", "replace").strip("\x00")
                    sc = f32(pay, 84)
                    scale = sc if 0.001 < sc < 100 else 1.0
                rep["counts"]["jetway"] += 1
                vj_body = []
                for child in vj_children:
                    cbase = scenery_base(child, rep)
                    if u16(child, 0) == 0x0B and len(child) >= 64:
                        csc = f32(child, 60)
                        vj_body.append(
                            '<SceneryObject%s\n\t\t\t\t<LibraryObject name="%s" scale="%.6f"/>\n\t\t\t</SceneryObject>'
                            % (cbase, guid(child[44:60]), csc if 0.001 < csc < 100 else 1.0))
                        rep["counts"]["library_object"] += 1
                    else:
                        ct, cs = sim_object(child)
                        cn = u32(child, 48)
                        if 0 < cn <= 64:
                            for c_off in (54, 52):
                                if c_off + cn <= len(child):
                                    t = child[c_off:c_off + cn].decode("utf-8", "replace")
                                    if t.isprintable() and "\x00" not in t:
                                        ct = t
                                        break
                        vj_body.append(
                            '<SceneryObject%s\n\t\t\t\t<SimObject containerTitle="%s" scale="%.6f"/>\n\t\t\t</SceneryObject>'
                            % (cbase, xesc(ct), cs))
                if not vj_body:
                    attrs = ('lat="%.14f" lon="%.14f" alt="0.00000000000000" pitch="0.000000" '
                             'bank="0.000000" heading="%.6f" imageComplexity="VERY_SPARSE" '
                             'altitudeIsAgl="TRUE" snapToGround="TRUE" snapToNormal="FALSE">'
                             % (lat, lon, hdg))
                    vj_body.append('<SceneryObject %s\n\t\t\t\t<SimObject containerTitle="%s" scale="%.6f"/>\n\t\t\t</SceneryObject>'
                                   % (attrs, xesc(title), scale))
                jetway_nodes.append(
                    '\t\t<Jetway gateName="%s" parkingNumber="%d" suffix="%s">\n\t\t\t%s\n\t\t</Jetway>'
                    % (PARK_NAME.get(u16(pay, 2), "NONE"), pnum,
                       PARK_NAME.get(u16(pay, 4), "NONE"),
                       "\n\t\t\t".join(vj_body)))
            # ---- 投影网格 (0xE8)：8 字节包装 + 内嵌景物记录（id 0x0B，64B 或 92B）
            #      2024 反编译把它输出成 <ProjectedMesh>，里面是一个只有变换的 SceneryObject
            elif rid in (0xE8, 0x56) and len(pay) >= 74 and u16(pay, 8) == 0x0B:
                _pm_add(pay, rep, airport_object_nodes)
            # ---- 投影网格重复表 (0x56)：90 字节头 + N 条「id 0xE8 / 80 字节」子记录，
            #      子记录载荷与同名 0xE8 记录逐字节相同，对照解析程序对两者都输出 <ProjectedMesh>
            elif rid == 0x56:
                p56 = 90
                n56 = 0
                while p56 + 6 <= len(pay):
                    sid, ssz = u16(pay, p56), u32(pay, p56 + 2)
                    if ssz < 6 or p56 + ssz > len(pay):
                        break
                    if sid == 0xE8 and ssz >= 80 and u16(pay, p56 + 6 + 8) == 0x0B:
                        if _pm_add(pay[p56 + 6:p56 + ssz], rep, airport_object_nodes):
                            n56 += 1
                    elif sid == 0xD4 and ssz == 8:
                        break                       # 表结束标记
                    else:
                        rep["unknown"].append("0x56 子记录 id %#06x size %d" % (sid, ssz))
                    p56 += ssz
                if n56:
                    rep["counts"]["projected_mesh_dup"] += n56
            # ---- 0x118：GUID + N 个「顶点（lat f64, lon f64, f32）」，2024 新记录。
            #      2024 schema 的唯一顶点类型 ctVertexLL 只有 lat/lon/spline，装不下每顶点的第 4 列，
            #      对照解析程序也不处理它 ⇒ 只做结构报告，不产出 XML
            elif rid == 0x118 and len(pay) >= 18:
                pn = u16(pay, 0)
                if pn and len(pay) >= 18 + pn * 20:
                    las = [struct.unpack_from("<d", pay, 18 + i * 20)[0] for i in range(pn)]
                    los = [struct.unpack_from("<d", pay, 26 + i * 20)[0] for i in range(pn)]
                    vals = [f32(pay, 34 + i * 20) for i in range(pn)]
                    rep["counts"]["poly118"] += 1
                    rep["decoded_notes"].append(
                        "0x118 顶点多边形：GUID %s、%d 顶点、lat %.7f..%.7f、lon %.7f..%.7f、"
                        "每顶点第 4 列 f32 %.3f..%.3f"
                        % (guid(pay[2:18]), pn, min(las), max(las), min(los), max(los),
                           min(vals), max(vals)))
                else:
                    rep["unknown"].append("0x118 顶点数 %d 与长度 %d 不符" % (pn, len(pay)))
            # ---- 矢量放置 / 围栏 (0x5A)：u16 顶点数 | 16B profile GUID @+2 | f32 间距@+18 | f32 航向@+22
            #      | f32 缩放@+26 | f32 缩放增量@+30 | u8 旋转@+34 | 顶点为「纬度 double, 经度 double」@+42 起
            elif rid == 0x5A and len(pay) >= 42:
                cnt = u16(pay, 0)
                prof = guid(pay[2:18])
                spacing, vheading, vscale, vdelta = f32(pay, 18), f32(pay, 22), f32(pay, 26), f32(pay, 30)
                # 旋转是 u32（@+34），只有两个已知值有名，其余原样输出数字（对照行为）
                _rot = u32(pay, 34)
                rot = "Follow edge" if _rot in (112, 624) else str(_rot)
                verts = []
                for k in range(cnt):
                    off = 42 + k * 16
                    if off + 16 > len(pay):
                        break
                    la, lo = struct.unpack_from("<dd", pay, off)
                    verts.append((la, lo))
                if len(verts) >= 2:
                    body = "".join('\n\t\t\t<Vertex lat="%s" lon="%s"/>' % (FMT.format(p[0]), FMT.format(p[1]))
                                   for p in verts)
                    rep["counts"]["vector_placement"] += 1
                    rep["counts"]["vertex"] += len(verts)
                    airport_nodes.append(
                        '\t\t<VectorPlacement profile="%s" spacing="%.6f" heading="%.6f" scale="%.6f" '
                        'scaleDelta="%.6f" rotation="%s" avoidDiscontinuity="TRUE" '
                        'adjustScalingAlongPath="TRUE">%s\n\t\t</VectorPlacement>'
                        % (prof, spacing, vheading, vscale, vdelta, xesc(rot), body))
                else:
                    rep["unknown"].append("vector placement with <2 vertices")
            # ---- 跑道标志牌 (0xD9)：u16 + 经度 + 纬度 + 航向 + 尺寸码 + 对齐码 + 文本
            elif rid == 0xD9:
                lon, lat = lonlat(u32(pay, 2), u32(pay, 6))
                hdg = f32(pay, 10)
                size_code = pay[14] if len(pay) > 14 else 0
                just = pay[15] if len(pay) > 15 else 0
                label = cstr(pay, 16).rstrip("\x00") if len(pay) > 16 else ""
                rep["counts"]["taxiway_sign"] += 1
                airport_nodes.append(
                    '\t\t<TaxiwaySign lat="%s" lon="%s" heading="%.6f" label="%s" justification="%s" size="SIZE%d"/>'
                    % (FMT.format(lat), FMT.format(lon), hdg, xesc(label),
                       "RIGHT" if just else "LEFT", size_code))
            # ---- 灯光支座 (0x57)：u16 + 纬度/经度/标高/标高2 四个 double + 航向/宽/长 三个 float
            elif rid == 0x57 and len(pay) >= 46:
                la, lo, al, al2 = struct.unpack_from("<dddd", pay, 2)
                hdg, wid, ln = struct.unpack_from("<fff", pay, 34)
                rep["counts"]["light_support"] += 1
                ls_flags = u16(pay, 0)
                airport_nodes.append(
                    '\t\t<LightSupport latitude="%.14f" longitude="%.14f" altitude="%.14f" altitude2="%.14f" '
                    'heading="%.6f" width="%.6f" length="%.6f" excludeLights="%s" excludeLightObjects="%s"/>'
                    % (la, lo, al, al2, hdg, wid, ln,
                       _tf(ls_flags & 1), _tf(ls_flags & 2)))
            # ---- VDGS 目视停靠引导 (0x104)：整条记录 84 B（含 6 B 头，载荷 78 B）；
            #      载荷 +0 u16 机位号、+2 u16 gateName、+4 u16 suffix，
            #      +6 u32 常量 0x400000、+8 u32 内嵌记录长度 64，载荷 +12 起是一个完整的
            #      SimObject SceneryObject 记录（id 0x1D，u16 size 0x40），外层补零到 84
            elif rid == 0x104 and len(pay) >= 76:
                vd_num = u16(pay, 0)
                vd_gate = PARK_NAME.get(u16(pay, 2), "NONE")
                vd_suf = PARK_NAME.get(u16(pay, 4), "NONE")
                if vd_suf not in SUFFIX_OK:
                    vd_suf = "NONE"
                inner = pay[12:76]
                vd_base = scenery_base(inner, rep)
                vd_title, vd_scale = sim_object(inner)
                # 内嵌记录的名称有时在长度字段后多 2 字节对齐填充（VDGS_01 落在 +54），
                # 按「长度字段 + 两个候选偏移」取第一个完全可打印且不含 NUL 的串
                vd_nlen = u32(inner, 48)
                if 0 < vd_nlen <= 64:
                    for vd_off in (54, 52):
                        if vd_off + vd_nlen <= len(inner):
                            t = inner[vd_off:vd_off + vd_nlen].decode("utf-8", "replace")
                            if t.isprintable() and "\x00" not in t:
                                vd_title = t
                                break
                rep["counts"]["vdgs"] += 1
                airport_nodes.append(
                    '\t\t<VDGS gateName="%s" parkingNumber="%d" suffix="%s">\n'
                    '\t\t\t<SceneryObject%s\n'
                    '\t\t\t\t<SimObject containerTitle="%s" scale="%.6f"/>\n'
                    '\t\t\t</SceneryObject>\n\t\t</VDGS>'
                    % (vd_gate, vd_num, vd_suf, vd_base, xesc(vd_title), vd_scale))
            # ---- 滑行道名称表 (0x1D)：u32 计数 + 6 字节头 + (计数-1)×8 字节 ASCII 名（索引 0 为空名）
            elif rid == 0x1D:
                cnt = u32(pay, 0)
                names = []
                for i in range(1, cnt):
                    off = 10 + (i - 1) * 8
                    if off + 8 > len(pay):
                        break
                    names.append(pay[off:off + 8].split(b"\x00")[0].decode("utf-8", "replace"))
                for i, nm in enumerate(names, start=1):
                    airport_nodes.append('\t\t<TaxiName index="%d" name="%s"/>' % (i, xesc(nm)))
                rep["taxinames"] = names
            else:
                key = "%#06x/%d" % (rid, len(pay))
                rep.setdefault("unknown_samples", {})[key] = pay[:32].hex(" ")
                rep["unknown"].append("airport sub-record id %#06x size %d" % (rid, len(pay)))

    # ---------------- 机场元数据（section 0x35） ----------------
    meta = []
    for blob, chunk in g.data_of(SECTION_META):
        vals = []
        for k in range(6):
            off = u32(blob, 0x12 + k * 4) + 4
            if 0 < off < len(blob):
                vals.append(cstr(blob, off).strip("\x00"))
        meta = vals
    if meta:
        meta = [m if (len(m) >= 2 and m.isprintable()) else "" for m in meta]
        ap["short"], ap["country"], ap["state"], ap["city"] = (meta + ["", "", "", ""])[:4]
        if len(meta) > 4 and meta[4]:
            ap["name"] = ap["name"] or meta[4]
        rep["meta"] = meta

    # ---------------- 景物对象（section 0x25） ----------------
    objects = []
    obj_gcount = {}
    for blob, chunk in g.data_of(SECTION_OBJECTS):
        pos = 0
        while pos + 4 <= len(blob):
            rid, sz = u16(blob, pos), u16(blob, pos + 2)
            if sz < 4 or pos + sz > len(blob):
                break
            rec = blob[pos:pos + sz]
            if sz >= 64 or (rid == 0x19 and sz >= 56):
                base = scenery_base(rec, rep)
                # 景物对象统一归 Model 组，组序号在后面的分组阶段统一分配
                if rid == 0x19:                                # 容器对象（SimObject）
                    title, sc = sim_object(rec)
                    objects.append('\t<SceneryObject%s\n'
                                   '\t\t<SimObject containerTitle="%s" scale="%.6f"/>\n\t</SceneryObject>'
                                   % (base, xesc(title), sc))
                    rep["counts"]["sim_object"] += 1
                elif rid == 0x18 or sz > 92:
                    pole = f32(rec, 72) if sz >= 80 else 4.572
                    sock = f32(rec, 76) if sz >= 80 else 2.7432
                    objects.append('\t<SceneryObject%s\n'
                                   '\t\t<Windsock poleHeight="%.6f" sockLength="%.6f"%s/>\n\t</SceneryObject>'
                                   % (base,
                                      pole / 0.3048 if 0.5 < pole < 30 else 15.0,
                                      sock / 0.3048 if 0.3 < sock < 10 else 9.0,
                                      ""))
                    rep["counts"]["windsock"] += 1
                else:
                    scale = f32(rec, 60)
                    objects.append('\t<SceneryObject%s\n'
                                   '\t\t<LibraryObject name="%s" scale="%.6f"/>\n\t</SceneryObject>'
                                   % (base, guid(rec[44:60]), scale if 0.001 < scale < 100 else 1.0))
                    rep["counts"]["library_object"] += 1
            pos += sz
    rep["objects"] = len(objects)

    if not ap["ident"]:
        base = source_name.replace("\\", "/").split("/")[-1]
        ap["ident"] = base.split(".")[0].upper()

    # 导航台（section 0x13）：按机场 + 跑道号 + 方位挂到跑道上
    rw_ils_unattached = attach_ils(g, ap, runway_meta, airport_nodes, rep)

    # 跑道入口：对照解析程序按 号+方位 与跑道主/次端比对；命中则作为该跑道的 <RunwayStart>，
    # 否则（类型非 1 或没有对应跑道）输出机场级的 <Start>
    start_lines = {}
    for spos, spay in pending_starts:
        end, hit = None, None
        if len(spay) >= 18 and ((spay[1] >> 4) & 0x0F) == 1:
            snum = RUNWAY_NUMBER_ENUM.get(spay[0], "00")
            sdesig = DESIGNATOR_ENUM.get(spay[1] & 0x0F, "NONE")
            for rw in runway_meta:
                if rw["pri_num"] == snum and rw["pri_desig"] == sdesig:
                    end, hit = "PRIMARY", rw
                    break
                if rw["sec_num"] == snum and rw["sec_desig"] == sdesig:
                    end, hit = "SECONDARY", rw
                    break
        slon, slat = lonlat(u32(spay, 2), u32(spay, 6))
        if end is None:
            rep["start_unmatched"] += 1
            # type 0 = 未指定，Schema 的 stStart 只有 TRACK/RUNWAY/HELIPAD/WATER 四值，
            # 此时省略 type 属性（ctStart 里 type 非必填）
            stype = (spay[1] >> 4) & 0x0F
            airport_nodes[spos] = (
                '\t\t<Start number="%s" designator="%s" lat="%s" lon="%s" alt="%.14f" heading="%.6f"%s/>'
                % (RUNWAY_NUMBER_ENUM.get(spay[0], "00"), DESIGNATOR_ENUM.get(spay[1] & 0x0F, "NONE"),
                   FMT.format(slat), FMT.format(slon), _nav_alt(i32(spay, 10)), f32(spay, 14),
                   (' type="%s"' % START_TYPE[stype]) if stype in START_TYPE and stype != 0 else ""))
            continue
        start_lines.setdefault(hit["node"], []).append(
            '\n\t\t\t<RunwayStart end="%s" lat="%s" lon="%s" alt="%.14f" heading="%.14f"/>'
            % (end, FMT.format(slat), FMT.format(slon), _nav_alt(i32(spay, 10)), f32(spay, 14)))
    for node_i, lines in start_lines.items():
        airport_nodes[node_i] = airport_nodes[node_i].replace(START_SLOT, "".join(lines) + START_SLOT)

    # 跑道子元素若出现在跑道之后，补挂到最后一条跑道上
    if rw_children:
        for i in range(len(airport_nodes) - 1, -1, -1):
            if "<Runway " in airport_nodes[i]:
                airport_nodes[i] = airport_nodes[i].replace(
                    "\n\t\t</Runway>", "".join(rw_children) + "\n\t\t</Runway>")
                break
        rw_children.clear()

    # 清掉未被填写的槽位（没有 Ils / RunwayStart 的跑道）
    for _i, _n in enumerate(airport_nodes):
        if ILS_SLOT in _n or START_SLOT in _n:
            airport_nodes[_i] = _n.replace(ILS_SLOT, "").replace(START_SLOT, "")

    # archetype 参数覆盖：把自闭合的 <AirportArchetype/> 展开成带子元素的节点
    for _i, _lines in arch_over.items():
        _n = airport_nodes[_i]
        if _n.endswith("/>"):
            airport_nodes[_i] = _n[:-2] + ">" + "".join(_lines) + "\n\t\t</AirportArchetype>"

    # ---------------- 分组：7 个景物顶层组 + 机场组(8) + 13 个子组(9..21) ----------------
    assign_airport_groups((airport_nodes, apron_nodes, painted_nodes, edge_light_nodes,
                           jetway_nodes, airport_object_nodes, objects))
    assign_scenery_groups(objects)

    # ---------------- 机场元数据（section 0x2C FsAirportSummary） ----------------
    for blob, chunk in g.data_of(0x2C):
        if len(blob) < 44:
            continue
        # 机场记录（0x0113/0x0056）已给出 XML 真正的 ident/magvar，这里只做兜底
        if not ap.get("ident_from_airport"):
            ap["ident"] = icao(u32(blob, 20)) or ap["ident"]
        ap["lon"] = _nav_lon(i32(blob, 8))
        ap["lat"] = _nav_lat(i32(blob, 12))
        ap["alt"] = _nav_alt(i32(blob, 16))
        if not ap.get("ident_from_airport"):
            ap["magvar"] = f32(blob, 28)
        rep["counts"]["summary"] += 1
        break

    # ---------------- 名称表（section 0x27 FsNameList）：区域/国家/省/市/机场名 ----------------
    for blob, chunk in g.data_of(0x27):
        if len(blob) < 20:
            continue
        counts = [u16(blob, 6 + 2 * k) for k in range(6)]
        offs = [u32(blob, 18 + 4 * k) for k in range(sum(counts))]
        pos, groups = 0, []
        for n in counts:
            groups.append([cstr(blob, o + 4) for o in offs[pos:pos + n]])
            pos += n

        def ok(s_):
            return bool(s_) and len(s_) >= 2 and s_.isprintable()

        cand = [groups[k][0] if k < len(groups) and groups[k] else "" for k in range(4)]
        if ok(cand[1]):
            for key, val in zip(("short", "country", "state", "city"), cand):
                if ok(val) and not ap.get(key):
                    ap[key] = val
        elif not ap.get("short") and not ap.get("country"):
            # 分组索引不可靠时，按「区域 / 国家 / 省 / 市 / 机场名…」顺序取前 4 个可打印串
            words, p = [], 0
            while p < len(blob):
                if blob[p] >= 0x20:
                    q = p
                    while q < len(blob) and blob[q] >= 0x20:
                        q += 1
                    s_ = blob[p:q].decode("utf-8", "replace")
                    if len(s_) >= 2:
                        words.append(s_)
                    p = q
                else:
                    p += 1
            if len(words) >= 4:
                ap["short"], ap["country"], ap["state"], ap["city"] = words[:4]
        rep["counts"]["namelist"] += 1
        break

    # ---------------- 输出 ----------------
    A('<?xml version="1.0"?>')
    A('<FSData version="9.0">')
    _gm = ""
    if ap.get("gm_bright"):
        _gm += ' groundMergingTransfertBright="%.6f"' % ap["gm_bright"]
    if ap.get("gm_dark"):
        _gm += ' groundMergingTransfertDark="%.6f"' % ap["gm_dark"]
    out.extend(group_elements_xml("\t"))
    A('\t<Airport displayName="%s" groupIndex="%d" groupID="%d" groupGenerated="FALSE" '
      'name="%s" ident="%s" '
      'lat="%.14f" lon="%.14f" alt="%.14f" magvar="%.6f"%s '
      'airportTestRadius="3000.00000000000000"%s isOnTIN="%s" tinColorCorrection="TRUE" '
      'starAirport="%s"%s>'
      % (xesc(ap["name"] or ap.get("short", "")), AIRPORT_GROUP_INDEX, AIRPORT_GROUP_ID,
         xesc(ap["name"] or ap.get("short", "")), xesc(ap["ident"]),
         ap["lat"], ap["lon"], ap["alt"], ap.get("magvar", 0.0),
         (' trafficScalar="%.6f"' % ap["traffic"]) if ap.get("traffic") else "",
         ' applyFlatten="TRUE"' if ap.get("flatten", True) else "",
         _tf_b(ap.get("tin", False)), _tf_b(ap.get("star", True)), _gm))
    out.extend(airport_sub_group_xml())
    A('\t\t<TaxiName index="0" name=""/>')
    out.extend(airport_nodes)
    if ap.get("fuel_mask", 0):
        out.extend(services_elements(ap.get("fuel_mask", 0)))
    out.extend(jetway_nodes)
    if edge_light_nodes:                                   # 对照解析程序始终输出该外壳（无灯时自闭合）
        A('\t\t<ApronEdgeLights>')
        out.extend(edge_light_nodes)
        A('\t\t</ApronEdgeLights>')
    else:
        A('\t\t<ApronEdgeLights/>')
    if apron_nodes:
        A('\t\t<Aprons>')
        out.extend(apron_nodes)
        A('\t\t</Aprons>')
    if painted_nodes:
        A('\t\t<PaintedElements>')
        out.extend(painted_nodes)
        A('\t\t</PaintedElements>')
    for p in presets:
        rep["counts"]["light_preset"] += 1
        A('\t\t<LightPreset name="%s" phase="%.6f" mesh="%s">' % (xesc(p["name"]), p["phase"], p["mesh"]))
        for lt in p["lights"]:
            A(lt)
            rep["counts"]["light"] += 1
        A('\t\t</LightPreset>')
    if del_airport[0]:
        A(del_airport[0])
    if rw_ils_unattached:
        out.extend(rw_ils_unattached)
    out.extend(airport_object_nodes)
    A('\t</Airport>')
    out.extend(objects)
    # ---------------- CVX 矢量/地形（section 0x65） ----------------
    out.extend(cvx_elements(g, rep))
    # ---------------- 排除矩形（section 0x2E） ----------------
    out.extend(exclusion_elements(g, rep))
    out.extend(ndb_elements(g, rep))
    out.extend(waypoint_elements(g, rep))
    out.extend(landmark_elements(g, rep))
    A('</FSData>')
    rep["profile"] = "2020" if is2020 else "2024"
    rep["airport"] = ap
    # 未解码记录去重（同一条重复出现只报一次，附次数）
    seen, uniq = {}, []
    for m in rep["unknown"]:
        if m in seen:
            seen[m] += 1
        else:
            seen[m] = 1
            uniq.append(m)
    rep["unknown"] = [m if seen[m] == 1 else "%s ×%d" % (m, seen[m]) for m in uniq]
    return "\n".join(out) + "\n", rep


def decompile_file(path: str, out_path: str | None = None, ident: str = "") -> tuple[str, dict]:
    with open(path, "rb") as fh:
        data = fh.read()
    xml, rep = decompile_bytes(data, source_name=path, ident=ident)
    if out_path:
        with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(xml)
    return xml, rep


def summarize(rep: dict) -> str:
    c = rep["counts"]
    ap = rep.get("airport", {})
    lines = [
        "机场: %s (%s)  %s / %s / %s" % (ap.get("name", ""), ap.get("ident", ""),
                                        ap.get("short", ""), ap.get("state", ""), ap.get("city", "")),
        "参考点: lat %.7f  lon %.7f  alt %.3f m" % (ap.get("lat", 0), ap.get("lon", 0), ap.get("alt", 0)),
        "跑道 %d | 入口 %d | COM %d | 滑行道点 %d | 滑行道路径 %d | 机位 %d | 停机坪 %d | 画线 %d | 边灯 %d | 标志牌 %d | 灯支座 %d | 登机桥 %d | 围栏 %d | 内嵌模型 %d | 顶点 %d"
        % (c["runway"], c["start"], c["com"], c["taxiway_point"], c["taxiway_path"],
           c["parking"], c["apron"], c["painted_line"], c["edge_lights"],
           c["taxiway_sign"], c["light_support"], c["jetway"], c["vector_placement"],
           c["airport_object"], c["vertex"]),
        "景物对象: %d（库对象 %d + 风向袋 %d）"
        % (rep.get("objects", 0), c["library_object"], c["windsock"]),
        "CVX 矢量: 多边形 %d | 矩形/高度图 %d" % (c["cvx_polygon"], c["cvx_rectangle"]),
    ]
    unk = sorted(set(rep["unknown"]))
    if c.get("cvx_ext_segment"):
        lines.append("CVX 未解图形段：%d 段（2024 高度类型 6 或需外部解码器的编码；记录长度已算出，图形未写入 XML）"
                     % c["cvx_ext_segment"])
    if c.get("projected_mesh_dup"):
        lines.append("投影网格重复表（0x56 内嵌 0xE8 子记录）：%d 条"
                     % c["projected_mesh_dup"])
    if c.get("arch_param"):
        lines.append("Archetype 参数覆盖（ParamOverride）：%d 条%s%s"
                     % (c["arch_param"],
                        "，其中 %d 条未找到所属 archetype" % c["arch_param_orphan"]
                        if c.get("arch_param_orphan") else "",
                        "，%d 条参数值取自未初始化内存（已按 0 输出）" % c["arch_param_junk"]
                        if c.get("arch_param_junk") else ""))
    if rep.get("start_unmatched"):
        lines.append("入口未匹配到跑道（已按对照解析程序规则输出为机场级 <Start>）：%d 条" % rep["start_unmatched"])
    if c.get("text_marking"):
        lines.append("文字标记（TextMarking）：%d 条" % c["text_marking"])
    if c.get("mast_light"):
        lines.append("灯柱（MastLight，0xFB 推测映射）：%d 条" % c["mast_light"])
    if c.get("wasm_module"):
        lines.append("WASM 模块声明（0x0102）：%d 条" % c["wasm_module"])
    if rep.get("park_suffix_bad"):
        lines.append("机位 suffix 值无合法枚举（N/PARKING 类，已按 NONE 输出）：%d 条"
                     % rep["park_suffix_bad"])
    for note in rep.get("decoded_notes", []):
        lines.append("已解码但未写入 XML：" + note)
    if unk:
        lines.append("未解码记录 %d 类：" % len(unk))
        lines += ["  - " + u for u in unk]
        samples = rep.get("unknown_samples") or {}
        for key in sorted(samples):
            rid, size = key.split("/")
            if any(("id %s size %s" % (rid, size)) in u for u in unk):
                lines.append("    %s/%s 载荷样例: %s" % (rid, size, samples[key]))
    return "\n".join(lines)


def report_text(rep: dict, info: dict = None) -> str:
    """生成可粘贴/可附加的诊断报告（含源文件指纹、摘要、记录统计、未解码明细）。"""
    import time as _time
    inf = info or {}
    c = rep["counts"]
    bar = "=" * 74
    thin = "-" * 74
    now = _time.strftime("%Y-%m-%d %H:%M:%S")
    out = [
        bar,
        "BGL 机场反编译器 v%s  诊断报告" % VERSION,
        bar,
        "生成时间   : %s（本机时间）" % now,
        "工具版本   : %s%s" % (VERSION, (" (" + inf["runtime"] + ")") if inf.get("runtime") else ""),
        "输出配置   : profile=%s  ident=%s" % (inf.get("profile") or rep.get("profile", ""),
                                             inf.get("ident") or "（未指定）"),
    ]
    if inf.get("source"):
        out.append("输入文件   : %s" % inf["source"])
        out.append("文件大小   : %s 字节%s"
                   % (format(inf.get("size", 0), ","),
                      ("  (%s)" % inf["mtime"]) if inf.get("mtime") else ""))
    if inf.get("sha256"):
        out.append("SHA-256    : %s" % inf["sha256"])
    if inf.get("output"):
        out.append("输出文件   : %s" % inf["output"])
        if inf.get("out_size"):
            out.append("输出大小   : %s 字节" % format(inf["out_size"], ","))
    out.append(thin)
    out.append("【机场摘要】")
    out.append(summarize(rep))
    recs = rep.get("records") or {}
    if recs:
        out.append(thin)
        out.append("【子记录统计】共 %d 条记录，%d 种 id（按次数降序）"
                   % (sum(recs.values()), len(recs)))
        for rid, n in sorted(recs.items(), key=lambda kv: (-kv[1], kv[0])):
            out.append("  %-10s %6d" % (rid, n))
    unk = sorted(set(rep.get("unknown") or []))
    out.append(thin)
    if unk:
        out.append("【未解码记录明细】%d 类" % len(unk))
        samples = rep.get("unknown_samples") or {}
        for i, u in enumerate(unk, 1):
            out.append("  %d. %s" % (i, u))
            for key in sorted(samples):
                rid, size = key.split("/")
                if ("id %s size %s" % (rid, size)) in u:
                    out.append("     载荷样例: %s" % samples[key])
    else:
        out.append("【未解码记录明细】无 —— 所有子记录都已识别")
    out.append(thin)
    out.append("提示：请把本文件（以及对应的 BGL）一起附到问题报告里。")
    return "\n".join(out) + "\n"
