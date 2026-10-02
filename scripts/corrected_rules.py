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


# build_addr.js と fix_placeholder_coords.js が 座標の理由 に書く文から、理由の句を取り出す
RE_COORD_REASON = re.compile(r"^元データの座標 [-\d.]+, [-\d.]+ [がを](.+?)ため")


def coord_reason(raw_lat, raw_lon, geo):
    """元データの座標を使わない理由を、句点を含まない句で返す。"""
    if float(raw_lat or 0) == 0 or float(raw_lon or 0) == 0:
        return "欠損を示す値"
    text = geo.get("座標の理由", "")
    m = RE_COORD_REASON.match(text)
    if not m:
        raise ValueError(f"座標を置き換える理由が読めません: {geo['ID']} {text!r}")
    # 「1度の格子に乗る丸め値のため」の「の」は、ためにつなぐための語なので落とす
    return m.group(1).replace("ジオコーダ座標", "住所の点").removesuffix("の")


def decide_coord(raw_lat, raw_lon, geo, chiban):
    """座標を決める。(緯度, 経度, 座標の出典, 注記) を返す。

    置き換えるかどうかは既存の処理の判定（geocoded.csv の 座標の出典）に従う。
    置き換え先は位置レベル8の点だけで、住居表示の点を先に使う。
    geocoded.csv の 住所_位置レベル が8の点は、nja-osm-tags が地番の点を返さないので
    住居表示の点に限られる。
    """
    if geo["座標の出典"] == "原データ":
        return raw_lat, raw_lon, "原データ", ""
    why = coord_reason(raw_lat, raw_lon, geo)
    if geo["住所_位置レベル"] == "8" and geo["住所_lat"] and geo["住所_lon"]:
        lat, lon = geo["住所_lat"], geo["住所_lon"]
        return lat, lon, "住居表示", (f"書き換えた: 緯度経度 {raw_lat}, {raw_lon} → "
                                    f"住居表示の点 {lat}, {lon}（{why}）")
    if chiban:
        lat, lon = chiban
        return lat, lon, "地番", (f"書き換えた: 緯度経度 {raw_lat}, {raw_lon} → "
                                f"地番の点 {lat}, {lon}（{why}）")
    return "", "", "", (f"空欄にした: 緯度経度 {raw_lat}, {raw_lon}"
                        f"（{why}。位置レベル8の住所の点が無い）")
