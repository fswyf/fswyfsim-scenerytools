/*!
 * bgl2xml.js —— MSFS / FSX 机场 BGL 反编译器（纯前端，无依赖）
 *
 * 逆向所得格式（与 Python 版 bgl2xml_core.py 完全等价，已用 ZSFZ.bgl ↔ ZSFZ.xml 真值配对验证）：
 *   文件头 0x38: magic 0x19920201 | 0x38 | 0 | 0 | magic2 0x08051803 @+0x10 | section 数 @+0x14
 *   section 表 20 字节/条 (类型, 标志, 子块数, 目录偏移, 目录大小)
 *   子块目录   16 字节/条 (id, 记录数, 数据偏移, 数据大小)
 *   机场记录 (section 0x03, id 0x0113):
 *     +0 u16 id | +2 u32 长度 | +6 六个 u8 计数 | +12 经度 | +16 纬度 | +20 海拔(mm)
 *     +0x5C 起为 (u16 id, u32 size) 子记录流
 *   坐标: lon = raw*360/(3*2^28) - 180 ; lat = 90 - raw*180/2^29 ; 航向 = raw*360/2^32
 */
(function (global) {
  "use strict";

  var IS2020 = false;

  var VERSION = "1.4.1";
  var LON_SCALE = 360.0 / (3 * 0x10000000);
  var LAT_SCALE = 180.0 / (2 * 0x10000000);
  var HEAD_SCALE = 360.0 / Math.pow(2, 32);

  var PATH_TYPE = { 0: "UNKNOWN", 1: "TAXI", 2: "RUNWAY", 3: "PARKING", 4: "PATH", 5: "CLOSED", 6: "VEHICLE", 7: "ROAD" };
  var TAXI_POINT_ORIENT = { 0: "FORWARD", 1: "REVERSE" };

  /* 画线 / 网格填充画线共用的类型码（kmbase.bgl ↔ kmbase.xml 逐条顶点配对得出） */
  var LINE_TYPE = { 0x00: "DEFAULT", 0x01: "HOLD_SHORT_FORWARD", 0x02: "HOLD_SHORT_BACKWARD",
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
    0x29: "HOLD_SHORT_BACKWARD_MARKED_L" };
  var SURFACE_TYPE = { 0x00: "CONCRETE", 0x01: "GRASS", 0x02: "WATER", 0x03: "CEMENT", 0x04: "ASPHALT",
    0x07: "CLAY", 0x08: "SNOW", 0x09: "ICE", 0x0C: "DIRT", 0x0D: "CORAL", 0x0E: "GRAVEL",
    0x0F: "OIL_TREATED", 0x10: "STEEL_MATS", 0x11: "BITUMINOUS", 0x12: "BRICK", 0x13: "MACADAM",
    0x14: "PLANKS", 0x15: "SAND", 0x16: "SHALE", 0x17: "TARMAC", 0xFE: "UNKNOWN",
    512: "USE_FS20_MATERIAL", 65283: "USE_FS20_APRON_MATERIAL" };
  var HELIPAD_TYPE = { 0: "NONE", 1: "H", 2: "SQUARE", 3: "CIRCLE", 4: "MEDICAL" };
  var LIGHT_LEVEL = { 0: "NONE", 1: "LOW", 2: "MEDIUM", 3: "HIGH" };
  var VASI_TYPE = { 1: "VASI21", 2: "VASI31", 3: "VASI22", 4: "VASI32", 5: "VASI23", 6: "VASI33",
    7: "PAPI2", 8: "PAPI4", 9: "TRICOLOR", 10: "PVASI", 11: "TVASI", 12: "BALL" };
  var APPROACH_LIGHTS = { 1: "ODALS", 2: "MALSF", 3: "MALSR", 4: "SSALF", 5: "SSALR", 6: "ALSF1",
    7: "ALSF2", 8: "RAIL", 9: "CALVERT", 10: "CALVERT2", 11: "MALS", 12: "SALS", 13: "SALSF", 14: "SSALS" };
  var MARKING_BITS = [["edges", 0], ["threshold", 1], ["alternateThreshold", 13], ["fixedDistance", 2],
    ["alternateFixedDistance", 14], ["touchdown", 3], ["alternateTouchdown", 15], ["dashes", 4],
    ["ident", 5], ["precision", 6], ["edgePavement", 7], ["singleEnd", 8], ["primaryClosed", 9],
    ["secondaryClosed", 10], ["primaryStol", 11], ["secondaryStol", 12]];

  /* Markings 位域 → 属性串。extra 为跑道记录的灯光字节（Markings 的 m_raw 取 +48..50，
     故 alternatePrecision/leadingZeroIdent/noThresholdEndArrows 来自该字节的 bit5/6/7）。 */
  function markingsAttrs(bits, extra) {
    if (extra === undefined) extra = 0;
    var out = MARKING_BITS.map(function (p) {
      return p[0] + '="' + (((bits >> p[1]) & 1) ? "TRUE" : "FALSE") + '"';
    });
    out.splice(9, 0, 'leadingZeroIdent="' + tf((extra >> 6) & 1) + '"');
    out.splice(11, 0, 'alternatePrecision="' + tf((extra >> 5) & 1) + '"');
    out.push('noThresholdEndArrows="' + tf((extra >> 7) & 1) + '"');
    return out.join(" ");
  }

  /* 表面材质（对照解析程序：raw==0 即默认 CONCRETE 时属性整体省略） */
  function surfaceOf(kp) {
    var raw = u16(kp, 0);
    return raw ? (SURFACE_TYPE[raw] || "UNKNOWN") : null;
  }
  function surfaceAttr(kp) {
    var s = surfaceOf(kp);
    return s ? ' surface="' + s + '"' : "";
  }

  /* 跑道基记录（0x60 字节）之后的内嵌子记录 → 按 bglcomp.xsd 顺序拼成跑道子元素 */
  function runwayChildren(pay, rep) {
    var parts = { def: [], offset: [], blast: [], overrun: [], approach: [], vasi: [], material: [] },
        pos = 0x60 - 6;
    while (pos + 6 <= pay.length) {
      var krid = u16(pay, pos), ksz = u32(pay, pos + 2);
      if (ksz < 6 || pos + ksz > pay.length) break;
      var kp = pay.subarray(pos + 6, pos + ksz);
      pos += ksz;
      if (krid === 0x3E && kp.length >= 18) {
        var cb = f32(kp, 10), ca = f32(kp, 14), extra = "";
        if (cb === cb && cb !== 0) extra += ' controlPointBefore="' + f(cb, 6) + '"';
        if (ca === ca && ca !== 0) extra += ' controlPointAfter="' + f(ca, 6) + '"';
        parts.def.push('\n\t\t\t<RunwayDeformation alt="' + f6(f32(kp, 6)) + '" ratio="' + f6(f32(kp, 2)) + extra + '"/>');
        rep.counts.runway_deformation++;
      } else if ((krid === 0x0B || krid === 0x0C || krid === 0x0D || krid === 0x0E) && kp.length >= 18) {
        parts.vasi.push('\n\t\t\t<Vasi end="' + ((krid === 0x0B || krid === 0x0C) ? "PRIMARY" : "SECONDARY") +
          '" side="' + ((krid === 0x0B || krid === 0x0D) ? "LEFT" : "RIGHT") + '" type="' +
          (VASI_TYPE[u16(kp, 0)] || "PAPI4") + '" biasX="' + f(f32(kp, 2), 6) + '" biasZ="' + f(f32(kp, 6), 6) +
          '" spacing="' + f(f32(kp, 10), 6) + '" pitch="' + f(f32(kp, 14), 6) + '"/>');
        rep.counts.vasi++;
      } else if ((krid === 0x0F || krid === 0x10 || krid === 0xDF || krid === 0xE0) && kp.length >= 18) {
        var abits = u16(kp, 0);
        parts.approach.push('\n\t\t\t<ApproachLights end="' + ((krid === 0x0F || krid === 0xDF) ? "PRIMARY" : "SECONDARY") +
          '" system="' + (APPROACH_LIGHTS[abits & 0x0F] || "NONE") + '" strobes="' + ((abits >> 8) & 0xFF) +
          '" endLights="' + ((abits & 0x20) ? "TRUE" : "FALSE") + '" touchdown="' + ((abits & 0x80) ? "TRUE" : "FALSE") +
          '" snapToGround="' + ((kp.length > 14 && kp[14]) ? "TRUE" : "FALSE") + '" reil="' +
          ((abits & 0x40) ? "TRUE" : "FALSE") + '" offset="' + f(f32(kp, 6), 6) +
          '" spacing="' + f(f32(kp, 2), 6) + '" slope="' + f(f32(kp, 10), 6) + '"/>');
        rep.counts.approach_lights++;
      } else if ((krid === 0x05 || krid === 0x06) && kp.length >= 10) {
        parts.offset.push('\n\t\t\t<OffsetThreshold end="' + (krid === 0x05 ? "PRIMARY" : "SECONDARY") +
          '" length="' + f(f32(kp, 2), 14) + '" width="' + f(f32(kp, 6), 14) + surfaceAttr(kp) + '"/>');
        rep.counts.offset_threshold++;
      } else if ((krid === 0x07 || krid === 0x08) && kp.length >= 10) {
        parts.blast.push('\n\t\t\t<BlastPad end="' + (krid === 0x07 ? "PRIMARY" : "SECONDARY") +
          '" length="' + f(f32(kp, 2), 14) + '" width="' + f(f32(kp, 6), 14) + surfaceAttr(kp) + '"/>');
        rep.counts.blast_pad++;
      } else if ((krid === 0x09 || krid === 0x0A || krid === 0x65 || krid === 0x66) && kp.length >= 10) {
        parts.overrun.push('\n\t\t\t<Overrun end="' + ((krid === 0x09 || krid === 0x65) ? "PRIMARY" : "SECONDARY") +
          '" length="' + f(f32(kp, 2), 14) + '" width="' + f(f32(kp, 6), 14) + surfaceAttr(kp) + '"/>');
        rep.counts.overrun++;
      } else if (krid === 0xCB && kp.length >= 38) {
        parts.material.push('\n\t\t\t<Material guid="' + guid(kp.subarray(2, 18)) + '" type="' + kp[0] + '" tilingU="' + f(f32(kp, 22), 6) +
          '" tilingV="' + f(f32(kp, 26), 6) + '" width="' + f(f32(kp, 30), 6) +
          '" falloff="' + f(f32(kp, 34), 6) + '"/>');
        rep.counts.facility_material++;
      } else {
        rep.unknown.push("runway child id 0x" + ("0000" + krid.toString(16)).slice(-4) + " size " + kp.length);
      }
    }
    return parts;
  }

  /* 跑道元素内为 Ils / RunwayStart 预留的槽位（子记录可能出现在跑道记录之后，故延后填入） */
  var ILS_SLOT = "\u0001ILS\u0001";
  var START_SLOT = "\u0001START\u0001";
  var START_TYPE = { 0: "UNKNOWN", 1: "RUNWAY", 2: "WATER", 3: "HELIPAD", 4: "TRACK" };

  /* DeleteAirport 的 48 位标志 → 属性名（位序由差分定位：flags u16 位 0-11，flags2 u8 位 0-7 → 32-39） */
  var DEL_FLAGS = [["deleteAllApproaches", 0], ["deleteAllApronLights", 1], ["deleteAllAprons", 2],
    ["deleteAllFrequencies", 3], ["deleteAllHelipads", 4], ["deleteAllRunways", 5], ["deleteAllStarts", 6],
    ["deleteAllTaxiways", 7], ["deleteAllVectorPlacement", 8], ["deleteAllBoundaryFences", 9],
    ["deleteAllJetways", 10], ["deleteAllControlTowers", 11], ["deleteAllDepartures", 32],
    ["deleteAllArrivals", 33], ["deleteAllPaintedElements", 34], ["deleteAllLightSupports", 35],
    ["deleteAllTaxiwaySigns", 36], ["deleteAllILSs", 37], ["deleteAllTerminalWaypoints", 38],
    ["deleteAllTerminalNDBs", 39]];
  var DEL_UNMAPPED = [];
  var POINT_TYPE = { 0: "UNKNOWN", 1: "NORMAL", 2: "HOLD_SHORT", 4: "ILS_HOLD_SHORT", 5: "HOLD_SHORT_NO_DRAW", 6: "ILS_HOLD_SHORT_NO_DRAW" };
  var TOWER_SIZE = { 0: "NONE", 1: "SMALL", 2: "MEDIUM", 3: "LARGE" };
  var PARK_NAME = { 0: "NONE", 1: "PARKING", 2: "N_PARKING", 3: "NE_PARKING", 4: "E_PARKING", 5: "SE_PARKING", 6: "S_PARKING", 7: "SW_PARKING", 8: "W_PARKING", 9: "NW_PARKING", 10: "GATE", 11: "DOCK", 12: "GATE_A", 13: "GATE_B", 14: "GATE_C", 15: "GATE_D", 16: "GATE_E", 17: "GATE_F", 18: "GATE_G", 19: "GATE_H", 20: "GATE_I", 21: "GATE_J", 22: "GATE_K", 23: "GATE_L", 24: "GATE_M", 25: "GATE_N", 26: "GATE_O", 27: "GATE_P", 28: "GATE_Q", 29: "GATE_R", 30: "GATE_S", 31: "GATE_T", 32: "GATE_U", 33: "GATE_V", 34: "GATE_W", 35: "GATE_X", 36: "GATE_Y", 37: "GATE_Z" };
/* stParkingSuffix 只收 NONE + GATE_A..GATE_Z，其余名称没有合法写法 */
var SUFFIX_OK = Object.keys(PARK_NAME).map(function (k) { return PARK_NAME[k]; })
  .filter(function (v) { return v === "NONE" || /^GATE_[A-Z]$/.test(v); });
  var PARK_TYPE = { 0: "NONE", 1: "RAMP_GA", 2: "RAMP_GA_SMALL", 3: "RAMP_GA_MEDIUM", 4: "RAMP_GA_LARGE", 5: "RAMP_CARGO", 6: "RAMP_MIL_CARGO", 7: "RAMP_MIL_COMBAT", 8: "GATE_SMALL", 9: "GATE_MEDIUM", 10: "GATE_HEAVY", 11: "DOCK_GA", 12: "FUEL", 13: "VEHICLE", 14: "RAMP_GA_EXTRA", 15: "GATE_EXTRA" };
  var COM_TYPE = { 1: "ATIS", 2: "MULTICOM", 3: "UNICOM", 4: "CTAF", 5: "GROUND", 6: "TOWER",
    7: "CLEARANCE", 8: "APPROACH", 9: "DEPARTURE", 10: "CENTER", 11: "FSS", 12: "AWOS", 13: "ASOS",
    14: "CLEARANCE_PRE_TAXI", 15: "REMOTE_CLEARANCE_DELIVERY" };
  /* COM 类型码 → MSFS 类型名；表外的码回退成 TOWER 并记进未解码清单 */
  function comType(code, rep) {
    var t = COM_TYPE[code];
    if (t === undefined) { rep.unknown.push("com type code 0x" + hex2(code)); t = "TOWER"; }
    return t;
  }
  var SECTION_AIRPORT = 0x03, SECTION_OBJECTS = 0x25, SECTION_META = 0x35;

  function BglError(msg) { this.name = "BglError"; this.message = msg; }
  BglError.prototype = Object.create(Error.prototype);

  function u16(b, o) { return b[o] | (b[o + 1] << 8); }
  function u32(b, o) { return (b[o] | (b[o + 1] << 8) | (b[o + 2] << 16) | (b[o + 3] << 24)) >>> 0; }
  function i32(b, o) { return b[o] | (b[o + 1] << 8) | (b[o + 2] << 16) | (b[o + 3] << 24); }
  function i16(b, o) { var v = b[o] | (b[o + 1] << 8); return v >= 0x8000 ? v - 0x10000 : v; }
  function f32(b, o) {
    var dv = new DataView(b.buffer, b.byteOffset + o, 4);
    return dv.getFloat32(0, true);
  }
  function lonlat(lo, la) { return [lo * LON_SCALE - 180.0, 90.0 - la * LAT_SCALE]; }

  function hex2(n) { return (n < 16 ? "0" : "") + n.toString(16); }

  function guid(raw) {
    var d1 = ((raw[3] << 24) | (raw[2] << 16) | (raw[1] << 8) | raw[0]) >>> 0;
    var d2 = (raw[5] << 8) | raw[4];
    var d3 = (raw[7] << 8) | raw[6];
    var s = "";
    for (var i = 8; i < 16; i++) s += hex2(raw[i]);
    var p = function (v, w) { var t = v.toString(16).toUpperCase(); while (t.length < w) t = "0" + t; return t; };
    return "{" + p(d1, 8) + "-" + p(d2, 4) + "-" + p(d3, 4) + "-" + s.slice(0, 4).toUpperCase() + "-" + s.slice(4).toUpperCase() + "}";
  }

  var UTF8 = new TextDecoder("utf-8");
  function cstr(pay, o) {
    if (o >= pay.length) return "";
    var e = pay.indexOf(0, o);
    if (e < 0) e = pay.length;
    return UTF8.decode(pay.subarray(o, e));
  }
  function stripZeros(s) { return s.replace(/^[\s\u0000]+|[\s\u0000]+$/g, ""); }
  function cstrBytes(buf) {
    var e = buf.indexOf(0);
    if (e < 0) e = buf.length;
    return UTF8.decode(buf.subarray(0, e));
  }
  function trimWs(s) { return s.replace(/^\s+|\s+$/g, ""); }
  /* 小数点后 d 位——与 Python 的 "%.*f" 完全一致。
     做法：先用 toFixed 展开成精确十进制串，再按「半数取偶」手工进位。
     （直接 toFixed(d) 是半数进位，会在 128.3203125、-40.648998260498046875 这类值上差 1e-14~1e-6） */
  /* 保留负零符号（Python 的 %.6f 对 -0.0 输出 -0.000000） */
  function f6(n) {
    var x = Number(n), s = f(x, 6);
    return (s === "0.000000" && x === 0 && 1 / x === -Infinity) ? "-0.000000" : s;
  }

  function f(n, d) {
    var x = Number(n);
    if (!isFinite(x)) return String(x);
    var s = x.toFixed(Math.min(100, d + 6));
    if (s.indexOf("e") >= 0 || s.indexOf("E") >= 0) return String(x);
    var neg = s.charAt(0) === "-";
    if (neg) s = s.slice(1);
    var dot = s.indexOf(".");
    if (dot < 0) s += ".";
    dot = s.indexOf(".");
    var ip = s.slice(0, dot), fp = s.slice(dot + 1);
    while (fp.length < d) fp += "0";
    var keep = fp.slice(0, d), rest = fp.slice(d), cmp = 0;
    for (var i = 0; i < rest.length; i++) {
      var c = +rest.charAt(i), half = (i === 0) ? 5 : 0;
      if (c > half) { cmp = 1; break; }
      if (c < half) { cmp = -1; break; }
    }
    var up = cmp > 0 || (cmp === 0 && d > 0 && (+keep.charAt(keep.length - 1)) % 2 === 1);
    if (up) {
      var arr = (ip + keep).split(""), k = arr.length - 1;
      while (k >= 0) {
        if (arr[k] === "9") { arr[k] = "0"; k--; } else { arr[k] = String(+arr[k] + 1); break; }
      }
      if (k < 0) arr.unshift("1");
      var joined = arr.join("");
      ip = joined.slice(0, joined.length - d) || "0";
      keep = joined.slice(joined.length - d);
    }
    var out = d > 0 ? ip + "." + keep : ip;
    return (neg ? "-" : "") + out;
  }

  function Bgl(data) {
    this.b = data;
    if (data.length < 0x38 || !(data[0] === 0x01 && data[1] === 0x02 && data[2] === 0x92 && data[3] === 0x19)) {
      throw new BglError("不是 MSFS/FSX BGL（文件头 magic 不符）");
    }
    this.nsec = u32(data, 0x14);
    if (this.nsec > 1000) throw new BglError("section 数量异常，可能不是机场 BGL");
    this.sections = [];
    for (var i = 0; i < this.nsec; i++) {
      var o = 0x38 + i * 20;
      if (o + 20 > data.length) break;
      var st = u32(data, o), fl = u32(data, o + 4), cn = u32(data, o + 8), sb = u32(data, o + 12);
      var stride = ((fl & 0x10000) | 0x40000) >> 14;
      var chunks = [];
      for (var c = 0; c < cn; c++) {
        var p = sb + c * stride + stride - 16;
        if (p + 16 > data.length) break;
        chunks.push({ id: u32(data, p), nrec: u32(data, p + 4), off: u32(data, p + 8), size: u32(data, p + 12) });
      }
      this.sections.push({ type: st, flags: fl, chunks: chunks });
    }
  }
  Bgl.prototype.dataOf = function (stype) {
    var out = [];
    for (var i = 0; i < this.sections.length; i++) {
      var s = this.sections[i];
      if (s.type === stype) {
        for (var c = 0; c < s.chunks.length; c++) {
          var ch = s.chunks[c];
          out.push([this.b.subarray(ch.off, ch.off + ch.size), ch]);
        }
      }
    }
    return out;
  };

  function chain(blob, start) {
    var pos = (start === undefined ? 0x5C : start), out = [];
    while (pos + 6 <= blob.length) {
      var rid = u16(blob, pos), sz = u32(blob, pos + 2);
      if (sz < 6 || pos + sz > blob.length) break;
      out.push([rid, blob.subarray(pos + 6, pos + sz), pos]);
      pos += sz;
    }
    return out;
  }

  /* 两种机场记录格式的子记录链起点：0x0113 → +0x5C，FSX 系 0x0056 → +0x44。
     先用头部 id 猜，再用实际走链长度（能否走到记录尾）校验，必要时在候选起点里挑最优。 */
  function chainEnd(blob, start) {
    var pos = start;
    while (pos + 6 <= blob.length) {
      var sz = u32(blob, pos + 2);
      if (sz < 6 || pos + sz > blob.length) break;
      pos += sz;
    }
    return pos;
  }

  function chainStart(blob, headerId) {
    var prefer = headerId === 0x0113 ? 0x5C : 0x44;
    var best = prefer, bestEnd = chainEnd(blob, prefer);
    if (bestEnd < blob.length * 0.9) {
      [0x5C, 0x44, 0x64, 0x68].forEach(function (s) {
        if (s + 6 > blob.length) return;
        var e = chainEnd(blob, s);
        if (e > bestEnd) { best = s; bestEnd = e; }
      });
    }
    return best;
  }

  /* XML 属性/文本转义：滑行道牌等文本里会出现 < > & 之类的字符 */
  function xesc(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  /* 景物记录的经纬度/海拔/航向：lon@+4 lat@+8 alt@+12；航向是 +22 处的 i16 × 360/65536 */
  function objPose(rec) {
    var ll = lonlat(u32(rec, 4), u32(rec, 8));
    var hdg = i16(rec, 22) * 360.0 / 65536.0;
    // Altitude.meters = f32(raw * f32(0.001))，两次单精度舍入
    return { lon: ll[0], lat: ll[1], alt: navAlt(i32(rec, 12)), hdg: hdg, altRaw: i32(rec, 12) };
  }

  /* 投影网格记录（0xE8 载荷，或 0x56 重复表里的同构子记录载荷）→ <ProjectedMesh> */
  function pmAdd(pay, rep, nodes) {
    if (pay.length < 74 || u16(pay, 8) !== 0x0B) return false;
    var eisz = u16(pay, 10);
    if (!(eisz >= 64 && eisz <= pay.length - 8)) return false;
    var erec = pay.subarray(8, 8 + eisz);
    var pose = objPose(erec);
    rep.counts.projected_mesh++;
    nodes.push('\t\t<ProjectedMesh priority="' + pay[0] + '" groundMerging="' + tf(pay[2] & 1) + '">\n' +
      '\t\t\t<SceneryObject lat="' + f(pose.lat, 14) + '" lon="' + f(pose.lon, 14) + '" alt="' + f(pose.alt, 14) +
      '" altitudeIsAgl="TRUE" snapToGround="FALSE" snapToNormal="FALSE" pitch="' +
      f(i16(erec, 18) * 360.0 / 65536.0, 6) + '" bank="' + f(i16(erec, 20) * 360.0 / 65536.0, 6) +
      '" heading="' + f(pose.hdg, 6) + '" imageComplexity="' + (COMPLEXITY[u16(erec, 24)] || "NORMAL") +
      '"/>\n\t\t</ProjectedMesh>');
    return true;
  }

  /* 景物记录标志字节 @+16 的位 → 对照输出的空子元素（位序由差分定位） */
  var OBJ_FLAG_KIDS = [["NoAutogenSuppression", 1], ["NoCrash", 2], ["NoFog", 3], ["NoShadow", 4]];
  var OBJ_FLAG_KIDS2 = [["NoZWrite", 5], ["NoZTest", 6], ["HideOnTIN", 7]];
  var COMPLEXITY = { 0: "VERY_SPARSE", 1: "SPARSE", 2: "NORMAL", 3: "DENSE", 4: "VERY_DENSE",
    5: "EXTREMELY_DENSE" };

  /* 景物记录的公共部分：SceneryObject 属性串 + No* 空子元素串 */
  function sceneryBase(rec) {
    var flags = rec.length > 16 ? rec[16] : 0, kids = [], i;
    for (i = 0; i < OBJ_FLAG_KIDS.length; i++)
      if ((flags >> OBJ_FLAG_KIDS[i][1]) & 1) kids.push(OBJ_FLAG_KIDS[i][0]);
    if (rec.length > 26 && (u16(rec, 26) & 1)) kids.push("NoSnow");
    for (i = 0; i < OBJ_FLAG_KIDS2.length; i++)
      if ((flags >> OBJ_FLAG_KIDS2[i][1]) & 1) kids.push(OBJ_FLAG_KIDS2[i][0]);
    var kid = "";
    for (i = 0; i < kids.length; i++) kid += '\n\t\t<' + kids[i] + '/>';
    var iid = rec.length >= 44 ? rec.subarray(28, 44) : new Uint8Array(0);
    var zero = true;
    for (i = 0; i < iid.length; i++) if (iid[i]) { zero = false; break; }
    var pose = objPose(rec);
    return (zero ? '' : ' instanceId="' + guid(iid) + '"') +
      ' lat="' + f(pose.lat, 14) + '" lon="' + f(pose.lon, 14) + '" alt="' + f(pose.alt, 14) +
      '" pitch="' + f(i16(rec, 18) * 360.0 / 65536.0, 6) + '" bank="' + f(i16(rec, 20) * 360.0 / 65536.0, 6) +
      '" heading="' + f(pose.hdg, 6) + '" imageComplexity="' + (COMPLEXITY[u16(rec, 24)] || "NORMAL") +
      '" altitudeIsAgl="' + ((flags & 1) ? "TRUE" : "FALSE") + '" snapToGround="' +
      (i32(rec, 12) === 0 ? "TRUE" : "FALSE") + '" snapToNormal="FALSE">' + kid;
  }

  /* id 0x19 的容器对象记录：f32 scale@+44 | u32 名称长度@+48 | 名称@+52 */
  function simObject(rec) {
    var title = "", scale = 1.0;
    if (rec.length >= 56) {
      var nlen = u32(rec, 48);
      if (nlen > 0 && nlen <= Math.min(64, rec.length - 52)) {
        var txt = cstr(rec, 52).replace(/\u0000+$/, "");
        if (/^[\x20-\x7E\u00A0-\uFFFF]*$/.test(txt) && txt.length) title = txt;
      }
      var sc = f32(rec, 44);
      scale = (sc > 0.001 && sc < 100) ? sc : 1.0;
    }
    return { title: title, scale: scale };
  }

  /* 内嵌对象记录的名称：长度取 u32@+48，文本候选偏移 54 优先、52 兜底，
     取第一个长度够、全部可打印且不含 NUL 的候选；都不成立返回 null */
  function simName(rec) {
    if (rec.length < 52) return null;
    var nlen = u32(rec, 48);
    if (!(nlen > 0 && nlen <= 64)) return null;
    var cands = [54, 52];
    for (var ci = 0; ci < 2; ci++) {
      var off = cands[ci];
      if (off + nlen <= rec.length) {
        var t = UTF8.decode(rec.subarray(off, off + nlen));
        if (t.length && !/[\u0000-\u001F\u007F]/.test(t)) return t;
      }
    }
    return null;
  }

  /* ======================= CVX（section 0x65 矢量/地形） ======================= */
  /* 属性 GUID → [值类型, XML type, XML name]，取自对照解析程序的属性映射表 */
  var CVX_ATTR = {
    "CE85242F-4110-4706-8344-1F3A8EE422BE": ["string", "STRING", "Version"],
    "359C73E8-06BE-4FB2-ABCB-EC942F7761D0": ["Guid", "GUID", "AirportBounds"],
    "1B6A15BB-05FB-4401-A8D1-BB520E84904C": ["Guid", "GUID", "Texture"],
    "5548FDB5-2267-4328-8E6F-FD0A45ADEC8F": ["float", "FLOAT32", "FalloffDistance"],
    "065E9D4D-6984-4D2A-91FD-3C33C4F53B22": ["byte", "UINT8", "FlattenMode"],
    "5C1A2387-1F07-47DF-A569-962CF6258E55": ["byte", "UINT8", "ExcludeDetectedBuildings"],
    "F3C2635D-9F2F-458F-8663-90B3837BED09": ["byte", "UINT8", "ExcludeOSMBuildings"],
    "F78A3074-8AD5-4B8B-92C4-C1C948BB7AA5": ["byte", "UINT8", "ExcludeMSBuildings"],
    "6A043F59-E6F2-4117-A2E4-D510E7317C29": ["uint", "UINT32", "VegetationScale"],
    "0A685EB0-0E01-44FE-B9EF-BFFFBC968ADE": ["byte", "UINT8", "LandClassRemap"],
    "CD28EFD0-D3F0-43B6-9F88-4E4707344A04": ["Guid", "GUID", "MaterialGUID"],
    "18B58CBF-AE02-4A19-8AA9-3809E8E73400": ["byte", "UINT8", "ExcludeTIN"],
    "4C252581-63E9-4C22-8A3D-14B31F3C8157": ["byte", "UINT8", "BuildingTIN"],
    "69A63EDD-FBE5-4F0D-88E6-6FA01963D613": ["byte", "UINT8", "ForceDetectedBuilding"],
    "41EFF715-C392-4B31-A457-50A504353A90": ["uint", "UINT32", "VegetationDensity"],
    "9E2B4C3E-7D84-453F-9DCC-B6498FF46703": ["uint", "UINT32", "Layer"],
    "4CACC252-E6DC-419A-B20C-16EC601DF70E": ["uint", "UINT32", "ExclusionFlags"],
    "F60DBBC7-DE6F-4FEA-BE7E-AFB1D73D57E7": ["byte", "UINT8", "AffectRocks"],
    "F104723A-D6D1-4B2E-9B44-ACCD8AB372DC": ["byte", "UINT8", "ExcludeRocks"],
    "9460843D-964B-4E45-AC49-634856FB6E1C": ["byte", "UINT8", "ForceElevation"],
    "E82ABE17-FB4C-4F67-A28C-ED41969AEAD6": ["float", "FLOAT32", "VegetationFalloff"],
    "684AFC09-9B38-4431-8D76-E825F54A4DFF": ["byte", "UINT8", "IsWater"],
    "972B7BAC-F620-4D6E-9724-E70BF8A450DD": ["byte", "UINT8", "IsWaterExclusion"],
    "3F8514F8-FAA8-4B94-AB7F-DC2078A4B888": ["uint", "UINT32", "WaterType"],
    "86A147E9-ACF2-4780-9D3C-416373ECB451": ["byte", "UINT8", "AirportSize"],
    "8C1A396B-F730-4128-981A-C90600F856E0": ["uint", "UINT32", "EcoRegion"],
    "09409810-AD40-48DE-A209-DB1CB10601F7": ["uint", "UINT32", "PotentialNaturalVegetation"],
    "F8A7B13F-BD91-48F8-AC66-6C8601A2F1C6": ["byte", "UINT8", "IsAirportInternational"],
    "C4EC4055-3177-4757-82FB-44038B244BA9": ["byte", "UINT8", "IsArtificialSurface"],
    "63040596-0B21-48FD-8B5F-A9E84A5B7BC9": ["uint", "UINT", "TreeBrightnessFactor"],
    "4D2A51D4-91AC-412F-833E-212CC10E5FBC": ["byte", "UINT8", "PreciseTerraforming"],
    "302AC02A-007B-493D-A1B8-4E7A408304BF": ["bytes", "RAW", "FlattenData"],
    "99312E49-88B1-470E-BD06-CA3A6A8C53CF": ["float", "FLOAT32", "Width"],
    "F0B11821-16FC-407B-BE5A-DBEB67A77571": ["string", "STRING", "GeomeName"]
  };
  var CVX_G_VERSION = "CE85242F-4110-4706-8344-1F3A8EE422BE";
  var CVX_G_BOUNDS = "359C73E8-06BE-4FB2-ABCB-EC942F7761D0";
  var CVX_G_WIDTH = "99312E49-88B1-470E-BD06-CA3A6A8C53CF";
  var CVX_G_FALLOFF = "5548FDB5-2267-4328-8E6F-FD0A45ADEC8F";
  var CVX_G_TEXTURE = "1B6A15BB-05FB-4401-A8D1-BB520E84904C";
  var CVX_G_LAYER = "9E2B4C3E-7D84-453F-9DCC-B6498FF46703";
  var CVX_G_FLATTEN = "065E9D4D-6984-4D2A-91FD-3C33C4F53B22";
  var CVX_G_PRECISION = "4D2A51D4-91AC-412F-833E-212CC10E5FBC";
  var CVX_G_FLATTEN_DATA = "302AC02A-007B-493D-A1B8-4E7A408304BF";
  var CVX_G_FORCE_ELEV = "9460843D-964B-4E45-AC49-634856FB6E1C";
  var CVX_G_HEIGHTMAP = "B7DCEA33-BD4B-4B3C-B4E2-8ECB145CB629";
  var CVX_NON_ATTR = [CVX_G_WIDTH, CVX_G_FLATTEN_DATA];
  var CVX_TOL = 1e-05;

  /* MD5（用于合成 UniqueGUID，与对照解析程序同算法） */
  function md5Hex(str, bin) {
    function rl(n, c) { return (n << c) | (n >>> (32 - c)); }
    function au(x, y) { var l = (x & 0xFFFF) + (y & 0xFFFF); return (((x >> 16) + (y >> 16) + (l >> 16)) << 16) | (l & 0xFFFF); }
    function cmn(q, a, b, x, s, t) { return au(rl(au(au(a, q), au(x, t)), s), b); }
    function ff(a, b, c, d, x, s, t) { return cmn((b & c) | (~b & d), a, b, x, s, t); }
    function gg(a, b, c, d, x, s, t) { return cmn((b & d) | (c & ~d), a, b, x, s, t); }
    function hh(a, b, c, d, x, s, t) { return cmn(b ^ c ^ d, a, b, x, s, t); }
    function ii(a, b, c, d, x, s, t) { return cmn(c ^ (b | ~d), a, b, x, s, t); }
    function bytes(s) {
      var u = unescape(encodeURIComponent(s)), a = [];
      for (var i = 0; i < u.length; i++) a.push(u.charCodeAt(i));
      return a;
    }
    var b = bin ? Array.prototype.slice.call(bin) : bytes(str), len = b.length * 8;
    b.push(0x80);
    while (b.length % 64 !== 56) b.push(0);
    var lo = len >>> 0, hi = Math.floor(len / 4294967296);
    for (var i = 0; i < 4; i++) b.push((lo >>> (8 * i)) & 0xFF);
    for (var i = 0; i < 4; i++) b.push((hi >>> (8 * i)) & 0xFF);
    var a0 = 1732584193, b0 = -271733879, c0 = -1732584194, d0 = 271733878;
    for (var i = 0; i < b.length; i += 64) {
      var x = [];
      for (var j = 0; j < 16; j++)
        x[j] = b[i + j * 4] | (b[i + j * 4 + 1] << 8) | (b[i + j * 4 + 2] << 16) | (b[i + j * 4 + 3] << 24);
      var a = a0, bb = b0, c = c0, d = d0;
      a = ff(a, bb, c, d, x[0], 7, -680876936); d = ff(d, a, bb, c, x[1], 12, -389564586);
      c = ff(c, d, a, bb, x[2], 17, 606105819); bb = ff(bb, c, d, a, x[3], 22, -1044525330);
      a = ff(a, bb, c, d, x[4], 7, -176418897); d = ff(d, a, bb, c, x[5], 12, 1200080426);
      c = ff(c, d, a, bb, x[6], 17, -1473231341); bb = ff(bb, c, d, a, x[7], 22, -45705983);
      a = ff(a, bb, c, d, x[8], 7, 1770035416); d = ff(d, a, bb, c, x[9], 12, -1958414417);
      c = ff(c, d, a, bb, x[10], 17, -42063); bb = ff(bb, c, d, a, x[11], 22, -1990404162);
      a = ff(a, bb, c, d, x[12], 7, 1804603682); d = ff(d, a, bb, c, x[13], 12, -40341101);
      c = ff(c, d, a, bb, x[14], 17, -1502002290); bb = ff(bb, c, d, a, x[15], 22, 1236535329);
      a = gg(a, bb, c, d, x[1], 5, -165796510); d = gg(d, a, bb, c, x[6], 9, -1069501632);
      c = gg(c, d, a, bb, x[11], 14, 643717713); bb = gg(bb, c, d, a, x[0], 20, -373897302);
      a = gg(a, bb, c, d, x[5], 5, -701558691); d = gg(d, a, bb, c, x[10], 9, 38016083);
      c = gg(c, d, a, bb, x[15], 14, -660478335); bb = gg(bb, c, d, a, x[4], 20, -405537848);
      a = gg(a, bb, c, d, x[9], 5, 568446438); d = gg(d, a, bb, c, x[14], 9, -1019803690);
      c = gg(c, d, a, bb, x[3], 14, -187363961); bb = gg(bb, c, d, a, x[8], 20, 1163531501);
      a = gg(a, bb, c, d, x[13], 5, -1444681467); d = gg(d, a, bb, c, x[2], 9, -51403784);
      c = gg(c, d, a, bb, x[7], 14, 1735328473); bb = gg(bb, c, d, a, x[12], 20, -1926607734);
      a = hh(a, bb, c, d, x[5], 4, -378558); d = hh(d, a, bb, c, x[8], 11, -2022574463);
      c = hh(c, d, a, bb, x[11], 16, 1839030562); bb = hh(bb, c, d, a, x[14], 23, -35309556);
      a = hh(a, bb, c, d, x[1], 4, -1530992060); d = hh(d, a, bb, c, x[4], 11, 1272893353);
      c = hh(c, d, a, bb, x[7], 16, -155497632); bb = hh(bb, c, d, a, x[10], 23, -1094730640);
      a = hh(a, bb, c, d, x[13], 4, 681279174); d = hh(d, a, bb, c, x[0], 11, -358537222);
      c = hh(c, d, a, bb, x[3], 16, -722521979); bb = hh(bb, c, d, a, x[6], 23, 76029189);
      a = hh(a, bb, c, d, x[9], 4, -640364487); d = hh(d, a, bb, c, x[12], 11, -421815835);
      c = hh(c, d, a, bb, x[15], 16, 530742520); bb = hh(bb, c, d, a, x[2], 23, -995338651);
      a = ii(a, bb, c, d, x[0], 6, -198630844); d = ii(d, a, bb, c, x[7], 10, 1126891415);
      c = ii(c, d, a, bb, x[14], 15, -1416354905); bb = ii(bb, c, d, a, x[5], 21, -57434055);
      a = ii(a, bb, c, d, x[12], 6, 1700485571); d = ii(d, a, bb, c, x[3], 10, -1894986606);
      c = ii(c, d, a, bb, x[10], 15, -1051523); bb = ii(bb, c, d, a, x[1], 21, -2054922799);
      a = ii(a, bb, c, d, x[8], 6, 1873313359); d = ii(d, a, bb, c, x[15], 10, -30611744);
      c = ii(c, d, a, bb, x[6], 15, -1560198380); bb = ii(bb, c, d, a, x[13], 21, 1309151649);
      a = ii(a, bb, c, d, x[4], 6, -145523070); d = ii(d, a, bb, c, x[11], 10, -1120210379);
      c = ii(c, d, a, bb, x[2], 15, 718787259); bb = ii(bb, c, d, a, x[9], 21, -343485551);
      a0 = au(a0, a); b0 = au(b0, bb); c0 = au(c0, c); d0 = au(d0, d);
    }
    function le(n) {
      var s = "";
      for (var i = 0; i < 4; i++) s += ((n >>> (8 * i)) & 0xFF).toString(16).padStart(2, "0");
      return s;
    }
    return le(a0) + le(b0) + le(c0) + le(d0);
  }

  function cvxQmid(rawA, rawB) {
    var u = 0, v = 0, i = 31;
    var n4 = rawA >>> 0, n5 = rawB >>> 0;
    while (i > 0 && (n5 & 0x80000000) === 0) {
      n5 = (((n5 << 2) >>> 0) + ((n4 & 0xC0000000) >>> 30)) >>> 0;
      n4 = Math.imul(n4, 4) >>> 0;
      i -= 1;
    }
    n5 = n5 & 0x7FFFFFFF;
    var level = i;
    while (i >= 0) {
      if (n5 & 0x80000000) v += 1 << i;
      if (n5 & 0x40000000) u += 1 << i;
      n5 = (n5 << 2) >>> 0;
      i -= 1;
    }
    var n = Math.pow(2, level), lonSpan = 480.0 / n, latSpan = 360.0 / n;
    var minLon = -180.0 + u * lonSpan, maxLat = 90.0 - v * latSpan;
    return { level: level, u: u, v: v, minLon: minLon, maxLon: minLon + lonSpan,
      minLat: maxLat - latSpan, maxLat: maxLat };
  }

  /* 与 Python repr(float) 等价的字符串（属性值用 repr，10.0 不能写成 10） */
  function pyFloatRepr(x) {
    if (x !== x) return "nan";
    if (x === Infinity) return "inf";
    if (x === -Infinity) return "-inf";
    var s = String(x), neg = s.charAt(0) === "-";
    if (neg) s = s.slice(1);
    var mant = s, exp10 = 0, ei = s.indexOf("e");
    if (ei >= 0) { mant = s.slice(0, ei); exp10 = parseInt(s.slice(ei + 1), 10); }
    var dot = mant.indexOf(".");
    var intPart = dot < 0 ? mant : mant.slice(0, dot);
    var fracPart = dot < 0 ? "" : mant.slice(dot + 1);
    var all = intPart + fracPart, digits = all.replace(/^0+/, "");
    if (!digits) return neg ? "-0.0" : "0.0";
    var pos = intPart.length + exp10 - (all.length - digits.length);
    while (digits.length > 1 && digits.charAt(digits.length - 1) === "0")
      digits = digits.slice(0, -1);
    var exp = pos - 1, out;
    if (exp < -4 || exp >= 16) {
      out = digits.charAt(0) + (digits.length > 1 ? "." + digits.slice(1) : "") +
        "e" + (exp < 0 ? "-" : "+") + ("0" + Math.abs(exp)).slice(-2);
    } else if (pos <= 0) {
      out = "0." + new Array(1 - pos + 1).join("0") + digits;
    } else if (pos >= digits.length) {
      out = digits + new Array(pos - digits.length + 1).join("0") + ".0";
    } else {
      out = digits.slice(0, pos) + "." + digits.slice(pos);
    }
    return (neg ? "-" : "") + out;
  }

  function cvxAttrValue(gu, raw) {
    var meta = CVX_ATTR[gu];
    if (!meta) return null;
    var vt = meta[0], val;
    if (vt === "byte") val = raw.length ? String(raw[0]) : "";
    else if (vt === "uint") val = raw.length >= 4 ? String(u32(raw, 0)) : "";
    else if (vt === "float") val = raw.length >= 4 ? pyFloatRepr(f32(raw, 0)) : "";
    else if (vt === "Guid") val = raw.length >= 16 ? guid(raw.subarray(0, 16)) : null;
    else if (vt === "string") val = cstr(raw, 0);
    else if (vt === "bytes") val = raw.length ? Array.prototype.map.call(raw, function (x) {
      return ("0" + x.toString(16)).slice(-2); }).join("") : "";
    else val = null;
    return { value: val, fstype: meta[1], name: meta[2] };
  }

  function cvxAttrs(buf) {
    var out = {}, i = 0;
    while (i + 20 <= buf.length) {
      var gd = guid(buf.subarray(i, i + 16));
      var size = i32(buf, i + 16);
      if (size < 0 || i + 20 + size > buf.length) break;
      var raw = buf.subarray(i + 20, i + 20 + size);
      var dec = cvxAttrValue(gd.replace(/[{}]/g, "").toUpperCase(), raw);
      out[i] = { guid: gd, gu: gd.replace(/[{}]/g, "").toUpperCase(), raw: raw, off: i,
        name: dec ? dec.name : null, fstype: dec ? dec.fstype : "UNKNOWN",
        value: dec ? dec.value : null };
      i += 20 + size;
    }
    return out;
  }

  /* 位打包点解码（与对照解析程序逐位等价） */
  function cvxMethod2(data, pointCt) {
    var arr = new Array(2 * pointCt);
    for (var z = 0; z < arr.length; z++) arr[z] = 0;
    if (pointCt === 0) return { arr: arr, size: 0 };
    var pos = 0, b = data[0];
    pos = 1;
    var i2 = 0, i3 = 0, i4 = 0;
    var num5 = (b * pointCt * 2 + 7) >> 3;
    var num6 = (1 << b) - 1;
    var dataSize = num5 + 1;
    if (num5) {
      var word;
      if (num5 >= 4) { word = u32(data, pos); num5 -= 4; pos += 4; }
      else {
        var chunk = data.subarray(pos, pos + num5), pad = new Uint8Array(4);
        pad.set(chunk);
        word = u32(pad, 0); num5 = 0; pos = data.length;
      }
      while (i3 < pointCt) {
        if (i4 < 0) arr[i3 * 2 + i2] += (word << (-i4)) & num6;
        else arr[i3 * 2 + i2] = (word >>> i4) & num6;
        if (b + i4 >= 32) {
          if (num5 >= 4) { word = u32(data, pos); num5 -= 4; pos += 4; }
          else {
            var ch2 = data.subarray(pos, pos + num5), pad2 = new Uint8Array(4);
            pad2.set(ch2);
            word = u32(pad2, 0); num5 = 0; pos += ch2.length;
          }
          i4 -= 32;
        } else {
          i4 += b; i2 += 1;
          if (i2 === 2) { i3 += 1; i2 = 0; }
        }
      }
    }
    return { arr: arr, size: dataSize };
  }

  function cvxSegment(data, ver, qmid) {
    if (data.length < 6) return { pts: [], size: 0, ext: false };
    var pointCt, altRaw, method, pos;
    if (ver === 7) {
      if (data.length < 10) return { pts: [], size: 0, ext: false };
      pointCt = u32(data, 4); altRaw = data[8]; method = data[9]; pos = 10;
    } else {
      pointCt = u32(data, 0); altRaw = data[4]; method = data[5]; pos = 6;
    }
    var altType;
    if (altRaw === 1) altType = "D";
    else if (altRaw === 2 && ver === 6) altType = "S";
    else if (altRaw === 4 && ver === 7) altType = "S";
    else if (altRaw === 0) altType = "N";
    else return { pts: [], size: 0, ext: false };
    var rawPts = [], size = 0, ext = false;
    if (method === 0) {
      size = 8 * pointCt;
      for (var i = 0; i + 8 <= data.length && i < size; i += 8) {
        rawPts.push(u32(data, i)); rawPts.push(u32(data, i + 4));
      }
    } else if (method === 2) {
      var m2 = cvxMethod2(data.subarray(pos), pointCt);
      rawPts = m2.arr; size = m2.size;
    } else if (method === 1) {
      ext = true;
      var pay = (pointCt && data.length >= 26) ? u32(data, 22) : 0;
      size = pointCt ? pay + 20 : 0;
      var p1 = 6 + size + (altType === "D" ? 4 * pointCt : (altType === "S" ? 4 : 0));
      return { pts: [], size: p1, ext: true };
    } else {
      return { pts: [], size: 0, ext: false };
    }
    pos += size;
    var alts = [];
    if (altType === "D") {
      for (var k = 0; k < pointCt; k++) {
        if (pos + 4 > data.length) break;
        alts.push(f32(data, pos)); pos += 4;
      }
    } else if (altType === "S") {
      if (pos + 4 <= data.length) { alts.push(f32(data, pos)); pos += 4; }
    }
    var rec = pos;
    if (rawPts.length % 2) return { pts: [], size: rec, ext: ext };
    var lonS = (qmid.maxLon - qmid.minLon) / 32768.0, latS = (qmid.maxLat - qmid.minLat) / 32768.0;
    var pts = [], ai = 0;
    for (var j = 0; j < rawPts.length; j += 2) {
      var lon = qmid.minLon + lonS * rawPts[j], lat = qmid.minLat + latS * rawPts[j + 1];
      var alt = null;
      if (alts.length) {
        if (ai >= alts.length) return { pts: [], size: rec, ext: ext };
        alt = alts[ai];
        if (alts.length > 1) ai += 1;
      }
      pts.push([lon, lat, alt]);
    }
    return { pts: pts, size: rec, ext: ext };
  }

  function cvxEntities(blob, baseOff, rep) {
    var out = [];
    if (blob.length < 32) return out;
    var ver = u32(blob, 0);
    if (ver !== 6 && ver !== 7) { rep.unknown.push("CVX 版本 " + ver + " 不支持"); return out; }
    var qmid = cvxQmid(u32(blob, 4), u32(blob, 8));
    var entCt = u32(blob, 12), attrSz = u32(blob, 16);
    var pos = ver === 6 ? 32 : 24;
    var attrs = cvxAttrs(blob.subarray(pos, pos + attrSz));
    pos += attrSz;
    for (var e = 0; e < entCt; e++) {
      if (pos + 10 > blob.length) break;
      var segCt = u32(blob, pos), disp = u32(blob, pos + 4), act = u16(blob, pos + 8);
      var epos = pos + 10 + 4 * act;
      if (epos > blob.length) break;
      var alist = [];
      for (var k = 0; k < act; k++) {
        var a = attrs[u32(blob, pos + 10 + 4 * k)];
        if (a) alist.push(a);
      }
      var segs = [];
      for (var s = 0; s < segCt; s++) {
        if (epos + 6 > blob.length) { segs = []; break; }
        var sg = cvxSegment(blob.subarray(epos), ver, qmid);
        if (sg.size <= 0) break;
        if (sg.ext) rep.counts.cvx_ext_segment++;
        segs.push(sg.pts);
        epos += sg.size;
      }
      var sz = epos - pos;
      if (sz <= 0) break;
      if (!CVX_DISPLAY[disp]) rep.unknown.push("CVX 显示方式 " + disp);
      out.push({ type: CVX_DISPLAY[disp] || "Unknown", attrs: alist, segments: segs,
        off: baseOff + pos, size: sz });
      pos += sz;
    }
    return out;
  }

  function cvxSynthGuid(seed) {
    var h = md5Hex(String(seed));
    var d1 = (parseInt(h.substr(6, 2) + h.substr(4, 2) + h.substr(2, 2) + h.substr(0, 2), 16)) >>> 0;
    var d2 = parseInt(h.substr(10, 2) + h.substr(8, 2), 16);
    var d3 = (parseInt(h.substr(14, 2) + h.substr(12, 2), 16) & 0x0FFF) | 0x4000;
    var p = function (v, w) { var t = v.toString(16).toUpperCase(); while (t.length < w) t = "0" + t; return t; };
    return "{" + p(d1, 8) + "-" + p(d2, 4) + "-" + p(d3, 4) + "-" +
      h.substr(16, 4).toUpperCase() + "-" + h.substr(20, 12).toUpperCase() + "}";
  }

  function cvxMatch(a, b) { return Math.abs(a[0] - b[0]) < CVX_TOL && Math.abs(a[1] - b[1]) < CVX_TOL; }

  function cvxPolyPoints(ent) {
    if (!ent.segments.length) return [];
    var pts = ent.segments[0].map(function (p) { return [p[0], p[1]]; });
    if (pts.length > 1 && Math.abs(pts[0][0] - pts[pts.length - 1][0]) < CVX_TOL &&
        Math.abs(pts[0][1] - pts[pts.length - 1][1]) < CVX_TOL) pts = pts.slice(0, -1);
    return pts;
  }

  function cvxAngleSort(points) {
    if (!points.length) return [];
    var cx = 0, cy = 0, i;
    for (i = 0; i < points.length; i++) { cx += points[i][0]; cy += points[i][1]; }
    cx /= points.length; cy /= points.length;
    return points.slice().sort(function (a, b) {
      return Math.atan2(a[1] - cy, a[0] - cx) - Math.atan2(b[1] - cy, b[0] - cx);
    });
  }

  function cvxMergePair(pa, pb) {
    var shared = [], i, j;
    for (i = 0; i < pa.length; i++)
      for (j = 0; j < pb.length; j++)
        if (cvxMatch(pa[i], pb[j])) shared.push(pa[i]);
    if (shared.length < 2) return null;
    var merged = [], all = pa.concat(pb);
    for (i = 0; i < all.length; i++) {
      var p = all[i], skip = false;
      for (j = 0; j < shared.length; j++) if (cvxMatch(p, shared[j])) { skip = true; break; }
      if (skip) continue;
      for (j = 0; j < merged.length; j++) if (cvxMatch(p, merged[j])) { skip = true; break; }
      if (!skip) merged.push(p);
    }
    return cvxAngleSort(merged);
  }

  function cvxAttrsSorted(ent) {
    var list = ent.attrs.slice().sort(function (a, b) { return a.off - b.off; }), out = [];
    for (var i = 0; i < list.length; i++) {
      var a = list[i];
      if (a.gu === CVX_G_VERSION) continue;
      if (CVX_NON_ATTR.indexOf(a.gu) >= 0) continue;
      if (a.name) out.push(a);
    }
    return out;
  }

  function cvxAttrXml(a) {
    return '\n\t\t<Attribute name="' + xesc(a.name) + '" guid="' + a.guid + '" type="' +
      xesc(a.fstype) + '" value="' + xesc(a.value) + '"/>';
  }

  function cvxPolygonSingle(ent, uniq, pg, gi) {
    var head = "", i;
    for (i = 0; i < ent.attrs.length; i++) {
      var v = ent.attrs[i];
      if (!IS2020 && v.gu === CVX_G_VERSION && v.value && String(v.value).indexOf("0.4") === 0) {
        head += ' version="' + xesc(v.value) + '"'; break;
      }
    }
    var pts = ent.segments.length ? ent.segments[0] : [];
    var body = (pts.length && pts[0][2] !== null) ? ' altitude="' + f(pts[0][2], 14) + '"' : "";
    var out = '\n\t<Polygon' + head + ' parentGroupID="' + pg + '" groupIndex="' + gi + '"' + body + '>';
    out += '\n\t\t<Attribute name="UniqueGUID" guid="{' + CVX_G_BOUNDS + '}" type="GUID" value="' + uniq + '"/>';
    var at = cvxAttrsSorted(ent);
    for (i = 0; i < at.length; i++) out += cvxAttrXml(at[i]);
    var pl = pts.map(function (p) { return [p[0], p[1]]; });
    if (pl.length > 1 && Math.abs(pl[0][0] - pl[pl.length - 1][0]) < 1e-09 &&
        Math.abs(pl[0][1] - pl[pl.length - 1][1]) < 1e-09) pl = pl.slice(0, -1);
    for (i = 0; i < pl.length; i++)
      out += '\n\t\t<Vertex lat="' + f(pl[i][1], 14) + '" lon="' + f(pl[i][0], 14) + '"/>';
    return out + "\n\t</Polygon>";
  }

  function cvxPolygonMerged(points, pg, gi, uniq, ent) {
    var head = "", i;
    if (ent) {
      for (i = 0; i < ent.attrs.length; i++) {
        var v = ent.attrs[i];
        if (!IS2020 && v.gu === CVX_G_VERSION && v.value && String(v.value).indexOf("0.4") === 0)
          head += ' version="' + xesc(v.value) + '"';
      }
      var seg = ent.segments.length ? ent.segments[0] : [];
      if (seg.length && seg[0][2] !== null) head += ' altitude="' + f(seg[0][2], 14) + '"';
    }
    var out = '\n\t<Polygon' + head + ' parentGroupID="' + pg + '" groupIndex="' + gi + '">';
    out += '\n\t\t<Attribute name="UniqueGUID" guid="{' + CVX_G_BOUNDS + '}" type="GUID" value="' + uniq + '"/>';
    if (ent) {
      var at = cvxAttrsSorted(ent);
      for (i = 0; i < at.length; i++) out += cvxAttrXml(at[i]);
    }
    for (i = 0; i < points.length; i++)
      out += '\n\t\t<Vertex lat="' + f(points[i][1], 14) + '" lon="' + f(points[i][0], 14) + '"/>';
    return out + "\n\t</Polygon>";
  }

  function cvxRectangle(ent, pg, gi) {
    if (!ent.segments.length || ent.segments[0].length < 2) return "";
    var width = null, falloff = null, surface = null, precision = true,
        flattenData = null, layer = 0, hmRaw = null, forceElev = false;
    for (var i = 0; i < ent.attrs.length; i++) {
      var a = ent.attrs[i], g = a.gu, raw = a.raw;
      if (g === CVX_G_WIDTH && raw.length === 4) width = f32(raw, 0);
      else if (g === CVX_G_FALLOFF && a.value) falloff = parseFloat(a.value);
      else if (g === CVX_G_TEXTURE && a.value) surface = a.value;
      else if (g === CVX_G_PRECISION && raw.length) precision = raw[0] !== 0;
      else if (g === CVX_G_FLATTEN_DATA && raw.length) flattenData = raw;
      else if (g === CVX_G_LAYER && raw.length >= 4) layer = u32(raw, 0);
      else if (g === CVX_G_HEIGHTMAP && raw.length) hmRaw = raw;
      else if (g === CVX_G_FORCE_ELEV && raw.length) forceElev = raw[0] !== 0;
    }
    var p0 = ent.segments[0][0], p1 = ent.segments[0][1];
    var out = '\n\t<Rectangle parentGroupID="' + pg + '" groupIndex="' + gi +
      '" width="' + f(width === null ? 0 : width, 6) + '" falloff="' + f(falloff === null ? 0 : falloff, 6) + '"' +
      (surface ? ' surface="' + xesc(surface) + '"' : "") + ' priority="' + layer + '" precision="' +
      (precision ? "TRUE" : "FALSE") + '"' + ((forceElev && !IS2020) ? ' forceElevation="TRUE"' : "");
    out += ' latitude="' + f(p0[1], 14) + '" longitude="' + f(p0[0], 14) + '" altitude="' +
      f(p0[2] === null ? 0 : p0[2], 14) + '"';
    out += ' latitude2="' + f(p1[1], 14) + '" longitude2="' + f(p1[0], 14) + '" altitude2="' +
      f(p1[2] === null ? 0 : p1[2], 14) + '"';
    var kids = "";
    if (flattenData) {
      for (var o = 0; o + 16 <= flattenData.length; o += 16) {
        var alt = f32(flattenData, o), ratio = f32(flattenData, o + 4),
            cpb = f32(flattenData, o + 8), cpa = f32(flattenData, o + 12);
        kids += '\n\t\t<RunwayDeformation alt="' + f6(alt) + '" ratio="' + f6(ratio) + '"';
        if (ratio !== 0.0 && ratio !== 1.0) {
          if (cpb === cpb) kids += ' controlPointBefore="' + f(cpb, 6) + '"';
          if (cpa === cpa) kids += ' controlPointAfter="' + f(cpa, 6) + '"';
        }
        kids += "/>";
      }
    }
    if (hmRaw && hmRaw.length >= 12) {
      var hmW = u16(hmRaw, 0), hmH = u16(hmRaw, 2), hmMin = f32(hmRaw, 4), hmMax = f32(hmRaw, 8);
      var scale = (hmMax - hmMin) / 32768.0, vals = [];
      var cnt = Math.min(hmW * hmH, Math.floor((hmRaw.length - 12) / 2));
      for (var q = 0; q < cnt; q++) vals.push(f(hmMin + u16(hmRaw, 12 + q * 2) * scale, 6));
      if (vals.length) kids += '\n\t\t<Heightmap width="' + hmW + '" data="' + vals.join(" ") + '"/>';
    }
    if (!kids) return out + "/>";
    return out + ">" + kids + "\n\t</Rectangle>";
  }

  function cvxElements(g, rep) {
    var ents = [];
    g.dataOf(0x65).forEach(function (pair) {
      ents = ents.concat(cvxEntities(pair[0], pair[1].off, rep));
    });
    var polyEnts = [], rects = [], i;
    for (i = 0; i < ents.length; i++) {
      var e = ents[i];
      if (!e.segments.length || !e.segments[0].length) continue;
      var gids = e.attrs.map(function (a) { return a.gu; });
      var pg = gids.indexOf(CVX_G_FLATTEN) >= 0 ? 7 : 2;
      if (e.type === "Polygon") polyEnts.push([e, pg]);
      else if (e.type === "Lines" && e.segments[0].length === 2)
        rects.push(cvxRectangle(e, pg, rects.length + 1));
    }
    var polys = [], used = {};
    for (i = 0; i < polyEnts.length; i++) {
      if (used[i]) continue;
      used[i] = 1;
      var entI = polyEnts[i][0], pgI = polyEnts[i][1];
      var merged = cvxPolyPoints(entI), changed = true;
      while (changed) {
        changed = false;
        for (var j = 0; j < polyEnts.length; j++) {
          if (used[j] || polyEnts[j][1] !== pgI) continue;
          var m = cvxMergePair(merged, cvxPolyPoints(polyEnts[j][0]));
          if (!m) continue;
          merged = m; used[j] = 1; changed = true;
        }
      }
      var gi = polys.length + 1, uniq = cvxSynthGuid(entI.off);
      /* 对照解析程序此处用的是「已用实体总数」，第二个多边形起恒为合并路径 */
      if (Object.keys(used).length > 1) polys.push([pgI, cvxPolygonMerged(merged, pgI, gi, uniq, entI)]);
      else polys.push([pgI, cvxPolygonSingle(entI, uniq, pgI, gi)]);
    }
    polys.sort(function (a, b) { return a[0] - b[0]; });
    rep.counts.cvx_polygon = (rep.counts.cvx_polygon || 0) + polys.length;
    var good = rects.filter(function (r) { return r; });
    rep.counts.cvx_rectangle = (rep.counts.cvx_rectangle || 0) + good.length;
    return polys.map(function (p) { return p[1]; }).concat(good);
  }

  var CVX_DISPLAY = { 0: "None", 1: "PointsOnly", 2: "Lines", 3: "Polygon" };

  /* ======================= 分组（Group / parentGroupID / groupIndex） ======================= */
  var GROUP_DISPLAY = { 1: "Buildings", 2: "Exclusion", 3: "Lights", 4: "Other Models", 5: "ParkingSigns", 6: "Static Jetways", 7: "Terrain" };
  var DEFAULT_GROUP = 4;
  var GUID_TO_GROUP = {};
  (function () {
    var tbl = {
      1: "491E6BE8-25E5-4DC3-8FAF-DEFA14404131 7E5C0613-61EA-4CFD-9537-76C7572BE5E9",
      3: "0458C636-D8D2-4860-AB9C-C6E4F3B0EE75 163C942C-189A-4380-8B03-FDEE4ABC525B 25486B7C-2448-4BA3-ADEC-5306C24D3933 470F9B8F-4572-4F10-A3B3-6AB2C278ED03 8CCCA24B-825F-402D-8D62-AF62D35DB4F4 8EF4C350-65F3-455B-AF52-64511D7F9510 AEAFBBC0-0436-401C-96DE-384B435FF8A7 C233E165-298F-4606-97AB-4F22DD8EB1B2 D8F767C2-C20E-4F56-FC9C-0B735CC345F7 DB0162E7-91A2-46E9-81B7-55A66CEC8839 F3A90285-66E3-4BE7-998F-FDB9CE2091AB",
      4: "580D226E-2F7B-4634-9B62-F5163D53259A",
      5: "00B2409E-5191-4CDB-9CAC-2AEF86610F17 0221F79A-A6F0-4D12-830D-703166668B89 06B4607F-D089-45B2-B2BC-C1CAF1B3AA18 0CFB4EE7-F3FC-4EBD-960C-BC3BB0F99B87 0D36BF7A-5698-4A48-BCB3-5DDD53904999 10925290-FD71-4E17-A3E5-3DE0E22E32D2 129D1D7E-F668-458E-9E77-01C43E1D3337 142B3D7D-C33D-4713-9B6C-37663B66FA4D 16739808-7DD6-4429-82B2-E72A27557531 17E0D6F5-47E3-4C83-8CE6-3AE4385C2486 1881ACE9-C886-4304-BD82-E27AABF94285 1AA606E0-8471-42AD-BC1D-EED0937FF08B 1C241AA1-9979-492E-B478-86CAFA4C11DC 1CF1E705-0FF7-4F18-8E1A-A1F12CD15EA9 2079007E-C359-4FF6-9D29-F27BEB48849A 2ABAA5E8-5960-421C-8C65-D06B421F65E7 2FC0439E-85BF-4053-B1F2-910D67DBAD08 35134FF7-96F7-4D79-BFBE-9531FA1DB5CD 385691E4-F6AD-41DA-BBB7-DD1BD77C9DF1 38FC15A2-86BF-4FF0-8B4B-45D961A80407 3F24B66D-1000-4273-8199-E4BB19A4C237 401C107E-8AD6-48EF-BDB7-4B7C9CCAEB57 461BBB04-C332-4739-ACB0-ACB324FAB58D 4D085A96-39AD-415A-A47F-FA3F886A148D 4D2295A0-5AC0-45D2-9629-14BE4F73478F 50941EF6-AC34-41A9-8CF8-AE42410D0BA1 512536DF-628F-4E8D-9F90-434C65989A78 51A7DAC7-6CCF-4C70-92DB-80EB441AD6DF 51E9C5C0-3F91-4CF6-857A-4B79757CC677 521E2E9E-12F5-4161-B9CA-62F71B04C83B 5AD54249-AE61-41C9-91CB-6A1E65598473 5C0C733F-A692-4D05-B6CE-7F18D4F58088 5CF7B9EF-CFED-4E74-B63C-B416944FD2FB 61634292-13E6-4720-AE76-8B5342437DB2 66138E0B-673E-4908-9C34-21D59ABD0D8F 6D35B8EF-1D49-40E4-B00A-00DF80E7EF7F 6DFE0132-B63F-4278-8744-C218A92FCCD2 70CE6D33-A787-486B-8B22-9BFF76951108 713E7332-67E0-4524-BD5E-DC0A7E3EDB15 7147B2A9-B275-4A3B-92F7-98F9C29F2113 72CB3575-DB3B-4E93-A36D-7A3D82D57D13 73F4E3D8-5D70-470E-BD54-393C56BB2D30 7D52FB16-DF28-4706-84C7-DB071AF45EDE 8040F27F-4247-47A6-86AD-60CEF6E50AC7 82417EBB-EBBF-4384-AD92-9EA909C58AD7 84F7FA9F-BB2F-401C-AC79-71EE03678BF0 88C92697-DC9D-4CBD-B25D-698FC01B8D96 90E21025-83C8-4CF7-9E6B-108603398A43 91183B97-231E-4CA0-AA7E-B0C865999E21 9825E2CE-D3D4-4EC2-8D3A-6229A50EEFAF 99D63003-E93B-4966-AE7C-B05C39350C78 9BE27D74-A0F4-4BB3-991F-794CFFAE6134 9DC242ED-B303-4896-B103-5A94AA9FFBA0 A477DB0D-DD11-4200-8658-6C846C892862 ABB0A713-7A59-4192-91D8-BB929159FD8B AEDA1335-7388-4BAD-A66A-0ED674007E2D B34245C3-CDFC-4956-8707-9852D1272E96 B4C0ABE3-4AF3-4E12-A638-8986B9A9EFCA B5784522-2CCC-48FB-89F0-1F110091321E B65B486A-BB85-4F5F-B37E-058AA9D91582 C55F5310-05E5-46AF-868F-35BE47A56702 C57B04EB-ED39-4222-94C3-D0EAB3AEAF39 CB510ACC-6AD3-4905-AF0D-369D9185D9E0 CE981420-7AB9-414E-90F0-A1462D607719 D3007B5D-D095-4056-A2C1-C54FB0A337DB D5C0935A-E320-4CC2-9442-32E8B384716C D654A19D-AFA3-4233-A071-8C539A59C5E5 D69D7878-E2F1-493F-8F50-BFC53F25FFD5 D6FE7602-643F-43CF-89AE-EC19A8688950 DA00E7DD-BB18-4D87-9814-D310E58E08EB DA4C8D61-0C2F-46D9-B5B9-B29A75165787 E0A5E1FC-5F14-40AE-82CF-600995310722 E126A049-B0B1-40B4-AD61-A01BBBE5F6D4 E4E6D353-526B-4039-937C-B8B14B91D468 EA9F0DA2-DB78-489C-9265-381A41BB26A3 EB282665-8943-4060-A944-50C85CEBEFFC EB2E40C7-AD80-43D6-A852-27897F9234C5 EB68143B-9F11-42E0-B7F2-BB85C3EBB154 ED64D5A6-3F4C-4038-91A0-E88CA6D172A8 EDED2F0D-96AF-41DC-A130-256456F73F66 F2ABF2F9-58D4-4666-9F4B-86FA6BE9424F F4A1438C-0BA8-4556-8F19-578C2B640040 F9963317-667F-4E3B-B860-A668A4CA9AAA FA556B45-F108-458D-A5E5-CFD4F2844159 FF06B5A1-612C-4144-8A04-BAE58DD00609",
      6: "2F6B0ED1-5A59-4DEA-92FF-5909A95F9D76 31528024-3011-4C43-A8B6-4713BA8C633A 40942401-3BF4-4D47-8F12-554A91EFD0BD",
    };
    Object.keys(tbl).forEach(function (k) {
      tbl[k].split(" ").forEach(function (g) { GUID_TO_GROUP["{" + g + "}"] = parseInt(k, 10); });
    });
  })();
  var AIRPORT_SUB_GROUPS = ["Runway", "RunwayMarkings", "PaintedMarkings", "GroundBase", "Centerlines", "Taxiways", "Parkings", "Taxipaths", "Edgelines", "Runway Alarm Lights", "Centerlights", "Edgelights", "TaxiSigns"];
  var AIRPORT_SUB_PARENTS = { "Runway": null, "RunwayMarkings": "Runway", "PaintedMarkings": null, "GroundBase": null, "Centerlines": "Taxiways", "Taxiways": null, "Parkings": null, "Taxipaths": "Taxiways", "Edgelines": "Taxiways", "Runway Alarm Lights": "Taxiways", "Centerlights": "Taxiways", "Edgelights": "Taxiways", "TaxiSigns": "Taxiways" };
  var AIRPORT_GROUP_ID = 8;          // 7 个景物顶层组（1..7）之后，机场节点固定为 8
  var AIRPORT_GROUP_INDEX = 7;       // 机场在根分组序号里的编号
  var AIRPORT_LEVEL_GROUPS = 7;      // FSData 层景物顶层组数量（groupID 1..7）
  var SUB_GID = {};
  AIRPORT_SUB_GROUPS.forEach(function (n, i) { SUB_GID[n] = AIRPORT_GROUP_ID + i + 1; });
  var DEFAULT_SCENERY_GROUP = 4;
  var SURF_CENTERLINE = "{A789C134-4487-43CB-8981-BAF5FCA23981}";
  var SURF_EDGELINE_SOLID = "{4EBBBBB6-08A3-4009-BD38-1BA096B75D45}";
  var SURF_RUNWAY_LINE = "{DAEEABDD-69FC-4E8E-A693-BA2E332533D1}";
  var SURF_RUNWAY_MARKINGS = "{06C65325-BD2E-41F8-A062-710DC32E42E4}";
  var GROUND_GID = 2;                // CVX 多边形/矩形默认所在组

  function groupElementsXml(indent) {
    indent = indent || "\t";
    var out = [];
    for (var gi = 1; gi <= AIRPORT_LEVEL_GROUPS; gi++) {
      out.push(indent + '<Group displayName="' + GROUP_DISPLAY[gi] + '" groupID="' + gi +
        '" groupGenerated="FALSE"/>');
    }
    return out;
  }
  function airportSubGroupXml() {
    var out = [];
    AIRPORT_SUB_GROUPS.forEach(function (name) {
      var parent = AIRPORT_SUB_PARENTS[name];
      var pid = (parent === null || parent === undefined) ? AIRPORT_GROUP_ID : SUB_GID[parent];
      out.push('\t\t<Group displayName="' + name + '" parentGroupID="' + pid +
        '" groupID="' + SUB_GID[name] + '" groupGenerated="FALSE"/>');
    });
    return out;
  }
  function tagName(s) {
    var p = s.indexOf("<");
    if (p < 0) return "";
    var q = s.indexOf(" ", p), r = s.indexOf(">", p);
    var end = Math.min(q < 0 ? r : q, r < 0 ? q : r);
    return end > 0 ? s.slice(p + 1, end) : "";
  }
  function nodeTag(s) { return tagName(s); }
  var ATTR_RE = /([A-Za-z_][\w.]*)\s*=\s*"([^"]*)"/g;
  function nodeAttrs(s) {
    var p = s.indexOf("<");
    if (p < 0) return {};
    var q = s.indexOf(">", p);
    var head = s.slice(p, q > 0 ? q : s.length), out = {}, m;
    ATTR_RE.lastIndex = 0;
    while ((m = ATTR_RE.exec(head)) !== null) out[m[1]] = m[2];
    return out;
  }
  function classifyApron(a) {
    var luv = (a.localUV === undefined || a.localUV === null) ? "FALSE" : a.localUV;
    if (String(luv).toUpperCase() !== "TRUE") return "GroundBase";
    if (a.priority === "1000000012") return "RunwayMarkings";
    if (a.surface === SURF_RUNWAY_MARKINGS) return "RunwayMarkings";
    return "PaintedMarkings";
  }
  // 机场子元素 → 分组（顺序与对照输出一致）
  var GROUP_OF_TAG = {
    "Runway": function () { return "Runway"; },
    "LightSupport": function () { return "Runway"; },
    "TaxiwayPoint": function () { return "Taxipaths"; },
    "TaxiwayPath": function () { return "Taxipaths"; },
    "TaxiwayParking": function () { return "Parkings"; },
    "TaxiwaySign": function () { return "TaxiSigns"; },
    "PaintedHatchedArea": function () { return "PaintedMarkings"; },
    "PaintedPolygon": function () { return "PaintedMarkings"; },
    "Apron": classifyApron,
    "PaintedLine": function (a) {
      return classifyPaintedLine(a.type, a.trueAngle, a.surface);
    },
    "EdgeLights": function (a) { return classifyEdgeLights(a.preset); }
  };
  var GROUP_OF_ORDER = ["Runway", "LightSupport", "TaxiwayPoint", "TaxiwayPath", "TaxiwayParking",
    "TaxiwaySign", "PaintedHatchedArea", "PaintedPolygon", "Apron", "PaintedLine", "EdgeLights"];
  function injectGroup(s, gid, idx) {
    var p = s.indexOf(" ");
    if (p < 0 || s.indexOf("parentGroupID") >= 0 && s.indexOf("parentGroupID") < p + 2) return s;
    return s.slice(0, p) + ' parentGroupID="' + gid + '" groupIndex="' + idx + '"' + s.slice(p);
  }
  /* 顶层景物对象按其 LibraryObject GUID 归入 7 个顶层组；未知 GUID 归 Other Models(4) */
  function assignSceneryGroups(objs) {
    var counters = {};
    for (var i = 0; i < objs.length; i++) {
      var s = objs[i];
      if (!s || nodeTag(s) !== "SceneryObject") continue;
      var p = s.indexOf("<LibraryObject");
      var gname = p >= 0 ? nodeAttrs(s.slice(p)).name : null;
      var gid = GUID_TO_GROUP[gname || ""] || DEFAULT_SCENERY_GROUP;
      counters[gid] = (counters[gid] || 0) + 1;
      objs[i] = injectGroup(s, gid, counters[gid]);
    }
    return counters;
  }
  /* 机场子元素分组：按 GROUP_OF_ORDER 的集合顺序补 parentGroupID / groupIndex；
     TaxiwayPoint 与 TaxiwayPath 共用 Taxipaths 的序号 */
  function assignAirportGroups(lists, counters) {
    counters = counters || {};
    function put(lst, i, s, gname) {
      counters[gname] = (counters[gname] || 0) + 1;
      lst[i] = injectGroup(s, SUB_GID[gname], counters[gname]);
    }
    GROUP_OF_ORDER.forEach(function (tag) {
      var pick = GROUP_OF_TAG[tag];
      lists.forEach(function (lst) {
        for (var i = 0; i < lst.length; i++) {
          var s = lst[i];
          if (!s || s.indexOf("parentGroupID") >= 0 || nodeTag(s) !== tag) continue;
          put(lst, i, s, pick(nodeAttrs(s)));
        }
      });
    });
    // ProjectedMesh 不进子组，直接挂在机场组（groupID=8）下单独计数
    lists.forEach(function (lst) {
      for (var i = 0; i < lst.length; i++) {
        var s = lst[i];
        if (!s || s.indexOf("parentGroupID") >= 0 || nodeTag(s) !== "ProjectedMesh") continue;
        counters["__airport__"] = (counters["__airport__"] || 0) + 1;
        lst[i] = injectGroup(s, AIRPORT_GROUP_ID, counters["__airport__"]);
      }
    });
    return counters;
  }
  function tf(v) { return v ? "TRUE" : "FALSE"; }

  /* 机场头 +48 的 u32 燃油位图：每个油品占 2 位（bit[2i]=flag、bit[2i+1]=flag2） */
  var FUEL_TYPES = ["73", "87", "100", "130", "145", "MOGAS", "JET", "JETA", "JETA1",
    "JETAP", "JETB", "JET4", "JET5", "UNKNOWN"];
  function servicesElements(mask) {
    var out = ['\t\t<Services>'];
    for (var i = 0; i < FUEL_TYPES.length; i++) {
      var flag = Math.floor(mask / Math.pow(2, 2 * i)) % 2 ? 1 : 0;
      var flag2 = Math.floor(mask / Math.pow(2, 2 * i + 1)) % 2 ? 1 : 0;
      var avail = (flag && flag2) ? "YES" : (flag2 ? "PRIOR_REQUEST" : (flag ? "UNKNOWN" : "NO"));
      out.push('\t\t\t<Fuel type="' + FUEL_TYPES[i] + '" availability="' + avail + '"/>');
    }
    out.push('\t\t</Services>');
    return out;
  }

  /* 景物对象分组：库对象按 GUID 查表，SimObject/风向袋落在默认组 4 */
  function objGroupAttrs(rec, rid, sz, counts) {
    var gid = DEFAULT_GROUP;
    if (rid !== 0x19 && !(rid === 0x18 || sz > 92)) {
      gid = GUID_TO_GROUP[guid(rec.subarray(44, 60))] || DEFAULT_GROUP;
    }
    counts[gid] = (counts[gid] || 0) + 1;
    return 'parentGroupID="' + gid + '" groupIndex="' + counts[gid] + '"';
  }
  var PAINTED_LINE_TYPE = { 0: "DEFAULT", 1: "HOLD_SHORT_FORWARD", 2: "HOLD_SHORT_BACKWARD", 3: "EDGE_LINE_DASHED", 4: "EDGE_LINE_SOLID", 5: "EDGE_SERVICE_DASHED", 6: "EDGE_SERVICE_SOLID", 7: "HOLD_SHORT_TAXIWAY", 8: "ILS_HOLD_SHORT", 9: "SERVICE_DASHED", 10: "DEFAULT_LIGHTED", 11: "HOLD_SHORT_FORWARD_LIGHTED", 12: "HOLD_SHORT_BACKWARD_LIGHTED", 13: "EDGE_LINE_DASHED_LIGHTED", 14: "EDGE_LINE_SOLID_LIGHTED", 15: "EDGE_SERVICE_DASHED_LIGHTED", 16: "EDGE_SERVICE_SOLID_LIGHTED", 17: "HOLD_SHORT_TAXIWAY_LIGHTED", 18: "ILS_HOLD_SHORT_LIGHTED", 19: "SERVICE_DASHED_LIGHTED", 20: "WIDE_YELLOW", 21: "WIDE_YELLOW_LIGHTED", 22: "NON_MOVEMENT", 23: "NON_MOVEMENT_LIGHTED", 24: "ENHANCED_CENTER", 25: "ENHANCED_CENTER_LIGHTED", 26: "WIDE_WHITE", 27: "WIDE_WHITE_LIGHTED", 28: "NON_MOVEMENT_BACK", 29: "NON_MOVEMENT_BACK_LIGHTED", 30: "EDGE_SOLID_ORTHO", 31: "EDGE_SOLID_ORTHO_LIGHTED", 32: "EDGE_SOLID_ORTHO_BACK", 33: "EDGE_SOLID_ORTHO_BACK_LIGHT", 34: "WIDE_RED", 35: "WIDE_RED_LIGHTED", 36: "SLIM_RED", 37: "SLIM_RED_LIGHTED", 38: "HOLD_SHORT_FORWARD_MARKED", 39: "HOLD_SHORT_BACKWARD_MARKED", 40: "HOLD_SHORT_FORWARD_MARKED_L", 41: "HOLD_SHORT_BACKWARD_MARKED_L" };
  var LINE_TYPE = PAINTED_LINE_TYPE;
  var PAINTED_LINE_TRUE_ANGLE = { 0: "NONE", 1: "BEGIN", 2: "END", 3: "BOTH_ENDS", 4: "ALL_POINTS" };
  var PAINTED_LINE_OUTLINE = ["NO_OUTLINE", "LINE", "FIT", "BORDER"];
  var GUID_RUNWAY_MARKINGS = "{06C65325-BD2E-41F8-A062-710DC32E42E4}";
  var GUID_EDGELINE_SOLID = "{4EBBBBB6-08A3-4009-BD38-1BA096B75D45}";
  var GUID_CENTERLINE = "{A789C134-4487-43CB-8981-BAF5FCA23981}";
  var GUID_RUNWAY_LINE = "{DAEEABDD-69FC-4E8E-A693-BA2E332533D1}";
  function classifyPaintedLine(ltype, tang, surf) {
    if (ltype === "WIDE_YELLOW") return tang === "ALL_POINTS" ? "RunwayMarkings" : "Edgelines";
    if (ltype === "WIDE_WHITE") {
      if ((tang === "ALL_POINTS" && surf === GUID_CENTERLINE) ||
          (tang === "NONE" && surf === GUID_RUNWAY_LINE)) return "RunwayMarkings";
      return "PaintedMarkings";
    }
    if (ltype === "EDGE_LINE_SOLID")
      return (surf === GUID_EDGELINE_SOLID || surf === GUID_RUNWAY_LINE) ? "Edgelines" : "Centerlines";
    if (ltype === "ENHANCED_CENTER" || ltype === "DEFAULT") return "Centerlines";
    if (ltype === "EDGE_SERVICE_DASHED") return tang === "ALL_POINTS" ? "PaintedMarkings" : "Centerlines";
    return "PaintedMarkings";
  }
  function classifyEdgeLights(preset) {
    if (preset === "Runway Alarm") return "Runway Alarm Lights";
    if (preset.indexOf("Center") === 0) return "Centerlights";
    return "Edgelights";
  }


  /* ======================= 排除矩形（section 0x2E） ======================= */
  var EXCL_FLAGS = [[3, "excludeAllObjects"], [4, "excludeBeaconObjects"], [5, "excludeEffectObjects"],
    [6, "excludeGenericBuildingObjects"], [7, "excludeLibraryObjects"], [8, "excludeTaxiwaySignObjects"],
    [9, "excludeTriggerObjects"], [10, "excludeWindsockObjects"], [11, "excludeExtrusionBridgeObjects"],
    [12, "excludeSimObjects"], [13, "excludeWorldScripts"], [14, "excludeCarParking"],
    [15, "excludeRectangles"], [16, "excludePolygons"]];

  function cvxLon(raw) { return raw === 0 ? 0.0 : raw * 4.470348358154297e-07 - 180.0; }
  function cvxLat(raw) { return raw === 0 ? 0.0 : 90.0 - raw * 3.3527612686157227e-07; }

  /* 定长 20 字节记录（无记录头）→ FSData 级 <ExclusionRectangle> */
  function exclusionElements(g, rep) {
    var out = [];
    g.dataOf(0x2E).forEach(function (pair) {
      var blob = pair[0], chunk = pair[1];
      var n = Math.min(chunk.nrec, Math.floor(blob.length / 20));
      for (var k = 0; k < n; k++) {
        var rec = blob.subarray(k * 20, k * 20 + 20);
        if (rec.length < 20) break;
        var flags = u32(rec, 0);
        var s = '\t<ExclusionRectangle latitudeMinimum="' + f(cvxLat(i32(rec, 16)), 14) +
          '" latitudeMaximum="' + f(cvxLat(i32(rec, 8)), 14) +
          '" longitudeMinimum="' + f(cvxLon(i32(rec, 4)), 14) +
          '" longitudeMaximum="' + f(cvxLon(i32(rec, 12)), 14) + '"';
        for (var i = 0; i < EXCL_FLAGS.length; i++)
          s += ' ' + EXCL_FLAGS[i][1] + '="' + (((flags >>> EXCL_FLAGS[i][0]) & 1) ? "TRUE" : "FALSE") + '"';
        out.push(s + "/>");
        rep.counts.exclusion++;
      }
    });
    return out;
  }

  /* ======================= 导航台（section 0x13 VorIls） ======================= */
  var _f32v = new Float32Array(1);
  function f32v(x) { _f32v[0] = Number(x); return _f32v[0]; }
  var _F32_0001 = f32v(0.001);
  var RUNWAY_NUMBER_ENUM = {}, DESIGNATOR_ENUM = { 0: "NONE", 1: "LEFT", 2: "RIGHT", 3: "CENTER", 4: "WATER", 5: "A", 6: "B" };
  (function () {
    for (var i = 0; i < 36; i++) RUNWAY_NUMBER_ENUM[i] = ("0" + i).slice(-2);
    var extra = ["NORTH", "NORTHEAST", "EAST", "SOUTHEAST", "SOUTH", "SOUTHWEST", "WEST", "NORTHWEST"];
    for (var j = 0; j < extra.length; j++) RUNWAY_NUMBER_ENUM[36 + j] = extra[j];
  })();

  function icao(raw, shift) {
    if (shift === undefined) shift = 5;
    var n = (raw >>> shift), chars = [], rem;
    while (n > 0) {
      rem = n % 38; n = Math.floor(n / 38);
      chars.push(rem === 0 ? " " : String.fromCharCode(rem >= 2 && rem <= 11 ? rem + 46 : rem + 53));
    }
    return chars.reverse().join("");
  }

  /* ======================= 航路点 / 地标（section 0x22 / 0x31） ======================= */
  var WAYPOINT_TYPE = { 1: "NAMED", 2: "UNNAMED", 3: "VOR", 4: "NDB", 5: "OFF_ROUTE",
    6: "IAF", 7: "FAF", 8: "RNAV", 9: "VFR" };

  function fmtUnit(v, unit) {
    var s = Number(v).toFixed(3).replace(/0+$/, "");
    if (s.charAt(s.length - 1) === ".") s += "0";
    return s + unit;
  }

  function fmtAltDerived(rawMm) {          // Altitude(is_int=True) → f32(raw*f32(0.001))
    var m = f32v(rawMm * _F32_0001);
    return m === 0 ? "0.0F" : fmtUnit(m, "M");
  }

  var NDB_TYPE = { 0: "COMPASS_POINT", 1: "MH", 2: "H", 3: "HH" };
  var NDB_REC_ID = 0x0106;

  /* NDB（section 0x17，记录 id 0x0106）→ FSData 下的 <Ndb>
     记录头 40 字节：+4 u32 rec_size、+6 u16 type、+8 u32 freq(KHz)、+12 i32 lon、
     +16 i32 lat、+20 i32 alt(mm)、+24 f32 range、+28 f32 magvar、+32 u32 ident、
     +36 u32（低 11 位 region）；后续为 (u16 st, u32 len) 子记录，st=0x19 为名称（cstring 从 +6 起） */
  function ndbElements(g, rep) {
    var out = [];
    g.dataOf(0x17).forEach(function (pair) {
      var blob = pair[0], pos = 0;
      while (pos + 6 <= blob.length) {
        var tid = u16(blob, pos), size = u32(blob, pos + 2);
        if (size < 6 || pos + size > blob.length) break;
        var raw = blob.subarray(pos, pos + size);
        if (tid !== NDB_REC_ID || raw.length < 40) {
          pos += size;
          continue;
        }
        var d = {
          lat: navLat(i32(raw, 16)), lon: navLon(i32(raw, 12)), alt: navAlt(i32(raw, 20)),
          type: NDB_TYPE[raw[6]] || String(raw[6]), freq: u32(raw, 8) / 1000.0,
          range: f32(raw, 24), magvar: f32(raw, 28),
          region: icao(u32(raw, 36) & 2047, 0), ident: icao(u32(raw, 32)), name: ""
        };
        var p = 40;
        while (p + 6 <= size) {
          var st = u16(raw, p), ss = u32(raw, p + 2);
          if (ss < 6 || p + ss > size) break;
          if (st === 0x19) {
            d.name = cstr(raw.subarray(p, p + ss), 6);
          } else {
            rep.unknown.push("Ndb 子记录 0x" + ("0000" + st.toString(16)).slice(-4) + " 长度 " + ss);
          }
          p += ss;
        }
        out.push('\t<Ndb lat="' + fmtShort(d.lat) + '" lon="' + fmtShort(d.lon) + '" alt="' +
          fmtShort(d.alt) + '" type="' + xesc(d.type) + '" frequency="' + f(d.freq, 3) +
          '" range="' + fmtF32(d.range) + '" magvar="' + fmtF32(d.magvar) + '" region="' +
          xesc(d.region) + '" ident="' + xesc(d.ident) + '"' +
          (d.name ? ' name="' + xesc(d.name) + '"' : "") + '/>');
        rep.counts.ndb = (rep.counts.ndb || 0) + 1;
        pos += size;
      }
    });
    return out;
  }

  function waypointElements(g, rep) {
    var out = [];
    g.dataOf(0x22).forEach(function (pair) {
      var blob = pair[0], pos = 0;
      while (pos + 6 <= blob.length) {
        var size = u32(blob, pos + 2);
        if (size < 6 || pos + size > blob.length) break;
        var raw = blob.subarray(pos, pos + size);
        if (raw.length < 28) {
          rep.unknown.push("waypoint record id 0x" + ("0000" + u16(blob, pos).toString(16)).slice(-4) +
            " size " + size);
          pos += size;
          continue;
        }
        var isW24 = (u16(blob, pos) === 0x0108 && raw.length >= 36);
        var wRegion = isW24 ? icao(u32(raw, 28) & 2047, 0) : icao(u32(raw, 24) & 2047, 0);
        var wIdent = isW24 ? icao(icao2024(u32(raw, 20)), 0) : icao(u32(raw, 20));
        out.push('\t<Waypoint lon="' + f(navLon(i32(raw, 8)), 14) + '" lat="' + f(navLat(i32(raw, 12)), 14) +
          '" magvar="' + fmtF32(f32(raw, 16)) + '" waypointType="' + (WAYPOINT_TYPE[raw[6]] || String(raw[6])) +
          '" waypointRegion="' + wRegion + '" waypointIdent="' + wIdent + '"/>');
        rep.counts.waypoint = (rep.counts.waypoint || 0) + 1;
        pos += size;
      }
    });
    return out;
  }

  function landmarkElements(g, rep) {
    var out = [];
    g.dataOf(0x31).forEach(function (pair) {
      var blob = pair[0], pos = 0;
      while (pos + 6 <= blob.length) {
        var size = u32(blob, pos + 2);
        if (size < 6 || pos + size > blob.length) break;
        if (size >= 38) {
          var raw = blob.subarray(pos, pos + size);
          var nlen = raw[34], tlen = raw[35], olen = raw[36];
          var cut = function (off, ln) {
            var b = raw.subarray(off, off + ln), z = b.indexOf(0);
            return UTF8.decode(z >= 0 ? b.subarray(0, z) : b);
          };
          var s = '\t<LandmarkLocation instanceId="' + guid(raw.subarray(6, 22)) + '" lat="' +
            f(navLat(i32(raw, 17)), 14) + '" lon="' + f(navLon(i32(raw, 22)), 14) + '" alt="' +
            fmtAltDerived(i32(raw, 30)) + '" name="' + xesc(cut(38, nlen)) + '" type="' + xesc(cut(38 + nlen, tlen)) + '"';
          var own = cut(38 + nlen + tlen, olen);
          if (own) s += ' owner="' + xesc(own) + '"';
          out.push(s + "/>");
          rep.counts.landmark = (rep.counts.landmark || 0) + 1;
        }
        pos += size;
      }
    });
    return out;
  }

  function fmtShort(v) {
    var s = String(Number(v));
    return s.slice(-2) === ".0" ? s.slice(0, -2) : s;
  }

  function u64hex(b, o) {
    var hi = u32(b, o + 4), lo = u32(b, o), s = hi.toString(16).toUpperCase();
    while (s.length < 8) s = "0" + s;
    var t = lo.toString(16).toUpperCase();
    while (t.length < 8) t = "0" + t;
    return s + t;
  }

  /* 按「精确十进制展开 + 半偶数舍入」格式化到 dec 位小数（与对照解析程序的
     printf 家族「%.*f」语义一致；JS 的 toFixed 是半远离零舍入，不能直接用） */
  function pyFixed(v, dec) {
    var neg = v < 0, a = Math.abs(v);
    var s = a.toFixed(dec + 20);
    var dot = s.indexOf(".");
    if (dot < 0) return neg ? "-" + s : s;
    var ip = s.slice(0, dot), fp = s.slice(dot + 1);
    var keep = fp.slice(0, dec), rest = fp.slice(dec);
    if (!rest.length) return (neg ? "-" : "") + (dec ? ip + "." + keep : ip);
    var up = false;
    if (/^5(0*)$/.test(rest)) {
      // 恰好一半：取最近的偶数
      var lastDigit = (keep.length ? keep.charAt(keep.length - 1) : ip.charAt(ip.length - 1));
      up = (parseInt(lastDigit, 10) % 2) === 1;
    } else {
      up = rest.charAt(0) >= "5";
    }
    var digits = (ip + keep).split("");
    if (up) {
      var k = digits.length - 1;
      while (k >= 0) {
        if (digits[k] === "9") { digits[k] = "0"; k--; }
        else { digits[k] = String.fromCharCode(digits[k].charCodeAt(0) + 1); break; }
      }
      if (k < 0) digits.unshift("1");
    }
    var all = digits.join("");
    var ipart = all.slice(0, all.length - dec) || "0";
    var fpart = all.slice(all.length - dec);
    var out = dec ? ipart + "." + fpart : ipart;
    return (neg ? "-" : "") + out;
  }

  function fmtF32(v) {
    var x = f32v(Number(v));
    if (x !== x) return "NaN";
    if (x === 0) return "0";
    if (Math.abs(x) >= 1e15) return String(x);
    if (x === Math.trunc(x)) return String(Math.trunc(x));
    for (var dec = 1; dec <= 8; dec++) {
      var s = pyFixed(x, dec);
      if (f32v(parseFloat(s)) === x) return s;
    }
    return String(x);
  }

  function navAlt(raw) { return f32v(raw * _F32_0001); }
  function navLon(raw) { return raw === 0 ? 0.0 : raw * 4.470348358154297e-07 - 180.0; }
  function navLat(raw) { return raw === 0 ? 0.0 : 90.0 - raw * 3.3527612686157227e-07; }

  /* 机场记录的 ICAO 标识：0x0113（2024）@+76 移位 6；0x0056（2020）@+40 移位 5。 */
  function airportIdent(blob, hid) {
    if (hid === 0x0113 && blob.length >= 80) return icao(u32(blob, 76), 6);
    if (blob.length >= 44) return icao(u32(blob, 40), 5);
    return "";
  }

  /* icao_2024：2024 版 VorIls 的 ident 可能被整体加了 2^26，按解码可读性择一。 */
  function icao2024(rawCode, bitShift) {
    if (bitShift === undefined) bitShift = 6;
    var stored = rawCode >>> bitShift;
    function valid(v) {
      if (v.length < 1 || v.length > 5) return false;
      for (var i = 0; i < v.length; i++) {
        var ch = v.charAt(i);
        if (!(("0" <= ch && ch <= "9") || ("A" <= ch && ch <= "Z"))) return false;
      }
      return true;
    }
    var c0 = icao(stored, 0);
    if (valid(c0) && (c0.length <= 4 || /[A-Za-z]/.test(c0.charAt(0)))) return stored;
    if (valid(icao(stored + 0x04000000, 0))) return stored + 0x04000000;
    return stored;
  }

  /* section 0x13：逐条 (u16 类型, u32 长度) 记录 → Ils 结构体 */
  function navRecords(g, rep) {
    var out = [];
    g.dataOf(0x13).forEach(function (pair) {
      var blob = pair[0], pos = 0;
      while (pos + 6 <= blob.length) {
        var rt = u16(blob, pos), rs = u32(blob, pos + 2);
        if (rs < 6 || pos + rs > blob.length) break;
        if (rt === 19 || rt === 261 || rt === 263) {
          var rec = blob.subarray(pos, pos + rs), is24 = (rt === 261 || rt === 263);
          var base = is24 ? 48 : 40;
          var d = {
            airport_ident: icao(((u32(rec, is24 ? 40 : 36)) >>> 11) & 0x1FFFFF, 0),
            ident: is24 ? icao(icao2024(u32(rec, 32)), 0) : icao(u32(rec, 32)),
            lon: navLon(u32(rec, 8)), lat: navLat(u32(rec, 12)), alt: navAlt(i32(rec, 16)),
            frequency: u32(rec, 20) / 1000000.0, range: f32(rec, 24), magvar: f32(rec, 28),
            name: "", number: "", designator: "NONE", heading: 0.0, width: 0.0,
            back_course: false, dme: [], glide: []
          };
          var p = base;
          while (p + 6 <= rs) {
            var st = u16(rec, p), ss = u32(rec, p + 2);
            if (ss < 6 || p + ss > rs) break;
            if ((st === 0x14 || st === 0x115) && ss >= 16) {
              d.number = RUNWAY_NUMBER_ENUM[rec[p + 6]] || "00";
              d.designator = DESIGNATOR_ENUM[rec[p + 7]] || "NONE";
              d.heading = f32(rec, p + 8);
              d.width = f32(rec, p + 12);
            } else if (st === 0x15 && ss >= 28) {
              d.glide.push({ lon: navLon(i32(rec, p + 8)), lat: navLat(i32(rec, p + 12)),
                alt: navAlt(i32(rec, p + 16)), range: f32(rec, p + 20), pitch: f32(rec, p + 24) });
            } else if ((st === 0x16 || st === 0x114) && ss >= 24) {
              d.dme.push({ lon: navLon(i32(rec, p + 8)), lat: navLat(i32(rec, p + 12)),
                alt: navAlt(i32(rec, p + 16)), range: f32(rec, p + 20) });
            } else if (st === 0x19) {
              d.name = cstr(rec, p + 6).replace(/\u0000+$/, "");
            }
            p += ss;
          }
          rep.counts.ils++;
          out.push(d);
        }
        pos += rs;
      }
    });
    return out;
  }

  function ilsXml(d, end) {
    var freq = f(d.frequency, 3).replace(/0+$/, "").replace(/\.$/, "");
    var s = '\n\t\t\t<Ils lat="' + f(d.lat, 14) + '" lon="' + f(d.lon, 14) + '" alt="' + f(d.alt, 14) + '"';
    if (end) s += ' end="' + end + '"';
    s += ' range="' + f(d.range, 14) + '" ident="' + xesc(d.ident) + '" magvar="' + f(d.magvar, 6) +
      '" heading="' + f(d.heading, 14) + '" frequency="' + freq + '"';
    if (d.name) s += ' name="' + xesc(d.name) + '"';
    s += ' backCourse="' + (d.back_course ? "TRUE" : "FALSE") + '">';
    for (var i = 0; i < d.dme.length; i++) {
      var dm = d.dme[i];
      s += '\n\t\t\t\t<Dme lat="' + fmtShort(dm.lat) + '" lon="' + fmtShort(dm.lon) + '" alt="' +
        fmtShort(dm.alt) + '" range="' + fmtF32(dm.range) + '" />';
    }
    for (var k = 0; k < d.glide.length; k++) {
      var gs = d.glide[k];
      s += '\n\t\t\t\t<GlideSlope lat="' + fmtShort(gs.lat) + '" lon="' + fmtShort(gs.lon) + '" alt="' +
        fmtShort(gs.alt) + '" range="' + fmtF32(gs.range) + '" pitch="' + fmtF32(gs.pitch) + '" />';
    }
    return s + "\n\t\t\t</Ils>";
  }

  function endMatches(ilsDesig, rwDesig) {
    return (!ilsDesig) || ilsDesig === "NONE" || ilsDesig === rwDesig;
  }

  /* 按「机场 + 跑道号 + 方位」把 Ils 挂到跑道上（_propagate 的规则） */
  function attachIls(g, runwayMeta, nodes, rep) {
    var unattached = [];
    navRecords(g, rep).forEach(function (d) {
      var end = null;
      if (d.number && d.airport_ident) {
        for (var i = 0; i < runwayMeta.length; i++) {
          var rw = runwayMeta[i];
          if (d.number === rw.secNum && endMatches(d.designator, rw.secDesig)) {
            rw.ils.push(ilsXml(d, "SECONDARY")); end = "SECONDARY"; break;
          }
          if (d.number === rw.priNum && endMatches(d.designator, rw.priDesig)) {
            rw.ils.push(ilsXml(d, "PRIMARY")); end = "PRIMARY"; break;
          }
        }
      }
      if (end === null) unattached.push(ilsXml(d, null));
    });
    runwayMeta.forEach(function (rw) {
      if (rw.ils.length) nodes[rw.node] = nodes[rw.node].replace(ILS_SLOT, ILS_SLOT + rw.ils.join(""));
    });
    return unattached;
  }

  /* ======================= 飞行程序（sub-record 0xFA Approach） ======================= */
  var LEG_TYPE = { 1: "AF", 2: "CA", 3: "CD", 4: "CF", 5: "CI", 6: "CR", 7: "DF", 8: "FA", 9: "FC",
    10: "FD", 11: "FM", 12: "HA", 13: "HF", 14: "HM", 15: "IF", 16: "PI", 17: "RF", 18: "TF", 19: "VA",
    20: "VD", 21: "VI", 22: "VM", 23: "VR" };
  var APPROACH_TYPE = { 0: "UNKNOWN", 1: "GPS", 2: "VOR", 3: "NDB", 4: "ILS", 5: "LOCALIZER", 6: "SDF",
    7: "LDA", 8: "VORDME", 9: "NDBDME", 10: "RNAV", 11: "LOCALIZER_BACKCOURSE" };
  var TRANSITION_TYPE = { 1: "FULL", 2: "DME", 3: "NDB", 4: "VOR", 5: "GPS", 6: "AIRWAY", 7: "ILS" };
  var ALTITUDE_DESCRIPTOR = { 0: "", 1: "A", 2: "+", 3: "-", 4: "B", 5: "C", 6: "G", 7: "H", 8: "I",
    9: "J", 10: "V" };
  var TURN_DIRECTION = { 0: "NULL", 1: "L", 2: "R", 3: "E" };
  var FIX_TYPE = { 0: "UNKNOWN", 1: "AIRPORT", 2: "VOR", 3: "NDB", 4: "TERMINAL_NDB", 5: "WAYPOINT",
    6: "TERMINAL_WAYPOINT", 8: "LOCALIZER", 9: "RUNWAY" };
  var _FT_PER_M = 3.2808399200439453;

  var LEG_ALTITUDE2 = mkSet("AF IF FC VD CD VR RF FD DF VI CR TF CI CF");
  var LEG_COURSE = mkSet("AF VD HF HM FM PI FC VM CD VA VR FD VI CR TF CA CI HA RF FA CF");
  var LEG_FIX = mkSet("AF IF FC VM HF HA RF FD DF FA HM FM PI TF CF");
  var LEG_FLY_OVER = mkSet("AF FC HF VR HA RF FD DF CR TF CI CF");
  var LEG_RHO = mkSet("AF IF FC HF HA FD DF FA HM FM PI TF CF");
  var LEG_THETA = mkSet("AF IF FC HF VR HA RF FD DF FA HM FM CR PI TF CF");
  var LEG_TIME_DIST = mkSet("FC VD CD HF HA RF FD HM PI TF CF");
  var LEG_VERTICAL_ANGLE = mkSet("RF TF CF");

  function mkSet(str) {
    var o = {}, p = str.split(" ");
    for (var i = 0; i < p.length; i++) o[p[i]] = true;
    return o;
  }

  function fmt00Hash(v) {
    var s = f(v, 3);
    if (s.indexOf(".") >= 0) {
      s = s.replace(/0+$/, "");
      if (s.slice(-1) === ".") s += "0";
    }
    return s;
  }

  function fmtHash(v) {
    var s = fmt00Hash(v);
    return s.slice(-2) === ".0" ? s.slice(0, -2) : s;
  }

  function fmtAltStr(meters) { return f(meters * _FT_PER_M, 1) + "F"; }

  function plainMeters(v) {
    var s = f(v, 3);
    return s.indexOf(".") >= 0 ? s.replace(/0+$/, "").replace(/\.$/, "") : s;
  }

  /* Python round()：半数取偶 */
  function pyRound(x) {
    var fl = Math.floor(x), diff = x - fl;
    if (diff > 0.5) return fl + 1;
    if (diff < 0.5) return fl;
    return (fl % 2 === 0) ? fl : fl + 1;
  }

  /* 腿属性的长度串（_dist_str）：优先整海里（NN），useUnit 时其次整米（MM），否则纯米数 */
  function distStr(v, useUnit) {
    var m = Number(v), nm = m / 1852.0, rn = pyRound(nm);
    if (rn !== 0 && Math.abs(rn - nm) < 0.01) return rn + "N";
    if (useUnit && Math.abs(pyRound(m) - m) < 0.01) return pyRound(m) + "M";
    return plainMeters(m);
  }

  /* 腿属性串（_leg_attrs）：FS9/FS20 与 2024 两种步长共用 */
  function legAttrs(t, ad, turn, courseTrue, timeSpec, flyOver, fixType, fixIdent, fixRegion,
                    rtype, rident, rregion, theta, rho, course, dist, a1, a2, speed, vang, flags, ind) {
    var s = '\n' + ind + '<Leg type="' + t + '"';
    if (LEG_FIX[t]) s += ' fixType="' + fixType + '" fixRegion="' + xesc(fixRegion) + '" fixIdent="' + xesc(fixIdent) + '"';
    if (LEG_FLY_OVER[t]) s += ' flyOver="' + (flyOver ? "TRUE" : "FALSE") + '"';
    if (turn !== "NULL") s += ' turnDirection="' + turn + '"';
    if (rtype !== undefined && rtype !== "" && rtype !== "UNKNOWN") {
      s += ' recommendedType="' + rtype + '"';
      if (rregion) s += ' recommendedRegion="' + xesc(rregion) + '"';
      s += ' recommendedIdent="' + xesc(rident) + '"';
    }
    if (LEG_THETA[t] && theta) s += ' theta="' + fmtHash(theta) + '"';
    /* rho 规则：类型允许且（非 0 或类型为 CF）；0 → "0"，整米 → "%dM"，其余走纯米数 */
    if (LEG_RHO[t] && rho !== undefined && rho !== null && (rho !== 0 || t === "CF")) {
      if (rho === 0) s += ' rho="0"';
      else if (Math.abs(pyRound(rho) - rho) < 0.01) s += ' rho="' + pyRound(rho) + 'M"';
      else s += ' rho="' + plainMeters(rho) + '"';
    }
    if (LEG_COURSE[t]) {
      if (courseTrue) s += ' trueCourse="' + fmtF32(course) + '"';
      else s += ' magneticCourse="' + fmtF32(course) + '"';
    }
    if (LEG_TIME_DIST[t]) {
      if (timeSpec) {
        if (dist) s += ' time="' + fmtShort(dist) + '"';
      } else if (dist) {
        s += ' distance="' + distStr(dist, false) + '"';
      }
    }
    if (ad) s += ' altitudeDescriptor="' + ad + '"';
    if (ad) s += ' altitude1="' + fmtAltStr(a1) + '"';
    if (LEG_ALTITUDE2[t] && a2) s += ' altitude2="' + fmtAltStr(a2) + '"';
    if (speed >= 0) s += ' speedLimit="' + Math.trunc(speed) + '"';
    if (LEG_VERTICAL_ANGLE[t] && vang) s += ' verticalAngle="' + fmtShort(vang) + '"';
    var fbits = [["isIAF", 1], ["isIF", 2], ["isFAF", 4], ["isMAP", 8]];
    for (var i = 0; i < fbits.length; i++) if (flags & fbits[i][1]) s += ' ' + fbits[i][0] + '="TRUE"';
    return s + "/>";
  }

  /* FS9/FS20 腿记录（60 或 72 字节）→ _leg_xml */
  function legXml(leg, rep, ind) {
    if (ind === undefined) ind = "\t\t\t\t";
    var t = LEG_TYPE[leg[0]] !== undefined ? LEG_TYPE[leg[0]] : String(leg[0]);
    var ad = ALTITUDE_DESCRIPTOR[leg[1]] !== undefined ? ALTITUDE_DESCRIPTOR[leg[1]] : "";
    var fl = u16(leg, 2);
    var turn = TURN_DIRECTION[fl & 3] !== undefined ? TURN_DIRECTION[fl & 3] : "NULL";
    var courseTrue = (fl >> 8) & 1, timeSpec = (fl >> 9) & 1, flyOver = (fl >> 10) & 1;
    var fu = u32(leg, 4);
    var fixType = FIX_TYPE[fu & 31] !== undefined ? FIX_TYPE[fu & 31] : "UNKNOWN", fixIdent = icao(fu);
    var fixRegion = icao(u32(leg, 8) & 2047, 0);
    var rec = u32(leg, 12);
    var rtype = FIX_TYPE[rec & 31] !== undefined ? FIX_TYPE[rec & 31] : "UNKNOWN", rident = icao(rec);
    var rregion = icao(u32(leg, 16) & 2047, 0) || fixRegion;
    return legAttrs(t, ad, turn, courseTrue, timeSpec, flyOver, fixType, fixIdent, fixRegion,
                    rtype, rident, rregion, f32(leg, 20), f32(leg, 24), f32(leg, 28), f32(leg, 32),
                    f32(leg, 36), f32(leg, 40), f32(leg, 44), f32(leg, 48),
                    leg.length >= 72 ? u32(leg, 68) : 0, ind);
  }

  /* MSFS2024 腿记录（96 字节）→ _leg2024_xml */
  function leg2024Xml(leg, rep, ind) {
    if (ind === undefined) ind = "\t\t\t\t";
    if (leg.length < 96) return legXml(leg, rep, ind);
    var t = LEG_TYPE[leg[0]] !== undefined ? LEG_TYPE[leg[0]] : String(leg[0]);
    var ad = ALTITUDE_DESCRIPTOR[leg[1]] !== undefined ? ALTITUDE_DESCRIPTOR[leg[1]] : "";
    var fl = u16(leg, 2);
    var turn = TURN_DIRECTION[fl & 3] !== undefined ? TURN_DIRECTION[fl & 3] : "NULL";
    var courseTrue = (fl >> 8) & 1, timeSpec = (fl >> 9) & 1, flyOver = (fl >> 10) & 1;
    var fu = u32(leg, 4);
    var fixType = FIX_TYPE[fu & 63] !== undefined ? FIX_TYPE[fu & 63] : "UNKNOWN", fixIdent = icao(icao2024(fu), 0);
    var fixRegion = icao(u32(leg, 12) & 2047, 0);
    var rec = u32(leg, 20);
    var rtype = FIX_TYPE[rec & 63] !== undefined ? FIX_TYPE[rec & 63] : "UNKNOWN", rident = icao(icao2024(rec), 0);
    var rregion = icao(u32(leg, 28) & 2047, 0) || fixRegion;
    return legAttrs(t, ad, turn, courseTrue, timeSpec, flyOver, fixType, fixIdent, fixRegion,
                    rtype, rident, rregion, f32(leg, 36), f32(leg, 40), f32(leg, 44), f32(leg, 48),
                    f32(leg, 52), f32(leg, 56), f32(leg, 60), f32(leg, 64),
                    u32(leg, 92), ind);
  }

  /* 0xF4/0xF5/0xF6 容器（u16 计数 @+6，腿从 +8 起，FS20 步长 72）→ _legs_xml */
  function legsXml(container, name, rep, ind) {
    if (ind === undefined) ind = "\t\t\t";
    var n = u16(container, 6);
    var stride = container.length >= 8 + n * 72 ? 72 : 60;
    var out = '\n' + ind + '<' + name + '>';
    for (var i = 0; i < n; i++) {
      var off = 8 + i * stride;
      if (off + stride > container.length) break;
      out += legXml(container.subarray(off, off + stride), rep, ind + "\t");
      rep.counts.leg = (rep.counts.leg || 0) + 1;
    }
    return out + '\n' + ind + '</' + name + '>';
  }

  /* 腿容器：u16 计数 @+6，腿从 +8 起（2024 步长 96，FS20 72，FS9 60）→ _legs_container */
  function legsContainer(body, name, attrs, ind, rep) {
    var n = u16(body, 6), stride, fn;
    if (body.length >= 8 + n * 96) { stride = 96; fn = leg2024Xml; }
    else if (body.length >= 8 + n * 72) { stride = 72; fn = legXml; }
    else { stride = 60; fn = legXml; }
    var out = '\n' + ind + '<' + name + attrs + '>';
    for (var i = 0; i < n; i++) {
      var off = 8 + i * stride;
      if (off + stride > body.length) break;
      out += fn(body.subarray(off, off + stride), rep, ind + "\t");
      rep.counts.leg = (rep.counts.leg || 0) + 1;
    }
    return out + '\n' + ind + '</' + name + '>';
  }

  var LEG_IDS_COMMON = { 0xE5: 1, 0xF8: 1, 0x10E: 1 };
  var LEG_IDS_RUNWAY_TRANS = { 0x46: 1, 0x116: 1 };
  var LEG_IDS_ENROUTE_TRANS = { 0x47: 1, 0x4A: 1 };
  var LEG_IDS_RUNWAY = { 0xE4: 1, 0xF7: 1, 0x10D: 1, 0x116: 1 };
  var LEG_IDS_ENROUTE = { 0xE6: 1, 0xF9: 1, 0x10A: 1, 0x10B: 1, 0x4A: 1 };

  /* 跑道/航线过渡容器内部串 → _transition_container */
  function transitionContainer(body, st, rep) {
    var pos = 8, attrs = "";
    if (st === 0x46 || st === 0x116) {
      attrs = ' number="' + (RUNWAY_NUMBER_ENUM[body[7]] !== undefined ? RUNWAY_NUMBER_ENUM[body[7]] : "00") +
        '" designator="' + (DESIGNATOR_ENUM[body[8]] !== undefined ? DESIGNATOR_ENUM[body[8]] : "NONE") + '"';
      pos = 12;
    } else if (st === 0x4A) {
      var nm = cstrBytes(body.subarray(8, 16));
      if (nm) attrs = ' name="' + xesc(nm) + '"';
      pos = 16;
    }
    var s = "";
    while (pos + 6 <= body.length) {
      var cs = u16(body, pos), csLen = u32(body, pos + 2);
      if (csLen < 6 || pos + csLen > body.length) break;
      var sub = body.subarray(pos, pos + csLen);
      if (LEG_IDS_RUNWAY[cs]) s += legsContainer(sub, "RunwayTransitionLegs", attrs, "\t\t\t\t", rep);
      else if (LEG_IDS_ENROUTE[cs]) s += legsContainer(sub, "EnrouteTransitionLegs", "", "\t\t\t\t", rep);
      pos += csLen;
    }
    return s;
  }

  /* 0x42 Departure / 0x48 Arrival 载荷 → <Departure>/<Arrival> → _procedure_xml */
  function procedureXml(pay, tag, rep) {
    var nm = cstrBytes(pay.subarray(6, 14));
    var rw = [], en = [], cl = [], pos = 14;
    while (pos + 6 <= pay.length) {
      var st = u16(pay, pos), ss = u32(pay, pos + 2);
      if (ss < 6 || pos + ss > pay.length) break;
      var sub = pay.subarray(pos, pos + ss);
      if (LEG_IDS_RUNWAY_TRANS[st]) rw.push([st, sub]);
      else if (LEG_IDS_ENROUTE_TRANS[st]) en.push([st, sub]);
      else if (LEG_IDS_COMMON[st]) cl.push([st, sub]);
      pos += ss;
    }

    function block(name, items) {
      var inner = "";
      for (var i = 0; i < items.length; i++) inner += transitionContainer(items[i][1], items[i][0], rep);
      if (!inner) return '\n\t\t\t<' + name + '/>';
      return '\n\t\t\t<' + name + '>' + inner + '\n\t\t\t</' + name + '>';
    }

    function common() {
      if (!cl.length) return '\n\t\t\t<CommonRouteLegs/>';
      var s = "";
      for (var i = 0; i < cl.length; i++) s += legsContainer(cl[i][1], "CommonRouteLegs", "", "\t\t\t", rep);
      return s;
    }

    var head = '\n\t\t<' + tag;
    if (nm) head += ' name="' + xesc(nm) + '"';
    head += ">";
    var parts;
    if (tag === "Arrival") parts = [block("EnrouteTransitions", en), common(), block("RunwayTransitions", rw)];
    else parts = [block("RunwayTransitions", rw), common(), block("EnrouteTransitions", en)];
    return head + parts.join("") + '\n\t\t</' + tag + '>';
  }

  function transitionXml(b, rep) {
    var tt = TRANSITION_TYPE[b[6]] !== undefined ? TRANSITION_TYPE[b[6]] : String(b[6]);
    var fu = u32(b, 8), freg = u32(b, 12);
    var nm = cstrBytes(b.subarray(20, 28));
    var s = ('\n\t\t\t<Transition transitionType="' + tt + '" fixType="' +
      (FIX_TYPE[fu & 31] !== undefined ? FIX_TYPE[fu & 31] : "UNKNOWN") + '" fixRegion="' +
      xesc(icao(freg & 2047, 0)) + '" fixIdent="' + xesc(icao(fu)) + '" altitude="' +
      fmtAltStr(f32(b, 16)) + '" name="' + xesc(nm) + '">');
    var pos = 28;
    while (pos + 6 <= b.length) {
      var st = u16(b, pos), ss = u32(b, pos + 2);
      if (ss < 6 || pos + ss > b.length) break;
      if (st === 0xF6 || st === 0x10C) {
        s += legsXml(b.subarray(pos, pos + ss), "TransitionLegs", rep, "\t\t\t\t");
        rep.counts.transition_legs = (rep.counts.transition_legs || 0) + 1;
      }
      pos += ss;
    }
    return s + '\n\t\t\t</Transition>';
  }

  /* 0xFA Approach 载荷（不含 6 字节记录头）→ <Approach> → approach_xml */
  function approachXml(pay, rep) {
    var b = pay[2];
    var desig = (b >> 4) & 7;
    var suf = (pay[0] && pay[0] !== 0x30) ? String.fromCharCode(pay[0]) : "";
    var s = ('\n\t\t<Approach type="' + (APPROACH_TYPE[b & 15] !== undefined ? APPROACH_TYPE[b & 15] : "UNKNOWN") +
      '" runway="' + (RUNWAY_NUMBER_ENUM[pay[1]] !== undefined ? RUNWAY_NUMBER_ENUM[pay[1]] : "00") +
      '" designator="' + (DESIGNATOR_ENUM[desig] !== undefined ? DESIGNATOR_ENUM[desig] : "NONE") + '"' +
      (suf ? ' suffix="' + suf + '"' : "") +
      ' gpsOverlay="' + tf(b >> 7) +
      '" fixType="' + (FIX_TYPE[u32(pay, 6) & 31] !== undefined ? FIX_TYPE[u32(pay, 6) & 31] : "UNKNOWN") +
      '" fixRegion="' + xesc(icao(u32(pay, 10) & 2047, 0)) + '" fixIdent="' + xesc(icao(u32(pay, 6))) +
      '" altitude="' + fmtAltStr(f32(pay, 14)) + '" heading="' + fmtShort(f32(pay, 18)) +
      '" missedAltitude="' + fmtAltStr(f32(pay, 22)) + '"');
    var fl = pay.length > 26 ? pay[26] : 0;
    var abits = [["lnav", 1], ["lnavvnav", 2], ["lpv", 4], ["lp", 8]];
    for (var i = 0; i < abits.length; i++) if (fl & abits[i][1]) s += ' ' + abits[i][0] + '="TRUE"';
    s += ">";
    var bodyStr = "", transStr = "", pos = 30;
    while (pos + 6 <= pay.length) {
      var st = u16(pay, pos), ss = u32(pay, pos + 2);
      if (ss < 6 || pos + ss > pay.length) break;
      var chunk = pay.subarray(pos, pos + ss);
      if (st === 0xF4 || st === 0x10A) {
        bodyStr += legsXml(chunk, "ApproachLegs", rep);
        rep.counts.approach_legs = (rep.counts.approach_legs || 0) + 1;
      } else if (st === 0xF5 || st === 0x10B) {
        bodyStr += legsXml(chunk, "MissedApproachLegs", rep);
        rep.counts.missed_legs = (rep.counts.missed_legs || 0) + 1;
      } else if (st === 0x49 || st === 0x110) {
        transStr += transitionXml(chunk, rep);
        rep.counts.transition = (rep.counts.transition || 0) + 1;
      }
      pos += ss;
    }
    rep.counts.approach = (rep.counts.approach || 0) + 1;
    return s + bodyStr + transStr + '\n\t\t</Approach>';
  }

  /* 0x110 Transition（2024）：tt@0、legCt@1、fix（6 位类型 + ident<<6）@2、region+保留@10、
     高度 f32@14、8 字节保留@18、子记录从 @30（0x10C = 腿容器，26 字节起） */
  function transition2024Xml(b, rep) {
    var tt = TRANSITION_TYPE[b[0]] !== undefined ? TRANSITION_TYPE[b[0]] : String(b[0]);
    var fu = u32(b, 2), freg = u32(b, 10);
    var nm = cstrBytes(b.subarray(22, 30));
    var s = ('\n\t\t\t<Transition transitionType="' + tt +
      '" fixType="' + (FIX_TYPE[fu & 63] !== undefined ? FIX_TYPE[fu & 63] : "UNKNOWN") +
      '" fixRegion="' + xesc(icao(freg & 2047, 0)) + '" fixIdent="' + xesc(icao(icao2024(fu), 0)) +
      '" altitude="' + fmtAltStr(f32(b, 18)) + '"' +
      (nm ? ' name="' + xesc(nm) + '"' : "") + '>');
    var pos = 30;
    while (pos + 6 <= b.length) {
      var st = u16(b, pos), ss = u32(b, pos + 2);
      if (ss < 6 || pos + ss > b.length) break;
      if (st === 0xF6 || st === 0x10C) {
        s += legsContainer(b.subarray(pos, pos + ss), "TransitionLegs", "", "\t\t\t\t", rep);
        rep.counts.transition_legs = (rep.counts.transition_legs || 0) + 1;
      }
      pos += ss;
    }
    return s + '\n\t\t\t</Transition>';
  }

  /* 0x111 Approach（2024 布局：44 字节或更长，载荷 +38 起是子记录）→ approach2024_xml */
  function approach2024Xml(pay, rep) {
    var b = pay[2];
    var suf = (pay[0] && pay[0] !== 0x30) ? String.fromCharCode(pay[0]) : "";
    var fu = u32(pay, 6), freg = u32(pay, 14);
    var s = ('\n\t\t<Approach type="' + (APPROACH_TYPE[b & 15] !== undefined ? APPROACH_TYPE[b & 15] : "UNKNOWN") +
      '" runway="' + (RUNWAY_NUMBER_ENUM[pay[1]] !== undefined ? RUNWAY_NUMBER_ENUM[pay[1]] : "00") +
      '" designator="' + (DESIGNATOR_ENUM[(b >> 4) & 7] !== undefined ? DESIGNATOR_ENUM[(b >> 4) & 7] : "NONE") + '"' +
      (suf ? ' suffix="' + suf + '"' : "") +
      ' gpsOverlay="' + tf(b >> 7) +
      '" fixType="' + (FIX_TYPE[fu & 63] !== undefined ? FIX_TYPE[fu & 63] : "UNKNOWN") +
      '" fixRegion="' + xesc(icao(freg & 2047, 0)) + '" fixIdent="' + xesc(icao(icao2024(fu), 0)) +
      '" altitude="' + fmtAltStr(f32(pay, 22)) + '" heading="' + fmtF32(f32(pay, 26)) +
      '" missedAltitude="' + fmtAltStr(f32(pay, 30)) + '"');
    var fl = pay.length > 38 ? u32(pay, 34) : 0;
    var abits = [["lnav", 1], ["lnavvnav", 2], ["lpv", 4], ["lp", 8]];
    for (var ai = 0; ai < abits.length; ai++) s += ' ' + abits[ai][0] + '="' + tf(fl & abits[ai][1]) + '"';
    s += ">";
    var bodyStr = "", transStr = "", pos = 38;
    while (pos + 6 <= pay.length) {
      var st = u16(pay, pos), ss = u32(pay, pos + 2);
      if (ss < 6 || pos + ss > pay.length) break;
      var chunk = pay.subarray(pos, pos + ss);
      if (st === 0xF4 || st === 0x10A) {
        bodyStr += legsContainer(chunk, "ApproachLegs", "", "\t\t\t", rep);
        rep.counts.approach_legs = (rep.counts.approach_legs || 0) + 1;
      } else if (st === 0xF5 || st === 0x10B) {
        bodyStr += legsContainer(chunk, "MissedApproachLegs", "", "\t\t\t", rep);
        rep.counts.missed_legs = (rep.counts.missed_legs || 0) + 1;
      } else if (st === 0x49 || st === 0x110) {
        transStr += transition2024Xml(chunk.subarray(6), rep);
        rep.counts.transition = (rep.counts.transition || 0) + 1;
      }
      pos += ss;
    }
    rep.counts.approach = (rep.counts.approach || 0) + 1;
    return s + bodyStr + transStr + '\n\t\t</Approach>';
  }

  /* Apron._vertices_form_parallelogram：四顶点能否排序成平行四边形（容差 5%） */
  function verticesFormParallelogram(latlon) {
    var tol = 0.05;
    if (latlon.length !== 4) return false;
    function eq(a, b) {
      var la = Math.hypot(a[0], a[1]), lb = Math.hypot(b[0], b[1]);
      if (la < 1e-12 || lb < 1e-12) return false;
      return Math.abs(la - lb) / Math.max(la, lb) < tol &&
        Math.abs(a[0] * b[1] - a[1] * b[0]) / (la * lb) < tol;
    }
    var idx = [[0, 1, 2, 3]];
    for (var seed = 0; seed < 4; seed++) {
      var rest = [0, 1, 2, 3].filter(function (x) { return x !== seed; });
      for (var a = 0; a < 3; a++) for (var b = 0; b < 3; b++) for (var c = 0; c < 3; c++) {
        if (a === b || b === c || a === c) continue;
        idx.push([seed, rest[a], rest[b], rest[c]]);
      }
    }
    for (var k = 0; k < idx.length; k++) {
      var v = [latlon[idx[k][0]], latlon[idx[k][1]], latlon[idx[k][2]], latlon[idx[k][3]]];
      var t0 = Math.cos(Math.PI / 180 * v[0][0]), t1 = Math.cos(Math.PI / 180 * v[1][0]),
          t2 = Math.cos(Math.PI / 180 * v[2][0]), t3 = Math.cos(Math.PI / 180 * v[3][0]);
      var e0 = [v[1][0] - v[0][0], (v[1][1] - v[0][1]) * t0];
      var e2 = [v[3][0] - v[2][0], (v[3][1] - v[2][1]) * t2];
      var e1 = [v[2][0] - v[1][0], (v[2][1] - v[1][1]) * t1];
      var e3 = [v[0][0] - v[3][0], (v[0][1] - v[3][1]) * t3];
      if (eq(e0, e2) && eq(e1, e3)) return true;
    }
    return false;
  }

  /* Apron._is_rectangle：4 顶点 + 无附着物 + （有朝向或呈平行四边形） */
  function apronIsRect(verts, pay) {
    if (verts.length !== 4 || u32(pay, 38) !== 0) return false;
    if (f32(pay, 26) !== 0) return true;
    return verticesFormParallelogram(verts.map(function (v) { return [v[2], v[1]]; }));
  }

  function vertexRuns(pay, ref, minrun) {
    minrun = minrun || 2;
    var rlon = ref ? ref[0] : 0.0, rlat = ref ? ref[1] : 0.0;
    var pairs = [], o, ll;
    for (o = 0; o <= pay.length - 8; o++) {
      var lo = u32(pay, o), la = u32(pay, o + 4);
      ll = lonlat(lo, la);
      if (!(ll[0] >= -180 && ll[0] <= 180 && ll[1] >= -90 && ll[1] <= 90)) continue;
      if (Math.abs(ll[0] - rlon) > 0.5 || Math.abs(ll[1] - rlat) > 0.5) continue;
      pairs.push([o, ll[0], ll[1]]);
    }
    var runs = [], cur = [];
    for (var i = 0; i < pairs.length; i++) {
      if (cur.length && pairs[i][0] === cur[cur.length - 1][0] + 8) cur.push(pairs[i]);
      else { if (cur.length >= minrun) runs.push(cur); cur = [pairs[i]]; }
    }
    if (cur.length >= minrun) runs.push(cur);
    runs.sort(function (a, b) { return b.length - a.length; });
    return runs;
  }

  function findSurfaceGuid(pay, limit) {
    for (var o = 0; o < (limit || 40); o++) {
      if (o + 16 > pay.length) break;
      var ver = pay[o + 7] >> 4, varB = pay[o + 8] & 0xC0;
      if (varB === 0x80 && ver >= 1 && ver <= 8) return guid(pay.subarray(o, o + 16));
    }
    return "";
  }

  /** 反编译：输入 Uint8Array，返回 { xml, rep }；profile="2020" 时按 MSFS 2020 schema 输出 */
  function decompileBytes(data, sourceName, ident, profile) {
    sourceName = sourceName || "input.bgl";
    ident = (ident || "").toUpperCase();
    var is2020 = (String(profile) === "2020");
    IS2020 = is2020;
    var g = new Bgl(data);
    var rep = { counts: { runway: 0, start: 0, com: 0, taxiway_point: 0, taxiway_path: 0, taxiway_sign: 0, light_support: 0, jetway: 0, vector_placement: 0, airport_object: 0, parking: 0, apron: 0, painted_line: 0, painted_hatched: 0, light_preset: 0, light: 0, tower: 0, helipad: 0, archetype: 0, offset_threshold: 0, edge_lights: 0, vertex: 0, library_object: 0, windsock: 0, sim_object: 0, projected_mesh: 0 }, unknown: [], records: {}, meta: null, objects: 0 };
    var nodes = [], objs = [], edgeNodes = [], jetwayNodes = [], apObjNodes = [], apronNodes = [],
        apronGroups = [], paintedGroups = [], edgeGroups = [], objGroups = {},
        runwayMeta = [], pendingStarts = [],
      paintedNodes = [], presets = [], delAirport = [null], rwChildren = [], archOpen = -1, archOver = {};
    var ap = { lat: 0, lon: 0, alt: 0, name: "", ident: ident, counts: [] };
    var state = { npts: 1 << 30 }, vert, name, body, surf, o, i;

    // ---------------- 机场记录 ----------------
    g.dataOf(SECTION_AIRPORT).forEach(function (pair) {
      var blob = pair[0];
      var hid = blob.length >= 6 ? u16(blob, 0) : 0;
      if (blob.length < 0x50 || (hid !== 0x0113 && hid !== 0x0056)) { rep.unknown.push("airport section: unexpected header"); return; }
      ap.counts = [];
      for (i = 6; i < 12; i++) ap.counts.push(blob[i]);
      var rl = lonlat(u32(blob, 12), u32(blob, 16));
      ap.lon = rl[0]; ap.lat = rl[1];
      ap.alt = navAlt(i32(blob, 20));
      ap.fs24 = (hid === 0x0113);      // PaintedLine 的 is_fs24：机场记录类型 == 0x0113
      // Airport.__init__ 的标志位：+53 流量系数、+54 bit0 starAirport / bit1 isOnTIN、+59 bit0 applyFlatten
      ap.traffic = blob.length > 59 ? blob[53] / 255.0 : 1.0;
      ap.star = blob.length > 59 ? !!(blob[54] & 1) : true;
      ap.tin = blob.length > 59 ? !!(blob[54] & 2) : false;
      ap.flatten = blob.length > 59 ? !!(blob[59] & 1) : true;
      ap.fuel_mask = blob.length >= 52 ? u32(blob, 48) : 0;
      // 机场记录的 ident 是压缩 ICAO：0x0113（2024）@+76、移位 6；0x0056（2020）@+40、移位 5。
      // magvar 在 @+36（f32）。0x2C FsAirportSummary 里的 ICAO 只作兜底。
      var _idn = airportIdent(blob, hid);
      if (_idn) {
        ap.ident = _idn;
        ap.identFromAirport = true;
      }
      if (blob.length >= 40) ap.magvar = f32(blob, 36);
      var cstart = chainStart(blob, hid);
      rep.airportFormat = "0x" + hid.toString(16) + " chain@0x" + cstart.toString(16);

      chain(blob, cstart).forEach(function (rec) {
        var rid = rec[0], pay = rec[1];
        rep.records["0x" + rid.toString(16)] = (rep.records["0x" + rid.toString(16)] || 0) + 1;

        if (rid === 0x19) {                                   // 机场名
          ap.name = cstr(pay, 0);
        } else if (rid === 0xCE) {                            // 跑道
          var nw1 = u16(pay, 2), nw2 = u16(pay, 4);
          var num = nw1 & 0xFF;
          var priDesig = (nw1 >> 8) & 0x0F, secDesig = (nw2 >> 8) & 0x0F;
          rl = lonlat(u32(pay, 14), u32(pay, 18));
          var len = f32(pay, 26), wid = f32(pay, 30), hdg = f32(pay, 34);
          var gd = guid(pay.subarray(70, 86));
          var col = [pay[86], pay[87], pay[88], pay[89]];
          rep.counts.runway++;
          runwayMeta.push({
            node: nodes.length, ils: [],
            priNum: RUNWAY_NUMBER_ENUM[num] || "00",
            priDesig: DESIGNATOR_ENUM[priDesig] || "NONE",
            secNum: RUNWAY_NUMBER_ENUM[nw2 & 0xFF] || "00",
            secDesig: DESIGNATOR_ENUM[secDesig] || "NONE"
          });
          var rwColor = (!(col[0] || col[1] || col[2] || col[3]))
            ? "" : ('\n\t\t\t<Coloration red="' + col[2] + '" green="' + col[1] + '" blue="' + col[0] +
              '" alpha="' + col[3] + '" override="TRUE"/>');
          var rwFalloff = f32(pay, 66);
          var RWC = runwayChildren(pay, rep);
          nodes.push('\t\t<Runway lat="' + f(rl[1], 14) + '" lon="' + f(rl[0], 14) + '" alt="' + f(navAlt(i32(pay, 22)), 14) +
            '" heading="' + f(hdg, 14) + '" length="' + f(len, 14) + '" width="' + f(wid, 14) + '" surface="' + gd +
            '" number="' + (num < 10 ? "0" : "") + num + '" designator="' + (DESIGNATOR_ENUM[priDesig] || "NONE") +
            '" transparent="' + tf((pay[0] >> 7) & 1) + '" primaryLanding="' + tf(!((pay[45] >> 1) & 1)) +
            '" primaryTakeoff="' + tf(!(pay[45] & 1)) + '" primaryPattern="' + ((pay[45] >> 2) & 1 ? "RIGHT" : "LEFT") +
            '" secondaryLanding="' + tf(!((pay[45] >> 4) & 1)) + '" secondaryTakeoff="' + tf(!((pay[45] >> 3) & 1)) +
            '" secondaryPattern="' + ((pay[45] >> 5) & 1 ? "RIGHT" : "LEFT") +
            '" patternAltitude="' + f(f32(pay, 38), 14) + '"' +
            (rwFalloff > 0 ? ' falloff="' + f(rwFalloff, 6) + '"' : "") +
            ' groundMerging="' + tf(!((pay[45] >> 6) & 1)) + '" excludeVegetationAround="' + tf(!((pay[45] >> 7) & 1)) +
            '" primaryMarkingBias="' + f(0, 14) + '" secondaryMarkingBias="' + f(0, 14) + '">' + RWC.def.join("") + rwColor +
            '\n\t\t\t<Markings ' + markingsAttrs(u16(pay, 0x2A), pay.length > 0x2C ? pay[0x2C] : 0) + '/>' +
            '\n\t\t\t<Lights center="' + (LIGHT_LEVEL[(pay[0x2C] >> 2) & 3] || "MEDIUM") + '" edge="' +
            (LIGHT_LEVEL[pay[0x2C] & 3] || "MEDIUM") + '"' + (((pay[0x2C] >> 4) & 1) ? ' centerRed="TRUE"' : '') + '/>' +
            RWC.offset.join("") + RWC.blast.join("") + RWC.overrun.join("") + RWC.approach.join("") + RWC.vasi.join("") +
            ILS_SLOT + START_SLOT + RWC.material.join("") + rwChildren.join("") +
            '\n\t\t</Runway>');
          rwChildren.length = 0;
        } else if (rid === 0x111 && pay.length >= 38) {         // 飞行程序（进近，2024 布局）
          nodes.push(approach2024Xml(pay, rep));
          rwChildren.length = 0;
        } else if (rid === 0xFA && pay.length >= 30) {         // 飞行程序（进近）
          nodes.push(approachXml(pay, rep));
          rwChildren.length = 0;
        } else if (rid === 0x42 || rid === 0x48) {             // 飞行程序（SID / STAR）
          var dk = (rid === 0x42) ? "departure" : "arrival";
          rep.counts[dk] = (rep.counts[dk] || 0) + 1;
          if (pay.length >= 14) nodes.push(procedureXml(pay, (rid === 0x42) ? "Departure" : "Arrival", rep));
          rwChildren.length = 0;
        } else if (rid === 0x11 || rid === 0x6A) {             // 跑道入口（end 需与跑道主/次端比对后判定）
          rep.counts.start++;
          pendingStarts.push([nodes.length, pay]);
          nodes.push("");
        } else if (rid === 0x11A) {                            // COM
          var code = u16(pay, 0), freq = u32(pay, 2) / 1e6;
          name = pay.length > 16 ? stripZeros(cstr(pay, pay.length - 16)) : "";
          name = name.split("").filter(function (ch) { var c = ch.charCodeAt(0); return c >= 0x20 && c !== 0x7f; }).join("");
          rep.counts.com++;
          nodes.push('\t\t<Com type="' + comType(code, rep) + '" frequency="' + f(freq, 6) +
            '" name="' + xesc(name) + '"/>');
        } else if (rid === 0x12 && pay.length >= 10) {         // COM（另一种写法：u16 类型 + u32 频率(Hz) + 名称）
          var ccode = u16(pay, 0), cfreq = u32(pay, 2) / 1e6;
          var craw = pay.subarray(6), czero = craw.indexOf(0);
          if (czero >= 0) craw = craw.subarray(0, czero);
          var cname = UTF8.decode(craw).split("").filter(function (ch) {
            var c = ch.charCodeAt(0); return c >= 0x20 && c !== 0x7f;
          }).join("");
          rep.counts.com++;
          nodes.push('\t\t<Com type="' + comType(ccode, rep) + '" frequency="' + f(cfreq, 6) +
            '" name="' + xesc(cname) + '"/>');
        } else if (rid === 0x1A) {                             // 滑行道点
          var np = u16(pay, 0);
          state.npts = np;
          for (i = 0; i < np; i++) {
            var flg = u32(pay, 2 + i * 12);
            rl = lonlat(u32(pay, 6 + i * 12), u32(pay, 10 + i * 12));
            var t = POINT_TYPE[flg & 0xFF];
            if (t === undefined) { t = (flg & 0x100) ? "HOLD_SHORT" : "NORMAL"; rep.unknown.push("taxiway point flag 0x" + flg.toString(16)); }
            rep.counts.taxiway_point++;
            nodes.push('\t\t<TaxiwayPoint index="' + i + '" type="' + t + '" orientation="' +
              (TAXI_POINT_ORIENT[(flg >> 8) & 0xFF] || "FORWARD") + '" lat="' + f(rl[1], 14) +
              '" lon="' + f(rl[0], 14) + '"/>');
          }
        } else if (rid === 0xD4) {                             // 滑行道路径
          var npat = u16(pay, 0);
          var addPath = function (e, endOff) {
            if (endOff === undefined) endOff = 46;
            var ptype = PATH_TYPE[e[4] & 0x07] || "TAXI";
            rep.counts.taxiway_path++;
            nodes.push('\t\t<TaxiwayPath type="' + ptype + '" start="' + u16(e, 0) +
              '" end="' + u16(e, endOff) + '" width="' + f(f32(e, 8), 6) + '"' +
              (ptype !== "RUNWAY" ? (' name="' + e[5] + '"') : (' number="' + (RUNWAY_NUMBER_ENUM[e[5]] || "00") + '"')) +
              ' surface="' + guid(e.subarray(24, 40)) + '" centerLine="' + tf(e[6] & 1) + '"' +
              (((e[6] >> 1) & 1) ? ' centerLineLighted="TRUE"' : "") +
              (((e[4] >> 4) & 1) ? ' enhanced="TRUE"' : "") +
              (ptype === "RUNWAY" ? (' designator="' + (DESIGNATOR_ENUM[(u16(e, 2) >> 12) & 0x0F] || "NONE") + '"') : "") +
              ' drawSurface="' + tf((e[4] >> 5) & 1) + '" drawDetail="' + tf((e[4] >> 6) & 1) +
              '" groundMerging="' + tf((e[45] >> 0) & 1) + '" excludeVegetationAround="' + tf(!((e[45] >> 1) & 1)) +
              '" excludeVegetationInside="' + tf(!((e[45] >> 2) & 1)) + '" weightLimit="' + u32(e, 12) + '"/>');
          };
          // 定长数组（长度能被条数整除）是最可靠的形态：直接按步长切
          var stride = (npat && (pay.length - 2) % npat === 0) ? (pay.length - 2) / npat : 0;
          if (stride >= 24 && stride <= 80) {
            rep.pathStride = stride;
            for (i = 0; i < npat; i++) addPath(pay.subarray(2 + i * stride, 2 + (i + 1) * stride), stride - 2);
          } else {
          var pos = 2, made = 0;
          while (made < npat && pos + 48 <= pay.length) {
            var e = pay.subarray(pos, pos + 48);
            var tcode = e[4], w = f32(e, 8), end = u16(e, 46);
            var ok = (tcode & 0x07) >= 1 && (tcode & 0x07) <= 3 && w > 1.0 && w < 200.0 && end < state.npts;
            if (!ok) {
              // 数组中间夹带的独立子记录（ZGBH 里是 0xD5，44 字节：GUID + 三个 1.0）
              var nid = u16(pay, pos), nsz = u32(pay, pos + 2);
              if (nsz >= 6 && nsz <= pay.length - pos) {
                rep.unknown.push("taxiway path array: nested sub-record id 0x" + ("0000" + nid.toString(16)).slice(-4) +
                  " size " + nsz + " at +" + pos);
                pos += nsz;
                continue;
              }
              var skipped = null;
              for (var d = 1; d < 64; d++) {
                if (pos + d + 48 > pay.length) break;
                var e2 = pay.subarray(pos + d, pos + d + 48);
                var t2 = e2[4] & 0x07, w2 = f32(e2, 8);
                if (t2 >= 1 && t2 <= 3 && w2 > 1.0 && w2 < 200.0 && u16(e2, 46) < state.npts) { skipped = d; break; }
              }
              if (skipped === null) { rep.unknown.push("taxiway path array desync at +" + pos); break; }
              rep.unknown.push("taxiway path array: skipped " + skipped + " bytes at +" + pos + " (" +
                Array.prototype.map.call(pay.subarray(pos, pos + skipped), function (x) { return hex2(x); }).join(" ") + ")");
              pos += skipped;
              continue;
            }
            addPath(e);
            pos += 48; made++;
          }
          }
        } else if (rid === 0xE7) {                             // 机位
          var npk = u16(pay, 0);
          // 机位条目是变长的：56 字节固定主体 + 每条航司码 4 字节（数量在位域 24..31）
          var pkpos = 2;
          for (i = 0; i < npk; i++) {
            var ep = pay.subarray(pkpos, pkpos + 56);
            if (ep.length < 56) break;
            var packed = u32(ep, 0);
            // 位域：名称 0..5、推回 6..7、类型 8..11、机位号 12..23、航司码数 24..31
            var pname = packed & 0x3F, ptype = (packed >> 8) & 0xF, number = (packed >> 12) & 0xFFF;
            var codeCt = Math.floor(packed / 16777216) & 0xFF;
            var radius = f32(ep, 4), hdg2 = f32(ep, 8);
            rl = lonlat(u32(ep, 28), u32(ep, 32));
            var sufName = PARK_NAME[ep[37]] || "NONE";
            if (SUFFIX_OK.indexOf(sufName) < 0) {
              sufName = "NONE";
              rep.parkSuffixBad = (rep.parkSuffixBad || 0) + 1;
            }
            var codes = [];
            for (var cj = 0; cj < codeCt; cj++) {
              var c4 = pay.subarray(pkpos + 56 + cj * 4, pkpos + 60 + cj * 4);
              if (c4.length < 1) break;
              var cstr4 = "";
              for (var ck = 0; ck < c4.length; ck++) {
                if (c4[ck] === 0) break;
                cstr4 += String.fromCharCode(c4[ck]);
              }
              if (cstr4) codes.push(cstr4);
            }
            rep.counts.parking++;
            nodes.push('\t\t<TaxiwayParking index="' + i + '" type="' + (PARK_TYPE[ptype] || "NONE") + '" lat="' + f(rl[1], 14) +
              '" lon="' + f(rl[0], 14) + '" heading="' + f(hdg2, 6) + '" radius="' + f(radius, 6) + '" name="' +
              (PARK_NAME[pname] || "NONE") + '" number="' + number + '" suffix="' + sufName +
              '" numberMarking="' + (ep[36] === 1 ? "TRUE" : "FALSE") + '" has3DMesh="' + ((ep[38] & 1) ? "TRUE" : "FALSE") +
              '" numberBiasX="' + f(f32(ep, 44), 6) + '" numberBiasZ="' + f(f32(ep, 48), 6) +
              '" numberHeading="' + f(f32(ep, 52), 6) + '"' +
              (codes.length ? ' airlineCodes="' + xesc(codes.join(",")) + '"' : "") + '/>');
            pkpos += 56 + 4 * codeCt;
          }
        } else if (rid === 0xD0) {                             // 停机坪
          var runsA = vertexRuns(pay, [ap.lon, ap.lat]);
          if (runsA.length) {
            vert = runsA[0];
            /* 载荷：+0 标志位（bit0 绘制面/bit1 细节/bit2 localUV/bit3 stretchUV/bit7 flipUV）
               | +1 不透明度 | +2 RGBA | +6 表面 GUID | +34 优先级 */
            var aflags = pay[0];
            surf = guid(pay.subarray(6, 22));
            var aprior = i32(pay, 34), alocal = (aflags >> 2) & 1;
            var agrp = !alocal ? "GroundBase"
              : ((aprior === 1000000012 || surf === GUID_RUNWAY_MARKINGS) ? "RunwayMarkings" : "PaintedMarkings");
            var acolor = (pay[2] || pay[3] || pay[4] || pay[5])
              ? '\n\t\t\t\t<Coloration red="' + pay[4] + '" green="' + pay[3] + '" blue="' + pay[2] +
                '" alpha="' + pay[5] + '" override="TRUE"/>' : "";
            body = vert.map(function (v) { return '\n\t\t\t\t<Vertex lat="' + f(v[2], 14) + '" lon="' + f(v[1], 14) + '"/>'; }).join("");
            rep.counts.apron++; rep.counts.vertex += vert.length;
            apronNodes.push('\t\t\t<Apron surface="' + surf + '" drawSurface="' + tf(aflags & 1) +
              '" drawDetail="' + tf((aflags >> 1) & 1) + '" localUV="' + tf(alocal) + '" stretchUV="' +
              tf((aflags >> 3) & 1) + '" flipUV="' + tf((aflags >> 7) & 1) +
              '" groundMerging="' + tf(!((aflags >> 4) & 1)) + '" excludeVegetationAround="' + tf(!((aflags >> 5) & 1)) +
              '" excludeVegetationInside="' + tf(!((aflags >> 6) & 1)) + '" opacity="' + pay[1] +
              '" tiling="' + f(f32(pay, 22), 6) + '" heading="' + f(f32(pay, 26), 6) +
              '" falloff="' + f(f32(pay, 30), 6) + '" isRectangle="' + tf(apronIsRect(vert, pay)) + '"' +
              (pay[38] ? ' offsetU="' + pay[38] + '"' : "") + (pay[39] ? ' offsetV="' + pay[39] + '"' : "") +
              ' priority="' + aprior + '">' + acolor + body + '\n\t\t\t</Apron>');
            apronGroups.push(agrp);
          } else rep.unknown.push("apron record without vertex run");
        } else if (rid === 0xFF && pay.length >= 114) {        // 2024 文字标记（地面文字）
          rep.counts.text_marking = (rep.counts.text_marking || 0) + 1;
          if (!is2020) {
            var tcols = "";
            [[36, "ColorText"], [40, "ColorBackground"], [44, "ColorOutline"]].forEach(function (c) {
              var b = pay[c[0]], g = pay[c[0] + 1], r = pay[c[0] + 2], a = pay[c[0] + 3];
              if (b || g || r || a) {
                tcols += '\n\t\t\t\t<' + c[1] + ' red="' + r + '" green="' + g + '" blue="' + b +
                  '" alpha="' + a + '"/>';
                rep.counts.coloration = (rep.counts.coloration || 0) + 1;
              }
            });
            // 标签长度取 u16@48（按该长度截断，而不是按 NUL）
            var tlen = u16(pay, 48);
            var tlab = tlen ? UTF8.decode(pay.subarray(50, 50 + Math.min(tlen, 64))).split("\u0000")[0] : "";
            // 载荷布局（去掉 6 字节记录头）：lon i32@0、lat i32@4、alt f32@8、heading f32@12、
            // paddingY f32@16、scale f32@20、letterSpacing f32@24、lineSpacing f32@28、
            // paddingX f32@32、三色 BGRA @36/40/44、u16 文本长度@48、64 字节标签@50
            var tbody = '\t\t\t<TextMarking lat="' + f(cvxLat(i32(pay, 4)), 14) + '" lon="' +
              f(cvxLon(i32(pay, 0)), 14) + '" heading="' + f(f32(pay, 12), 6) + '" scale="' + f(f32(pay, 20), 6) +
              '" letterSpacing="' + f(f32(pay, 24), 6) + '" lineSpacing="' + f(f32(pay, 28), 6) +
              '" paddingX="' + f(f32(pay, 32), 6) + '" paddingY="' + f(f32(pay, 16), 6) +
              '"' + (tlab ? ' label="' + xesc(tlab) + '"' : "");
            nodes.push(tcols ? (tbody + ">" + tcols + "\n\t\t\t</TextMarking>") : (tbody + "/>"));
          }
        } else if (rid === 0xFB && pay.length >= 54) {         // 2024 灯柱（0xFB 推测映射到 <MastLight>）
          rep.counts.mast_light = (rep.counts.mast_light || 0) + 1;
          if (!is2020) {
            nodes.push('\t\t<MastLight lat="' + f(cvxLat(u32(pay, 10)), 14) + '" lon="' +
              f(cvxLon(u32(pay, 6)), 14) + '" heading="' + f(f32(pay, 26), 6) + '"/>');
          }
        } else if (rid === 0x0102) {          // 2024 WASM 模块声明（NUL 填充的路径串）
      rep.counts.wasm_module = (rep.counts.wasm_module || 0) + 1;
      if (!is2020) {
        var wend = pay.indexOf(0);
        if (wend < 0) wend = pay.length;
        var wpath = UTF8.decode(pay.subarray(0, wend));
        if (wpath) {
          nodes.push('\t\t<WasmModule name="' + wpath.replace(/&/g, "&amp;").replace(/"/g, "&quot;")
            .replace(/</g, "&lt;").replace(/>/g, "&gt;") + '"/>');
        }
      }
    } else if (rid === 0xCF) {                             // 画线
          var runsL = vertexRuns(pay, [ap.lon, ap.lat]);
          if (runsL.length) {
            vert = runsL[0];
            body = vert.map(function (v) { return '\n\t\t\t\t<Vertex lat="' + f(v[2], 14) + '" lon="' + f(v[1], 14) + '"/>'; }).join("");
            rep.counts.painted_line++; rep.counts.vertex += vert.length;
            var ltype = LINE_TYPE[pay[0]];
            if (ltype === undefined) { ltype = "DEFAULT"; rep.unknown.push("painted line type code 0x" + hex2(pay[0])); }
            var tang = PAINTED_LINE_TRUE_ANGLE[pay[1]] || "NONE";
            var psurf = guid(pay.subarray(6, 22));
            // 对照解析程序：机场记录为 0x0113 时（is_fs24）多输出 outlineType，取自载荷 +4 的 u16。
            // outlineType 不在 2020 版 bglcomp.xsd 里，故 2020 profile 下不输出（保证可直接编译）
            var oltype = (ap.fs24 && !is2020) ? (' outlineType="' + PAINTED_LINE_OUTLINE[Math.min(u16(pay, 4), 3)] + '"') : "";
            paintedNodes.push('\t\t\t<PaintedLine type="' + ltype + '"' + oltype + ' trueAngle="' + tang + '"' +
              (psurf === "{00000000-0000-0000-0000-000000000000}" ? "" : (' surface="' + psurf + '"')) +
              '' + '>' + body + '\n\t\t\t</PaintedLine>');
            paintedGroups.push(classifyPaintedLine(ltype, tang, psurf));
          } else rep.unknown.push("painted line without vertex run");
        } else if (rid === 0xD8 && pay.length >= 22) {         // 网格填充画线
          // +0 u32 类型码 | +4 u16 顶点数 | +6 f32 朝向 | +10 f32 间距 | +14 起 (u32 经度, u32 纬度)
          var hcnt = u16(pay, 4);
          if (14 + hcnt * 8 <= pay.length) {
            var htype = LINE_TYPE[pay[0]];
            if (htype === undefined) { htype = "DEFAULT"; rep.unknown.push("hatched area type code 0x" + hex2(pay[0])); }
            var hbody = "";
            for (i = 0; i < hcnt; i++) {
              var hll = lonlat(u32(pay, 14 + i * 8), u32(pay, 18 + i * 8));
              hbody += '\n\t\t\t\t<Vertex lat="' + f(hll[1], 14) + '" lon="' + f(hll[0], 14) + '"/>';
            }
            rep.counts.painted_hatched++; rep.counts.vertex += hcnt;
            paintedNodes.push('\t\t\t<PaintedHatchedArea' +
              ' heading="' + f(f32(pay, 6), 14) + '" spacing="' + f(f32(pay, 10), 14) + '" type="' + htype + '">' +
              hbody + '\n\t\t\t</PaintedHatchedArea>');
          } else rep.unknown.push("hatched area vertex count " + hcnt + " out of range");
        } else if (rid === 0x58) {                             // 灯光预设（后面的 0x59 是它的灯）
          var pnlen = pay.length > 1 ? pay[1] : 0;
          var pname = "";
          if (pnlen > 0 && pnlen <= Math.min(64, pay.length - 26)) pname = stripZeros(cstr(pay, 26)).slice(0, pnlen);
          presets.push({ name: pname, mesh: pay.length >= 22 ? guid(pay.subarray(6, 22)) : "",
            phase: pay.length >= 26 ? f32(pay, 22) : 0, lights: [] });
        } else if (rid === 0x59 && pay.length >= 60) {         // 预设里的一盏灯
          var lflags = u16(pay, 0), ldur = f32(pay, 50), lper = f32(pay, 54);
          var lightStr = '\t\t\t<Light relativePosition="' + f(f32(pay, 2), 6) + ' ' + f(f32(pay, 6), 6) + ' ' + f(f32(pay, 10), 6) +
            '" direction="' + f(f32(pay, 14), 6) + ' ' + f(f32(pay, 18), 6) + ' ' + f(f32(pay, 22), 6) +
            '" direction2="' + f(f32(pay, 26), 6) + ' ' + f(f32(pay, 30), 6) + ' ' + f(f32(pay, 34), 6) +
            '" type="' + ((lflags & 0x100) ? "OMNIDIRECTIONAL" : "UNIDIRECTIONAL") +
            '" fade="' + ((ldur > 0 || lper > 0) ? "FADE_IN_OUT" : "NO_FADE") +
            '" radius="' + f(f32(pay, 38), 6) + '" color="' + pay[44] + ' ' + pay[43] + ' ' + pay[42] +
            '" intensity="' + f(f32(pay, 46), 6) + '" duration="' + f(ldur, 6) + '" period="' + f(lper, 6) +
            '" phase="' + f(f32(pay, 58), 6) + '"/>';
          if (presets.length) presets[presets.length - 1].lights.push(lightStr);
          else rep.unknown.push("light record without preceding preset");
        } else if (rid === 0xFC && pay.length >= 2) {          // 航司代码表（2024）：u16 条数 + N × (4 字符代码 + 4 字节)
          var fcN = u16(pay, 0), fcCodes = [];
          for (var fk = 0; fk < fcN; fk++) {
            if (2 + fk * 8 + 4 > pay.length) break;
            var fcSlot = pay.subarray(2 + fk * 8, 2 + fk * 8 + 4);
            var fcd = "";
            for (var fi = 0; fi < fcSlot.length; fi++) if (fcSlot[fi] !== 0) fcd += String.fromCharCode(fcSlot[fi]);
            fcd = fcd.trim();
            if (fcd) fcCodes.push(fcd);
          }
          rep.counts.airline_code_table = (rep.counts.airline_code_table || 0) + 1;
          if (!rep.airline_codes) rep.airline_codes = [];
          rep.airline_codes = rep.airline_codes.concat(fcCodes);
          if (!rep.decoded_notes) rep.decoded_notes = [];
          rep.decoded_notes.push("航司代码表(0xFC): " + fcCodes.join(", ") + "（记录里没有逐机位的引用字段，故不写入 XML）");
        } else if (rid === 0xE9 && pay.length >= 10) {          // 地面合并明暗阈值（Airport 的两个属性）
          // Airport._dispatch_child：ctype 233 → bright = f32(body, 8)、dark = f32(body, 12)（我方载荷 +2 / +6）
          rep.counts.ground_merging = (rep.counts.ground_merging || 0) + 1;
          ap.gm_bright = f32(pay, 2);
          ap.gm_dark = f32(pay, 6);
        } else if (rid === 0x66 && pay.length >= 10) {          // 塔台 Tower
          var tflags = pay[2], tisz = u16(pay, 6);
          rep.counts.tower++;
          if (u16(pay, 4) === 0x0B && tisz >= 64 && tisz <= pay.length - 4) {
            var trec = pay.subarray(4, 4 + tisz), tsc = f32(trec, 60);
            nodes.push('\t\t<Tower>\n' +
              '\t\t\t<SceneryObject ' + sceneryBase(trec) + '\n' +
              '\t\t\t\t<LibraryObject name="' + guid(trec.subarray(44, 60)) + '" scale="' +
              f((tsc > 0.001 && tsc < 100 ? tsc : 1.0), 6) + '"/>\n\t\t\t</SceneryObject>\n\t\t</Tower>');
          } else if (pay.length >= 28) {                        // 默认塔台：直接给经纬高
            var dv = new DataView(pay.buffer, pay.byteOffset + 4);
            var talt = dv.getFloat64(16, true);
            // 高度按对照语义量化到 float32 再以 double 输出
            talt = Math.fround(talt);
            // flags bit0 = 默认塔台、bit1..3 = 尺寸覆盖
            nodes.push('\t\t<Tower lat="' + f(dv.getFloat64(0, true), 14) +
              '" lon="' + f(dv.getFloat64(8, true), 14) + '" alt="' + f(talt, 14) +
              '" overrideSize="' + (TOWER_SIZE[(tflags >> 1) & 3] || "NONE") + '" overrideLevel="' + pay[3] + '"/>');
          } else rep.unknown.push("tower record without embedded object");
        } else if (rid === 0x26 && pay.length >= 30) {          // 直升机坪 Helipad
          var tcode = pay[1] & 0x0F;
          var hrl = lonlat(u32(pay, 6), u32(pay, 10));
          rep.counts.helipad++;
          nodes.push('\t\t<Helipad lat="' + f(hrl[1], 14) + '" lon="' + f(hrl[0], 14) + '" alt="' +
            f(i32(pay, 14) / 1000.0, 3) + '" surface="' + (SURFACE_TYPE[pay[0]] || "CONCRETE") +
            '" heading="' + f(f32(pay, 26), 6) + '" length="' + f(u32(pay, 18) / 100.0, 3) +
            '" width="' + f(u32(pay, 22) / 100.0, 3) + '" type="' + (HELIPAD_TYPE[tcode] || "SQUARE") +
            '" closed="' + (((pay[1] >> 5) & 1) ? "TRUE" : "FALSE") +
            '" transparent="' + (((pay[1] >> 4) & 1) ? "TRUE" : "FALSE") +
            '" red="' + pay[4] + '" green="' + pay[3] + '" blue="' + pay[2] + '"/>');
        } else if (rid === 0x5D && pay.length >= 18) {          // 机场 archetype（一个 GUID，2024 专有元素）
          rep.counts.archetype++;
          if (!is2020) {
            nodes.push('\t\t<AirportArchetype archetypeGUID="' + guid(pay.subarray(2, 18)) + '"/>');
            archOpen = nodes.length - 1;
          }
        } else if (rid === 0x5C && pay.length >= 14) {          // archetype 参数覆盖（u16 + 参数名哈希 + f32 值）
          rep.counts.archParam = (rep.counts.archParam || 0) + 1;
          if (is2020) {
            // 2020 没有 AirportArchetype 元素，整条丢弃
          } else if (archOpen < 0) {
            rep.counts.archParamOrphan = (rep.counts.archParamOrphan || 0) + 1;
          } else {
            var av = f32(pay, 10);
            if (!(av === 0 || (Math.abs(av) >= 1e-6 && Math.abs(av) <= 1e6))) {
              av = 0;
              rep.counts.archParamJunk = (rep.counts.archParamJunk || 0) + 1;
            }
            if (!archOver[archOpen]) archOver[archOpen] = [];
            archOver[archOpen].push('\n\t\t\t<ParamOverride name="0x' + u64hex(pay, 2) +
              '" value="' + fmtF32(av) + '"/>');
          }
        } else if (rid === 0x33 && pay.length >= 6) {          // 机场删除标志 DeleteAirport
          // +0 u16 标志位 0-11 · +2/+3/+4 跑道/入口/频率计数 · +5 u8 标志位 0-7（映射到 32-39）
          var bits = u16(pay, 0) + pay[5] * 4294967296;
          var attrs = [];
          DEL_FLAGS.forEach(function (pair) {
            var on = (bits / Math.pow(2, pair[1])) % 2 >= 1;
            attrs.push(pair[0] + '="' + (on ? "TRUE" : "FALSE") + '"');
          });
          delAirport[0] = '\t\t<DeleteAirport ' + attrs.join(" ") + '/>';
        } else if (rid === 0x31) {                             // 停机坪边灯
          var spacing = f32(pay, 14);
          var runsE = vertexRuns(pay, [ap.lon, ap.lat]);
          vert = runsE.length ? runsE[0] : [];
          name = vert.length ? stripZeros(cstr(pay, 18 + vert.length * 8)) : "";
          body = vert.map(function (v) { return '\n\t\t\t<Vertex lat="' + f(v[2], 14) + '" lon="' + f(v[1], 14) + '"/>'; }).join("");
          rep.counts.edge_lights++; rep.counts.vertex += vert.length;
          // 2020/2024 两版 bglcomp.xsd 的 ctEdgeLights 都只认 preset（无 type/name）
          edgeNodes.push('\t\t\t<EdgeLights preset="' + xesc(name) + '" spacing="' + f(spacing, 6) + '">' + body + '\n\t\t\t</EdgeLights>');
          edgeGroups.push(classifyEdgeLights(name));
        } else if (rid === 0xDE) {                             // 登机桥 Jetway
          var pnum = u16(pay, 0);
          rl = lonlat(u32(pay, 16), u32(pay, 20));
          var jhdg = u16(pay, 34) * 360.0 / 65536.0;
          var jtitle = "", jscale = 1.0, jinner = null;
          // 载荷 +12 起是 1~2 条内嵌 SceneryObject 记录（每条 u16 id + u16 size，size 含 4 字节头），
          // 0x1D = SimObject 容器、0x0B = LibraryObject，各自带自己的对象属性
          var jkids = [], jpos = 12;
          while (jpos + 4 <= pay.length) {
            var jcsz = u16(pay, jpos + 2);
            if (jcsz < 4 || jpos + jcsz > pay.length) break;
            jkids.push(pay.subarray(jpos, jpos + jcsz));
            jpos += jcsz;
          }
          if (jkids.length) {
            jinner = jkids[0];
          } else if (pay.length >= 76 && u16(pay, 12) === 0x19) {
            var isz = u32(pay, 8);
            if (isz >= 64 && isz <= pay.length - 12) jinner = pay.subarray(12, 12 + isz);
          }
          if (jinner) {
            var so = simObject(jinner);
            var sn = simName(jinner);
            jtitle = (sn !== null) ? sn : so.title;
            jscale = so.scale;
          } else if (pay.length >= 94) {
            var nlen = u32(pay, 88);
            if (nlen > 0 && nlen <= Math.min(64, pay.length - 94)) {
              jtitle = UTF8.decode(pay.subarray(94, 94 + nlen)).replace(/\u0000+$/g, "");
            }
            var sc = f32(pay, 84);
            jscale = (sc > 0.001 && sc < 100) ? sc : 1.0;
          }
          rep.counts.jetway++;
          var jbody = [];
          jkids.forEach(function (child) {
            var cbase = sceneryBase(child);
            if (u16(child, 0) === 0x0B && child.length >= 64) {
              var csc = f32(child, 60);
              jbody.push('<SceneryObject' + cbase +
                '\n\t\t\t\t<LibraryObject name="' + guid(child.subarray(44, 60)) +
                '" scale="' + f(((csc > 0.001 && csc < 100) ? csc : 1.0), 6) + '"/>\n\t\t\t</SceneryObject>');
              rep.counts.library_object = (rep.counts.library_object || 0) + 1;
            } else {
              var cso = simObject(child);
              var cn = simName(child);
              jbody.push('<SceneryObject' + cbase +
                '\n\t\t\t\t<SimObject containerTitle="' + xesc(cn !== null ? cn : cso.title) +
                '" scale="' + f(cso.scale, 6) + '"/>\n\t\t\t</SceneryObject>');
            }
          });
          if (!jbody.length) {
            jbody.push('<SceneryObject lat="' + f(rl[1], 14) + '" lon="' + f(rl[0], 14) +
              '" alt="0.00000000000000" pitch="0.000000" bank="0.000000" heading="' + f(jhdg, 6) +
              '" imageComplexity="VERY_SPARSE" altitudeIsAgl="TRUE" snapToGround="TRUE" snapToNormal="FALSE">' +
              '\n\t\t\t\t<SimObject containerTitle="' + xesc(jtitle) + '" scale="' + f(jscale, 6) +
              '"/>\n\t\t\t</SceneryObject>');
          }
          jetwayNodes.push('\t\t<Jetway gateName="' + (PARK_NAME[u16(pay, 2)] || "NONE") + '" parkingNumber="' + pnum +
            '" suffix="' + (PARK_NAME[u16(pay, 4)] || "NONE") + '">\n\t\t\t' + jbody.join('\n\t\t\t') +
            '\n\t\t</Jetway>');
        } else if (rid === 0x104 && pay.length >= 76) {        // VDGS 目标停机位（载荷 78 字节）
          // 载荷 +0 u16 机位号、+2 u16 gateName、+4 u16 suffix、
          // +6 u32 常量 0x400000、+8 u32 内嵌记录长度（64），载荷 +12 起是内嵌 SimObject 记录
          var vdNum = u16(pay, 0);
          var vdGate = PARK_NAME[u16(pay, 2)] || "NONE";
          var vdSuf = PARK_NAME[u16(pay, 4)] || "NONE";
          if (SUFFIX_OK.indexOf(vdSuf) < 0) vdSuf = "NONE";
          var vdInner = pay.subarray(12, 76);
          var vdBase = sceneryBase(vdInner);
          var vdSo = simObject(vdInner);
          var vdTitle = simName(vdInner);
          if (vdTitle === null) vdTitle = vdSo.title;
          rep.counts.vdgs = (rep.counts.vdgs || 0) + 1;
          nodes.push('\t\t<VDGS gateName="' + vdGate + '" parkingNumber="' + vdNum + '" suffix="' + vdSuf + '">\n' +
            '\t\t\t<SceneryObject' + vdBase + '\n' +
            '\t\t\t\t<SimObject containerTitle="' + xesc(vdTitle) + '" scale="' + f(vdSo.scale, 6) + '"/>\n' +
            '\t\t\t</SceneryObject>\n\t\t</VDGS>');
        } else if (rid === 0xE8 && pay.length >= 74 && u16(pay, 8) === 0x0B) {   // 投影网格
          pmAdd(pay, rep, apObjNodes);
        } else if (rid === 0x56) {   // 投影网格重复表：90 字节头 + N 条「id 0xE8 / 80 字节」子记录
          var p56 = 90, n56 = 0;
          while (p56 + 6 <= pay.length) {
            var sid56 = u16(pay, p56), ssz56 = u32(pay, p56 + 2);
            if (ssz56 < 6 || p56 + ssz56 > pay.length) break;
            if (sid56 === 0xE8 && ssz56 >= 80 && u16(pay, p56 + 6 + 8) === 0x0B) {
              if (pmAdd(pay.subarray(p56 + 6, p56 + ssz56), rep, apObjNodes)) n56++;
            } else if (sid56 === 0xD4 && ssz56 === 8) {
              break;                     // 表结束标记
            } else {
              rep.unknown.push("0x56 子记录 id 0x" + ("0000" + sid56.toString(16)).slice(-4) + " size " + ssz56);
            }
            p56 += ssz56;
          }
          if (n56) rep.counts.projected_mesh_dup = (rep.counts.projected_mesh_dup || 0) + n56;
        } else if (rid === 0x118 && pay.length >= 18) {   // 顶点多边形（GUID + N×(lat f64, lon f64, f32)）
          var pn18 = u16(pay, 0);
          if (pn18 && pay.length >= 18 + pn18 * 20) {
            var las18 = [], los18 = [], vals18 = [], dv18 = new DataView(pay.buffer, pay.byteOffset, pay.byteLength);
            for (var i18 = 0; i18 < pn18; i18++) {
              las18.push(dv18.getFloat64(18 + i18 * 20, true));
              los18.push(dv18.getFloat64(26 + i18 * 20, true));
              vals18.push(f32(pay, 34 + i18 * 20));
            }
            rep.counts.poly118 = (rep.counts.poly118 || 0) + 1;
            if (!rep.decoded_notes) rep.decoded_notes = [];
            rep.decoded_notes.push("0x118 顶点多边形：GUID " + guid(pay.subarray(2, 18)) + "、" + pn18 +
              " 顶点、lat " + f(Math.min.apply(null, las18), 7) + ".." + f(Math.max.apply(null, las18), 7) +
              "、lon " + f(Math.min.apply(null, los18), 7) + ".." + f(Math.max.apply(null, los18), 7) +
              "、每顶点第 4 列 f32 " + f(Math.min.apply(null, vals18), 3) + ".." + f(Math.max.apply(null, vals18), 3));
          } else {
            rep.unknown.push("0x118 顶点数 " + pn18 + " 与长度 " + pay.length + " 不符");
          }
        } else if (rid === 0x5A && pay.length >= 42) {         // 矢量放置 / 围栏
          var vcnt = u16(pay, 0), prof = guid(pay.subarray(2, 18));
          var vspacing = f32(pay, 18), vheading = f32(pay, 22), vscale = f32(pay, 26), vdelta = f32(pay, 30);
          // 旋转量是 u32（@+34）；只有已知的 112/624 输出 Follow edge，其余输出原数字
          var vrotRaw = u32(pay, 34);
          var vrot = (vrotRaw === 112 || vrotRaw === 624) ? "Follow edge" : String(vrotRaw);
          var vbody = "";
          var made = 0;
          for (var kv = 0; kv < vcnt; kv++) {
            var ov = 42 + kv * 16;
            if (ov + 16 > pay.length) break;
            var dv = new DataView(pay.buffer, pay.byteOffset + ov);
            var vla = dv.getFloat64(0, true), vlo = dv.getFloat64(8, true);
            vbody += '\n\t\t\t<Vertex lat="' + f(vla, 14) + '" lon="' + f(vlo, 14) + '"/>';
            made++;
          }
          if (made >= 2) {
            rep.counts.vector_placement++; rep.counts.vertex += made;
            nodes.push('\t\t<VectorPlacement profile="' + prof + '" spacing="' + f(vspacing, 6) +
              '" heading="' + f(vheading, 6) + '" scale="' + f(vscale, 6) + '" scaleDelta="' + f(vdelta, 6) +
              '" rotation="' + xesc(vrot) + '" avoidDiscontinuity="TRUE" adjustScalingAlongPath="TRUE">' +
              vbody + '\n\t\t</VectorPlacement>');
          } else rep.unknown.push("vector placement with <2 vertices");
        } else if (rid === 0xD9) {                             // 跑道标志牌 TaxiwaySign
          rl = lonlat(u32(pay, 2), u32(pay, 6));
          var szc = pay.length > 14 ? pay[14] : 0, jst = pay.length > 15 ? pay[15] : 0;
          var lbl = pay.length > 16 ? cstr(pay, 16).replace(/\u0000+$/, "") : "";
          rep.counts.taxiway_sign++;
          nodes.push('\t\t<TaxiwaySign lat="' + f(rl[1], 14) + '" lon="' + f(rl[0], 14) + '" heading="' + f(f32(pay, 10), 6) +
            '" label="' + xesc(lbl) + '" justification="' + (jst ? "RIGHT" : "LEFT") + '" size="SIZE' + szc + '"/>');
        } else if (rid === 0x57 && pay.length >= 46) {         // 灯光支座 LightSupport
          var dvS = new DataView(pay.buffer, pay.byteOffset + 2);
          var laS = dvS.getFloat64(0, true), loS = dvS.getFloat64(8, true);
          var alS = dvS.getFloat64(16, true), al2S = dvS.getFloat64(24, true);
          var lsFlags = u16(pay, 0);
          rep.counts.light_support++;
          nodes.push('\t\t<LightSupport latitude="' + f(laS, 14) + '" longitude="' + f(loS, 14) +
            '" altitude="' + f(alS, 14) + '" altitude2="' + f(al2S, 14) + '" heading="' + f(f32(pay, 34), 6) +
            '" width="' + f(f32(pay, 38), 6) + '" length="' + f(f32(pay, 42), 6) +
            '" excludeLights="' + tf(lsFlags & 1) + '" excludeLightObjects="' + tf(lsFlags & 2) + '"/>');
        } else if (rid === 0x1D) {                             // 滑行道名称表
          var cntN = u32(pay, 0), namesN = [];
          for (var iN = 1; iN < cntN; iN++) {
            var offN = 10 + (iN - 1) * 8;
            if (offN + 8 > pay.length) break;
            namesN.push(UTF8.decode(pay.subarray(offN, offN + 8)).split("\u0000")[0]);
          }
          namesN.forEach(function (nm, k) { nodes.push('\t\t<TaxiName index="' + (k + 1) + '" name="' + xesc(nm) + '"/>'); });
          rep.taxinames = namesN;
        } else {
          var key = "0x" + ("0000" + rid.toString(16)).slice(-4) + "/" + pay.length;
          if (!rep.unknownSamples) rep.unknownSamples = {};
          if (!rep.unknownSamples[key]) rep.unknownSamples[key] = Array.prototype.map.call(
            pay.subarray(0, 32), function (x) { return hex2(x); }).join(" ");
          rep.unknown.push("airport sub-record id 0x" + ("0000" + rid.toString(16)).slice(-4) + " size " + pay.length);
        }
      });
    });

    // ---------------- 机场元数据（section 0x35） ----------------
    var metaVals = null;
    g.dataOf(SECTION_META).forEach(function (pair) {
      var blob = pair[0], vals = [];
      for (var k = 0; k < 6; k++) {
        var off = u32(blob, 0x12 + k * 4) + 4;
        if (off > 0 && off < blob.length) vals.push(cstr(blob, off).replace(/\u0000+$/, ""));
      }
      metaVals = vals;
    });
    if (metaVals && metaVals.length) {
      var mv = metaVals.concat(["", "", "", ""]).slice(0, 4);
      ap.short = mv[0]; ap.country = mv[1]; ap.state = mv[2]; ap.city = mv[3];
      if (metaVals.length > 4 && metaVals[4]) ap.name = ap.name || metaVals[4];
      rep.meta = metaVals;
    }

    // ---------------- 景物对象（section 0x25） ----------------
    g.dataOf(SECTION_OBJECTS).forEach(function (pair) {
      var blob = pair[0], pos = 0;
      while (pos + 4 <= blob.length) {
        var rid = u16(blob, pos), sz = u16(blob, pos + 2);
        if (sz < 4 || pos + sz > blob.length) break;
        var rec = blob.subarray(pos, pos + sz);
        if (sz >= 64 || (rid === 0x19 && sz >= 56)) {
          var head = '\t<SceneryObject' + sceneryBase(rec) + '\n';
          if (rid === 0x19) {                                  // 容器对象（SimObject）
            var so2 = simObject(rec);
            objs.push(head + '\t\t<SimObject containerTitle="' + xesc(so2.title) + '" scale="' + f(so2.scale, 6) +
              '"/>\n\t</SceneryObject>');
            rep.counts.sim_object++;
          } else if (rid === 0x18 || sz > 92) {
            var pole = sz >= 80 ? f32(rec, 72) : 4.572, sock = sz >= 80 ? f32(rec, 76) : 2.7432;
            objs.push(head + '\t\t<Windsock poleHeight="' +
              f((pole > 0.5 && pole < 30 ? pole / 0.3048 : 15.0), 6) + '" sockLength="' +
              f((sock > 0.3 && sock < 10 ? sock / 0.3048 : 9.0), 6) + '"' +
              '' + '/>\n\t</SceneryObject>');
            rep.counts.windsock++;
          } else {
            var scale = f32(rec, 60);
            objs.push(head + '\t\t<LibraryObject name="' + guid(rec.subarray(44, 60)) + '" scale="' +
              f((scale > 0.001 && scale < 100 ? scale : 1.0), 6) + '"/>\n\t</SceneryObject>');
            rep.counts.library_object++;
          }
        }
        pos += sz;
      }
    });
    rep.objects = objs.length;

    if (!ap.ident) {
      var base = String(sourceName).replace(/\\/g, "/").split("/").pop();
      ap.ident = base.split(".")[0].toUpperCase();
    }

    // 导航台（section 0x13）：按机场 + 跑道号 + 方位挂到跑道上
    var unattachedIls = attachIls(g, runwayMeta, nodes, rep);

    // 跑道入口：对照解析程序按 号+方位 与跑道主/次端比对；命中则作为该跑道的 <RunwayStart>，
    // 否则（类型非 1 或没有对应跑道）输出机场级的 <Start>
    var startLines = {};
    pendingStarts.forEach(function (item) {
      var spos = item[0], spay = item[1];
      var end = null, hit = null;
      if (spay.length >= 18 && ((spay[1] >> 4) & 0x0F) === 1) {
        var snum = RUNWAY_NUMBER_ENUM[spay[0]] || "00";
        var sdesig = DESIGNATOR_ENUM[spay[1] & 0x0F] || "NONE";
        for (var k = 0; k < runwayMeta.length; k++) {
          var rw = runwayMeta[k];
          if (rw.priNum === snum && rw.priDesig === sdesig) { end = "PRIMARY"; hit = rw; break; }
          if (rw.secNum === snum && rw.secDesig === sdesig) { end = "SECONDARY"; hit = rw; break; }
        }
      }
      var sll = lonlat(u32(spay, 2), u32(spay, 6));
      if (end === null) {
        // type 0 = 未指定；stStart 只有 TRACK/RUNWAY/HELIPAD/WATER，此时省略 type
        rep.startUnmatched = (rep.startUnmatched || 0) + 1;
        var stype = (spay[1] >> 4) & 0x0F;
        nodes[spos] = ('\t\t<Start number="' + (RUNWAY_NUMBER_ENUM[spay[0]] || "00") + '" designator="' +
          (DESIGNATOR_ENUM[spay[1] & 0x0F] || "NONE") + '" lat="' + f(sll[1], 14) + '" lon="' + f(sll[0], 14) +
          '" alt="' + f(navAlt(i32(spay, 10)), 14) + '" heading="' + f(f32(spay, 14), 6) + '"' +
          (stype > 0 && START_TYPE[stype] ? ' type="' + START_TYPE[stype] + '"' : "") + '/>');
        return;
      }
      if (!startLines[hit.node]) startLines[hit.node] = [];
      startLines[hit.node].push('\n\t\t\t<RunwayStart end="' + end + '" lat="' + f(sll[1], 14) + '" lon="' + f(sll[0], 14) +
        '" alt="' + f(navAlt(i32(spay, 10)), 14) + '" heading="' + f(f32(spay, 14), 14) + '"/>');
    });
    Object.keys(startLines).forEach(function (nodeI) {
      nodes[nodeI] = nodes[nodeI].replace(START_SLOT, startLines[nodeI].join("") + START_SLOT);
    });

    // 跑道子元素若出现在跑道之后，补挂到最后一条跑道上
    if (rwChildren.length) {
      for (var ri = nodes.length - 1; ri >= 0; ri--) {
        if (nodes[ri].indexOf("<Runway ") >= 0) {
          nodes[ri] = nodes[ri].replace("\n\t\t</Runway>", rwChildren.join("") + "\n\t\t</Runway>");
          break;
        }
      }
      rwChildren.length = 0;
    }

    // 清掉未被填写的槽位（没有 Ils / RunwayStart 的跑道）
    for (var si = 0; si < nodes.length; si++) {
      if (nodes[si].indexOf(ILS_SLOT) >= 0 || nodes[si].indexOf(START_SLOT) >= 0)
        nodes[si] = nodes[si].split(ILS_SLOT).join("").split(START_SLOT).join("");
    }

    // archetype 参数覆盖：把自闭合的 <AirportArchetype/> 展开成带子元素的节点
    Object.keys(archOver).forEach(function (k) {
      var n = nodes[k | 0];
      if (n && n.slice(-2) === "/>") nodes[k | 0] = n.slice(0, -2) + ">" + archOver[k].join("") + "\n\t\t</AirportArchetype>";
    });

    // ---------------- 分组：7 个景物顶层组 + 机场组(8) + 13 个子组(9..21) ----------------
    assignAirportGroups([nodes, apronNodes, paintedNodes, edgeNodes, jetwayNodes, apObjNodes, objs], {});
    assignSceneryGroups(objs);

    // ---------------- 机场元数据（section 0x2C FsAirportSummary） ----------------
    var sumBlobs = g.dataOf(0x2C);
    for (var sb = 0; sb < sumBlobs.length; sb++) {
      var sblob = sumBlobs[sb][0];
      if (sblob.length < 44) continue;
      if (!ap.identFromAirport) ap.ident = icao(u32(sblob, 20)) || ap.ident;
      ap.lon = navLon(i32(sblob, 8));
      ap.lat = navLat(i32(sblob, 12));
      ap.alt = navAlt(i32(sblob, 16));
      if (!ap.identFromAirport) ap.magvar = f32(sblob, 28);
      rep.counts.summary = (rep.counts.summary || 0) + 1;
      break;
    }

    // ---------------- 名称表（section 0x27 FsNameList）：区域/国家/省/市/机场名 ----------------
    var nameBlobs = g.dataOf(0x27);
    for (var nb = 0; nb < nameBlobs.length; nb++) {
      var nblob = nameBlobs[nb][0];
      if (nblob.length < 20) continue;
      var countsN = [], k2, totalN = 0;
      for (k2 = 0; k2 < 6; k2++) { countsN.push(u16(nblob, 6 + 2 * k2)); totalN += countsN[k2]; }
      var offsN = [];
      for (k2 = 0; k2 < totalN; k2++) offsN.push(u32(nblob, 18 + 4 * k2));
      var posN = 0, groupsN = [];
      for (k2 = 0; k2 < countsN.length; k2++) {
        var grp = [];
        for (var g2 = posN; g2 < posN + countsN[k2]; g2++) grp.push(cstr(nblob, offsN[g2] + 4));
        groupsN.push(grp);
        posN += countsN[k2];
      }
      var okN = function (s) { return !!s && s.length >= 2 && !/[\u0000-\u001f]/.test(s); };
      var candN = [];
      for (k2 = 0; k2 < 4; k2++) candN.push(groupsN.length > k2 && groupsN[k2].length ? groupsN[k2][0] : "");
      if (okN(candN[1])) {
        var keysN = ["short", "country", "state", "city"];
        for (k2 = 0; k2 < 4; k2++) if (okN(candN[k2]) && !ap[keysN[k2]]) ap[keysN[k2]] = candN[k2];
      } else if (!ap.short && !ap.country) {
        var wordsN = [], pN = 0;
        while (pN < nblob.length) {
          if (nblob[pN] >= 0x20) {
            var qN = pN;
            while (qN < nblob.length && nblob[qN] >= 0x20) qN++;
            var sN = UTF8.decode(nblob.subarray(pN, qN));
            if (sN.length >= 2) wordsN.push(sN);
            pN = qN;
          } else pN++;
        }
        if (wordsN.length >= 4) {
          ap.short = wordsN[0]; ap.country = wordsN[1]; ap.state = wordsN[2]; ap.city = wordsN[3];
        }
      }
      rep.counts.namelist = (rep.counts.namelist || 0) + 1;
      break;
    }

    // ---------------- 输出 ----------------
    var out = [];
    out.push('<?xml version="1.0"?>');
    out.push('<FSData version="9.0">');
    var apName = ap.name || ap.short || "";
    var gmAttrs = "";
    if (ap.gm_bright) gmAttrs += ' groundMergingTransfertBright="' + f(ap.gm_bright, 6) + '"';
    if (ap.gm_dark) gmAttrs += ' groundMergingTransfertDark="' + f(ap.gm_dark, 6) + '"';
    groupElementsXml("\t").forEach(function (n) { out.push(n); });
    out.push('\t<Airport displayName="' + xesc(apName) + '" groupIndex="' + AIRPORT_GROUP_INDEX +
      '" groupID="' + AIRPORT_GROUP_ID + '" groupGenerated="FALSE" ' +
      'name="' + xesc(apName) + '" ident="' + xesc(ap.ident) + '" lat="' + f(ap.lat, 14) + '" lon="' + f(ap.lon, 14) +
      '" alt="' + f(ap.alt, 14) + '" magvar="' + f(ap.magvar || 0.0, 6) + '"' +
      (ap.traffic ? ' trafficScalar="' + f(ap.traffic, 6) + '"' : "") + ' ' +
      'airportTestRadius="3000.00000000000000"' + ((ap.flatten === undefined ? true : ap.flatten) ? ' applyFlatten="TRUE"' : "") +
      ' isOnTIN="' + tf(ap.tin === undefined ? false : ap.tin) + '" tinColorCorrection="TRUE" ' +
      'starAirport="' + tf(ap.star === undefined ? true : ap.star) + '"' + gmAttrs + '>');
    airportSubGroupXml().forEach(function (n) { out.push(n); });
    out.push('\t\t<TaxiName index="0" name=""/>');
    nodes.forEach(function (n) { out.push(n); });
    if (ap.fuel_mask) servicesElements(ap.fuel_mask).forEach(function (n) { out.push(n); });
    jetwayNodes.forEach(function (n) { out.push(n); });
    if (edgeNodes.length) {
      out.push('\t\t<ApronEdgeLights>');
      edgeNodes.forEach(function (n) { out.push(n); });
      out.push('\t\t</ApronEdgeLights>');
    } else {
      out.push('\t\t<ApronEdgeLights/>');
    }
    if (apronNodes.length) {
      out.push('\t\t<Aprons>');
      apronNodes.forEach(function (n) { out.push(n); });
      out.push('\t\t</Aprons>');
    }
    if (paintedNodes.length) {
      out.push('\t\t<PaintedElements>');
      paintedNodes.forEach(function (n) { out.push(n); });
      out.push('\t\t</PaintedElements>');
    }
    presets.forEach(function (p) {
      rep.counts.light_preset++;
      out.push('\t\t<LightPreset name="' + xesc(p.name) + '" phase="' + f(p.phase, 6) + '" mesh="' + p.mesh + '">');
      p.lights.forEach(function (lt) { out.push(lt); rep.counts.light++; });
      out.push('\t\t</LightPreset>');
    });
    if (delAirport[0]) out.push(delAirport[0]);
    unattachedIls.forEach(function (n) { out.push(n); });
    apObjNodes.forEach(function (n) { out.push(n); });
    out.push('\t</Airport>');
    objs.forEach(function (n) { out.push(n); });
    cvxElements(g, rep).forEach(function (n) { out.push(n); });
    exclusionElements(g, rep).forEach(function (n) { out.push(n); });
    ndbElements(g, rep).forEach(function (n) { out.push(n); });
    waypointElements(g, rep).forEach(function (n) { out.push(n); });
    landmarkElements(g, rep).forEach(function (n) { out.push(n); });
    out.push('</FSData>');
    rep.profile = is2020 ? "2020" : "2024";
    rep.airport = ap;
    // 未解码记录去重（同一条重复出现只报一次，附次数）
    var seen = {}, uniq = [];
    rep.unknown.forEach(function (m) {
      if (seen[m]) seen[m]++;
      else { seen[m] = 1; uniq.push(m); }
    });
    rep.unknown = uniq.map(function (m) { return seen[m] === 1 ? m : m + " ×" + seen[m]; });
    return { xml: out.join("\n") + "\n", rep: rep };
  }

  function summarize(rep) {
    var c = rep.counts, ap = rep.airport || {};
    var lines = [
      "机场: " + (ap.name || "") + " (" + (ap.ident || "") + ")  " + (ap.short || "") + " / " + (ap.state || "") + " / " + (ap.city || ""),
      "参考点: lat " + Number(ap.lat || 0).toFixed(7) + "  lon " + Number(ap.lon || 0).toFixed(7) + "  alt " + Number(ap.alt || 0).toFixed(3) + " m",
      "跑道 " + c.runway + " | 入口 " + c.start + " | COM " + c.com + " | 滑行道点 " + c.taxiway_point +
      " | 滑行道路径 " + c.taxiway_path + " | 机位 " + c.parking + " | 停机坪 " + c.apron + " | 画线 " + c.painted_line +
      " | 边灯 " + c.edge_lights + " | 标志牌 " + c.taxiway_sign + " | 灯支座 " + c.light_support + " | 登机桥 " + c.jetway +
      " | 围栏 " + c.vector_placement + " | 内嵌模型 " + c.airport_object + " | 顶点 " + c.vertex,
      "景物对象: " + rep.objects + "（库对象 " + c.library_object + " + 风向袋 " + c.windsock + "）",
      "CVX 矢量: 多边形 " + (c.cvx_polygon || 0) + " | 矩形/高度图 " + (c.cvx_rectangle || 0)
    ];
    var uniq = rep.unknown.filter(function (v, i, a) { return a.indexOf(v) === i; }).sort();
    if (c.projected_mesh_dup) {
      lines.push("投影网格重复表（0x56 内嵌 0xE8 子记录）：" + c.projected_mesh_dup + " 条");
    }
    if (c.archParam) {
      lines.push("Archetype 参数覆盖（ParamOverride）：" + c.archParam + " 条" +
        (c.archParamOrphan ? "，其中 " + c.archParamOrphan + " 条未找到所属 archetype" : "") +
        (c.archParamJunk ? "，" + c.archParamJunk + " 条参数值取自未初始化内存（已按 0 输出）" : ""));
    }
    if (rep.startUnmatched) lines.push("入口未匹配到跑道（已按对照解析程序规则输出为机场级 <Start>）：" + rep.startUnmatched + " 条");
    if (rep.counts.text_marking) lines.push("文字标记（TextMarking）：" + rep.counts.text_marking + " 条");
    if (rep.counts.mast_light) lines.push("灯柱（MastLight，0xFB 推测映射）：" + rep.counts.mast_light + " 条");
  if (rep.counts.wasm_module) lines.push("WASM 模块声明（0x0102）：" + rep.counts.wasm_module + " 条");
    if (rep.parkSuffixBad) lines.push("机位 suffix 值无合法枚举（N/PARKING 类，已按 NONE 输出）：" + rep.parkSuffixBad + " 条");
    (rep.decoded_notes || []).forEach(function (note) { lines.push("已解码但未写入 XML：" + note); });
    if (uniq.length) {
      lines.push("未解码记录 " + uniq.length + " 类：");
      uniq.forEach(function (u) { lines.push("  - " + u); });
      var smp = rep.unknownSamples || {};
      Object.keys(smp).sort().forEach(function (k) {
        var parts = k.split("/");
        var hit = uniq.some(function (u) {
          return u.indexOf("id " + parts[0] + " size " + parts[1]) >= 0;
        });
        if (hit) lines.push("    " + k + " 载荷样例: " + smp[k]);
      });
    }
    return lines.join("\n");
  }

  function reportText(rep, info) {
    var inf = info || {}, c = rep.counts || {};
    var bar = new Array(75).join("="), thin = new Array(75).join("-");
    function p2(n) { return (n < 10 ? "0" : "") + n; }
    var d = new Date();
    var now = d.getFullYear() + "-" + p2(d.getMonth() + 1) + "-" + p2(d.getDate()) + " " +
              p2(d.getHours()) + ":" + p2(d.getMinutes()) + ":" + p2(d.getSeconds());
    function num(n) { return String(n || 0).replace(/\B(?=(\d{3})+(?!\d))/g, ","); }
    var out = [
      bar,
      "BGL 机场反编译器 v" + VERSION + "  诊断报告",
      bar,
      "生成时间   : " + now + "（本机时间）",
      "工具版本   : " + VERSION + (inf.runtime ? " (" + inf.runtime + ")" : ""),
      "输出配置   : profile=" + (inf.profile || rep.profile || "") + "  ident=" + (inf.ident || "（未指定）")
    ];
    if (inf.source) { out.push("输入文件   : " + inf.source); out.push("文件大小   : " + num(inf.size) + " 字节"); }
    if (inf.sha256) out.push("SHA-256    : " + inf.sha256);
    if (inf.md5) out.push("MD5        : " + inf.md5);
    if (inf.output) {
      out.push("输出文件   : " + inf.output);
      if (inf.outSize) out.push("输出大小   : " + num(inf.outSize) + " 字节");
    }
    out.push(thin, "【机场摘要】", summarize(rep));
    var recs = rep.records || {}, keys = Object.keys(recs);
    if (keys.length) {
      var tot = 0;
      keys.forEach(function (k) { tot += recs[k]; });
      keys.sort(function (a, b) { return recs[b] - recs[a] || (a < b ? -1 : 1); });
      out.push(thin, "【子记录统计】共 " + tot + " 条记录，" + keys.length + " 种 id（按次数降序）");
      keys.forEach(function (k) {
        var s2 = "  " + k;
        while (s2.length < 12) s2 += " ";
        var s3 = "" + recs[k];
        while (s3.length < 6) s3 = " " + s3;
        out.push(s2 + " " + s3);
      });
    }
    var uniq = (rep.unknown || []).filter(function (v, i, a) { return a.indexOf(v) === i; }).sort();
    out.push(thin);
    if (uniq.length) {
      out.push("【未解码记录明细】" + uniq.length + " 类");
      var smp = rep.unknownSamples || {};
      uniq.forEach(function (u, i) {
        out.push("  " + (i + 1) + ". " + u);
        Object.keys(smp).sort().forEach(function (key) {
          var parts = key.split("/");
          if (u.indexOf("id " + parts[0] + " size " + parts[1]) >= 0) out.push("     载荷样例: " + smp[key]);
        });
      });
    } else {
      out.push("【未解码记录明细】无 —— 所有子记录都已识别");
    }
    out.push(thin, "提示：请把本文件（以及对应的 BGL）一起附到问题报告里。");
    return out.join("\n") + "\n";
}

var API = { VERSION: VERSION, BglError: BglError, decompileBytes: decompileBytes, summarize: summarize, reportText: reportText, guid: guid, md5Hex: md5Hex };
  global.BGL2XML = API;
  if (typeof module !== "undefined" && module.exports) module.exports = API;
})(typeof window !== "undefined" ? window : globalThis);
