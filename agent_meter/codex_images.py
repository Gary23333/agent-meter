"""Codex 桌面端内置 image_gen 的按张统计（张数 + API 等价估算成本）。

口径（与 docs 里既定口径一致，不读对话正文）：
- 每张 PNG 存在 ~/.codex/generated_images/<thread-id>/ 下，文件名 exec-*.png / ig_*.png；
  只读 PNG 头 33 字节解析 IHDR 宽高，不读整图。
- 成本只估输出 token：GPT Image 2.5 输出 token 单价 $30/1M；按像素面积对基准面积等比缩放。
  宽高比 max/min <= 1.13 视为方形（基准 1024x1024），否则按 1536x1024 基准。
  不含参考图输入 token，是 API 等价估算，不是订阅账单。
- 调用次数（calls/failed/generating）来自 ~/.codex/thread_history*.sqlite 的
  thread_items；该库很大，只 select 两个标量（绝不 select item_json 整列），
  按 (path, mtime_ns, size) 做进程内缓存（TTL 600s，上限 4 项）。
- 历史库读不到时降级为「仅文件统计」：status=partial / reason=codex_history_unavailable。
"""
import os
import sqlite3
import time
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from .ccswitch import period_bounds
from .model import DISPLAY_ZONE, SourceError, metric
from .prices import FX_FALLBACK

# GPT Image 2.5 输出 token 官方单价（USD / 百万 token）。
OUTPUT_PRICE_PER_MILLION = Decimal("30")
# 质量档位 -> (方形基准 tokens, 非方形基准 tokens)，基准面积见下。
QUALITY_TOKEN_BASE = {
    "low": (196, 158),
    "medium": (439, 343),
    "high": (1756, 1372),
    "xhigh": (3122, 2459),
    "max": (7024, 5488),
}
DEFAULT_QUALITY = "high"
SQUARE_REF_AREA = 1024 * 1024
WIDE_REF_AREA = 1536 * 1024
# 宽高比在该阈值内（含）按方形基准计价。
SQUARE_ASPECT_LIMIT = 1.13
SIX = Decimal("0.000001")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

PERIODS = ("today", "7d", "30d", "all")
HISTORY_TTL_SECONDS = 600
HISTORY_CACHE_MAX = 4

_png_cache = {}       # path -> ((mtime_ns, size), width, height)
_history_cache = {}   # path -> (stamp, expires_at, statuses|None)

HISTORY_SQL = ("SELECT created_at_ms, json_extract(item_json,'$.status')"
               " FROM thread_items WHERE item_type='imageGeneration'")


def resolve_quality(quality):
    """非法档位回退 high（配置项可能被手动写坏）。"""
    key = quality.strip().lower() if isinstance(quality, str) else ""
    return key if key in QUALITY_TOKEN_BASE else DEFAULT_QUALITY


def estimate_cost_usd(width, height, quality=DEFAULT_QUALITY):
    """一张图的输出 token 成本（USD，定点 6 位小数）。"""
    if isinstance(width, bool) or isinstance(height, bool) \
            or not isinstance(width, int) or not isinstance(height, int):
        raise SourceError("invalid_image_dimensions")
    if width <= 0 or height <= 0:
        raise SourceError("invalid_image_dimensions")
    base_square, base_wide = QUALITY_TOKEN_BASE[resolve_quality(quality)]
    if max(width, height) / min(width, height) <= SQUARE_ASPECT_LIMIT:
        base_tokens, ref_area = base_square, SQUARE_REF_AREA
    else:
        base_tokens, ref_area = base_wide, WIDE_REF_AREA
    tokens = Decimal(base_tokens) * Decimal(width * height) / Decimal(ref_area)
    return (tokens * OUTPUT_PRICE_PER_MILLION / Decimal(1000000)).quantize(SIX, ROUND_HALF_UP)


def read_png_size(path):
    """只读 PNG 头解析 IHDR 宽高；失败返回 (None, None)。"""
    try:
        with open(path, "rb") as handle:
            head = handle.read(33)
    except (OSError, ValueError):
        return None, None
    if len(head) < 24 or head[:8] != PNG_SIGNATURE or head[12:16] != b"IHDR":
        return None, None
    width = int.from_bytes(head[16:20], "big")
    height = int.from_bytes(head[20:24], "big")
    if width <= 0 or height <= 0:
        return None, None
    return width, height


def scan_image_files(images_dir, use_cache=True):
    """[(epoch_seconds, width, height)]；宽高为 None 表示头部不可解析。

    不可解析的图仍计入张数（文件确实存在），只是成本跳过，
    由指标里的 unreadable_images 体现。
    """
    root = Path(images_dir)
    records = []
    seen = set()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            if not name.lower().endswith(".png"):
                continue
            path = Path(dirpath) / name
            try:
                st = path.stat()
            except OSError:
                continue
            stamp = (st.st_mtime_ns, st.st_size)
            key = str(path)
            if use_cache:
                seen.add(key)
                cached = _png_cache.get(key)
                if cached is not None and cached[0] == stamp:
                    records.append((st.st_mtime, cached[1], cached[2]))
                    continue
            width, height = read_png_size(path)
            if use_cache:
                _png_cache[key] = (stamp, width, height)
            records.append((st.st_mtime, width, height))
    if use_cache:
        for gone in set(_png_cache) - seen:
            del _png_cache[gone]
    return records


def find_history_db(codex_home):
    """thread_history*.sqlite 里取 mtime 最新的一份（排除 -shm/-wal 伴生文件）。"""
    root = Path(codex_home).expanduser()
    if not root.is_dir():
        return None
    candidates = []
    try:
        for path in root.glob("thread_history*.sqlite"):
            if "-shm" in path.name or "-wal" in path.name:
                continue
            if path.is_file():
                candidates.append(path)
    except OSError:
        return None
    if not candidates:
        return None
    try:
        return max(candidates, key=lambda p: p.stat().st_mtime)
    except OSError:
        return None


def resolve_history_db(history_db):
    """配置的路径不存在时，用所在目录的 glob 兜底（版本号会变）。"""
    if not history_db:
        return None
    path = Path(history_db).expanduser()
    if path.is_file():
        return path
    return find_history_db(path.parent)


def read_history_statuses(history_db):
    """[(created_at_ms, status)]，读不到返回 None（调用方降级）。

    先试只读 URI（?mode=ro）；本机该库约 3.5GB，模式只读打开可能报
    unable to open database file，因此再退回 ?immutable=1。
    """
    path = Path(history_db).expanduser()
    if not path.is_file():
        return None
    uri = path.resolve().as_uri()
    conn = None
    try:
        try:
            conn = sqlite3.connect(uri + "?mode=ro", uri=True, timeout=3)
            conn.execute("PRAGMA query_only=ON")
            rows = conn.execute(HISTORY_SQL).fetchall()
        except sqlite3.Error:
            if conn is not None:
                conn.close()
            conn = sqlite3.connect(uri + "?immutable=1", uri=True, timeout=3)
            conn.execute("PRAGMA query_only=ON")
            rows = conn.execute(HISTORY_SQL).fetchall()
        return [(row[0], row[1]) for row in rows
                if isinstance(row[0], int) and not isinstance(row[0], bool)]
    except (sqlite3.Error, OSError, ValueError):
        return None
    finally:
        if conn is not None:
            conn.close()


def history_statuses(history_db, now=None):
    """带进程内缓存的调用状态列表；None 也会被缓存，避免每次刷新都开大库。"""
    if history_db is None:
        return None
    path = Path(history_db).expanduser()
    try:
        st = path.stat()
    except OSError:
        return None
    key = str(path)
    stamp = (st.st_mtime_ns, st.st_size)
    current = time.time() if now is None else float(now)
    cached = _history_cache.get(key)
    if cached is not None and cached[0] == stamp and current < cached[1]:
        return cached[2]
    statuses = read_history_statuses(path)
    _history_cache[key] = (stamp, current + HISTORY_TTL_SECONDS, statuses)
    if len(_history_cache) > HISTORY_CACHE_MAX:
        oldest = min(_history_cache, key=lambda k: _history_cache[k][1])
        del _history_cache[oldest]
    return statuses


def _money(usd, currency):
    """USD 原样输出；CNY 按 FX_FALLBACK 折算（与价格表同一口径）。"""
    if currency == "CNY":
        return (usd * FX_FALLBACK).quantize(SIX, ROUND_HALF_UP)
    return usd.quantize(SIX, ROUND_HALF_UP)


def codex_image_metric(images_dir, history_db, now, zone=DISPLAY_ZONE,
                       currency="USD", quality=DEFAULT_QUALITY):
    """codex 来源的 image_generation 指标。"""
    root = Path(images_dir).expanduser()
    if not root.is_dir():
        raise SourceError("codex_images_not_found")
    quality_key = resolve_quality(quality)
    currency_key = currency if currency in {"USD", "CNY"} else "USD"
    records = scan_image_files(root)
    db = resolve_history_db(history_db)
    statuses = history_statuses(db, now) if db is not None else None

    bounds = {period: period_bounds(now, period, zone) for period in PERIODS}
    period_rows = {period: {"images": 0, "calls": 0, "failed_calls": 0,
                            "generating_calls": 0, "usd": Decimal(0)} for period in PERIODS}
    unreadable = 0
    buckets = {}
    for epoch, width, height in records:
        cost = Decimal(0)
        if width is None or height is None:
            unreadable += 1
        else:
            cost = estimate_cost_usd(width, height, quality_key)
        inches = datetime.fromtimestamp(epoch, zone).date().isoformat()
        bucket = buckets.setdefault(inches, {"images": 0, "usd": Decimal(0)})
        bucket["images"] += 1
        bucket["usd"] += cost
        for period in PERIODS:
            start, end = bounds[period]
            if start is not None and epoch < start:
                continue
            if epoch > end:
                continue
            row = period_rows[period]
            row["images"] += 1
            row["usd"] += cost

    if statuses is not None:
        # calls 是内置生图调用总数（含失败与进行中）；failed/generating 是它的子集。
        for created_ms, status in statuses:
            seconds = created_ms / 1000
            for period in PERIODS:
                start, end = bounds[period]
                if start is not None and seconds < start:
                    continue
                if seconds > end:
                    continue
                row = period_rows[period]
                row["calls"] += 1
                if status == "failed":
                    row["failed_calls"] += 1
                elif status == "generating":
                    row["generating_calls"] += 1

    value = {
        "basis": "codex_builtin_image_gen_files",
        "quality_assumption": quality_key,
        "currency": currency_key,
        "converted_from_usd": currency_key == "CNY",
        "fx_note": "converted_at_7.25" if currency_key == "CNY" else None,
        "cost_scope": "output_tokens_only_excludes_reference_inputs",
        "call_counts_available": statuses is not None,
        "periods": {period: {"images": row["images"], "calls": row["calls"],
                             "failed_calls": row["failed_calls"],
                             "generating_calls": row["generating_calls"],
                             "estimated_cost": format(_money(row["usd"], currency_key), "f")}
                    for period, row in period_rows.items()},
        "daily_buckets": [{"date": date, "images": bucket["images"],
                           "estimated_cost": format(_money(bucket["usd"], currency_key), "f")}
                          for date, bucket in sorted(buckets.items())],
        "coverage": ("codex_generated_images_and_thread_history" if statuses is not None
                     else "codex_generated_images"),
        "unreadable_images": unreadable,
        "timezone": str(zone),
    }
    if statuses is not None:
        return metric(value)
    return metric(value, status="partial", reason="codex_history_unavailable")


def history_call_counts(history_db, now, zone=DISPLAY_ZONE):
    """校验（verify）用的独立重算：与缓存无关地重新读库并分周期计数。"""
    statuses = read_history_statuses(history_db) if history_db is not None else None
    if statuses is None:
        return None
    counts = {period: {"calls": 0, "failed_calls": 0, "generating_calls": 0} for period in PERIODS}
    for created_ms, status in statuses:
        seconds = created_ms / 1000
        for period in PERIODS:
            start, end = period_bounds(now, period, zone)
            if start is not None and seconds < start:
                continue
            if seconds > end:
                continue
            row = counts[period]
            row["calls"] += 1
            if status == "failed":
                row["failed_calls"] += 1
            elif status == "generating":
                row["generating_calls"] += 1
    return counts
