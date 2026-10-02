#!/usr/bin/env python3
"""訂正済みデータセットの規則。

値1つ、または値の組1つを受け取り、直した値と注記を返す純関数を置く。
CSV の読み書きは build_corrected.py が持ち、ここでは行わない。

値を書き換えるか空欄にするのは、誤りと確定できる値だけ。
それ以外の異常は元の値を残し、注記に疑いとして書く。

注記の文は「空欄にした: 」「書き換えた: 」「疑い: 」のどれかで始め、元の値をそのまま含める。
validate_corrected.py は、値が変わったセルの元の値が注記に含まれることを確かめる。

判定の基準は OSM 向けの処理と共有する。区間の分類は build_opening_hours.classify、
休診日の範囲は build_opening_hours.parse_closed_dates、URL の形は build_osm の正規表現。
"""

import os
import re
import sys

# 判定の関数は submodule の jp-healthcare-osm から読む
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "vendor",
                                "jp-healthcare-osm", "scripts"))
from build_opening_hours import (EXCLUSION_NOTE, MAX_CLOSURE_RANGE_DAYS,  # noqa: E402
                                 NIGHT_MAX_DURATION, classify, parse_closed_dates)
from build_osm import (RE_BARE_DOMAIN, RE_MISSING_COLON, RE_REDIRECT,  # noqa: E402
                       RE_URL)

NOTE_SEP = " / "

# 曜日で始まり 開始時間 で終わる列。`月_診療開始時間` と `月_開店時間帯2_開始時間` の両方の形がある
RE_TIME_START = re.compile(r"^([月火水木金土日祝])_(.+?)_?開始時間$")

# 残して注記する区間の理由。00:00-23:59 は24時間営業の書き方として正しいので含めない
SUSPECT_NOTE = {
    "too_early": EXCLUSION_NOTE["too_early"],
    "too_late": EXCLUSION_NOTE["too_late"],
    "overnight_implausible": f"日跨ぎとしても {NIGHT_MAX_DURATION // 60}時間を超える",
}

# parse_closed_dates が解釈しなかった範囲を残り文字列に埋める形
RE_REJECTED_RANGE = re.compile(r"\[\d+日超の範囲:(.+?)\]")


def time_pairs(header):
    """時刻の列を (開始列, 終了列, 表示名) の組で、列の順に返す。"""
    pairs = []
    for col in header:
        m = RE_TIME_START.match(col)
        if not m:
            continue
        end = col[: -len("開始時間")] + "終了時間"
        if end not in header:
            raise ValueError(f"終了時間の列がありません: {col}")
        pairs.append((col, end, f"{m.group(1)}_{m.group(2)}"))
    return pairs


def fix_time(a, b, label):
    """開始と終了の組を直す。(開始, 終了, 注記) を返す。"""
    if not (a.strip() and b.strip()):
        return a, b, ""
    kind = classify(a.strip(), b.strip())
    if kind == "null_placeholder":
        return "", "", f"空欄にした: {label} {a}-{b}（開始と終了が同じ）"
    if kind in SUSPECT_NOTE:
        return a, b, f"疑い: {label} {a}-{b}（{SUSPECT_NOTE[kind]}）"
    return a, b, ""


def closed_date_notes(text, label):
    """自由記述の休診日のうち、範囲が長すぎて終点の誤りが疑われるものを注記にする。"""
    if not text.strip():
        return []
    _, rest = parse_closed_dates(text.strip())
    return [f"疑い: {label} {raw}（範囲が{MAX_CLOSURE_RANGE_DAYS}日を超える。"
            f"終点の打ち間違いの疑い）"
            for raw in RE_REJECTED_RANGE.findall(rest)]


def fix_url(value, label):
    """ホームページアドレスを直す。(値, 注記) を返す。

    OSM 向けの clean_url とは規則が違う。スキームが無い値に https を補わず、
    300文字の上限でも落とさない。前者は http か https かを元データから決められず、
    後者は OSM のタグ値の上限で、元の値の誤りではないため。
    """
    v = value.strip()
    if not v:
        return value, ""
    if RE_REDIRECT.match(v):
        return "", f"空欄にした: {label} {value}（検索エンジンの転送 URL）"
    if RE_URL.match(v):
        return value, ""
    m = RE_MISSING_COLON.match(v)
    if m:
        fixed = f"{m.group(1)}://{m.group(2)}"
        return fixed, f"書き換えた: {label} {value} → {fixed}（コロンの脱字）"
    if RE_BARE_DOMAIN.match(v):
        return value, f"疑い: {label} {value}（スキームが無い）"
    return value, f"疑い: {label} {value}（URL として読めない形式）"
