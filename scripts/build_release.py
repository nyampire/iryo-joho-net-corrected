#!/usr/bin/env python3
"""訂正済みデータセットを都道府県ごとの ZIP にまとめ、GitHub の Releases に載せる形にする。

入力:
  output/corrected/<元データと同じファイル名>   8ファイル
  README.md                                    「### 出典明示」の節の文言

出力:
  output/release/iryo-joho-net-corrected_<元データの日付>_<県コード>.zip   47個

1つの ZIP には、その県の分だけを入れる。
  <県コード>_<県名>/<元データと同じファイル名>.csv       8ファイル
  <県コード>_<県名>/<施設票のファイル名>.geojson         5ファイル
  <県コード>_<県名>/README.txt                          中身の説明と出典明示

CSV は samples/ と同じく、出力の文字列をそのまま写す。
施設票は 都道府県コード で絞り、診療科の票は絞った施設の ID を持つ行だけを残す。

GeoJSON は施設票の行を点にしたもので、属性には全列を CSV と同じ文字列のまま入れる。
緯度経度が空欄の行は点にできないので GeoJSON には入れず、CSV にだけ残る。
診療科の票は位置を持たないので GeoJSON にしない。
GeoJSON の属性に診療科を入れ子で入れると、QGIS や表計算ソフトでは1つの長い文字列に
なって絞り込めないため、ID で CSV とつなぐ形にした（2026-10-08 に決定）。

ZIP の中のファイル名は日本語を含む。Releases の添付ファイル名は英数字にそろえるため、
ZIP の名前には県名を入れず、県コードだけを入れる。
同じ入力からは同じバイト列の ZIP ができるよう、ZIP の中の時刻は元データの日付に固定する。

使い方:
  python3 scripts/build_release.py [--src output/corrected] [--out output/release]
"""

import argparse
import collections
import json
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
# jp-healthcare-osm にも build_samples.py があるので、このリポジトリの scripts/ を先に探す
sys.path.insert(0, os.path.join(HERE, "..", "vendor", "jp-healthcare-osm", "scripts"))
sys.path.insert(0, HERE)
from build_samples import PREF_COL, RE_FACILITY, RE_HOURS, fields, records  # noqa: E402
from prefectures import PREF  # noqa: E402

LAT, LON = "所在地座標（緯度）", "所在地座標（経度）"
RE_DATE = re.compile(r"_(\d{8})\.csv$")
ZIP_PREFIX = "iryo-joho-net-corrected"


def attribution(readme_path):
    """README の「### 出典明示」の節にある最初のコードブロックの中身を返す。

    出典明示の文言を2か所に持たないよう、README を唯一の置き場にする。
    """
    with open(readme_path, encoding="utf-8") as f:
        text = f.read()
    m = re.search(r"^### 出典明示\n.*?^```\n(.*?)^```", text, re.S | re.M)
    if not m:
        sys.exit(f"README に「### 出典明示」の節のコードブロックがありません: {readme_path}")
    return m.group(1).strip()


def readme_text(code, date, credit):
    return (
        f"医療情報ネット オープンデータ 訂正済みデータセット {code} {PREF[code]}\n"
        f"元データの時点: {date[:4]}年{int(date[4:6])}月{int(date[6:])}日\n"
        "\n"
        "厚生労働省「医療情報ネット」のオープンデータを、元の列のまま、"
        "誤りと確定できる値だけを直したものです。\n"
        "末尾の「注記」列に、書き換えた値、空欄にした値、疑いのある値を、元の値とともに書いています。\n"
        "施設票と診療科の票は ID 列で紐づきます。\n"
        "GeoJSON は施設票の行を点にしたもので、緯度経度が空欄の行は含みません。\n"
        "\n"
        "詳しい説明: https://github.com/nyampire/iryo-joho-net-corrected\n"
        "\n"
        "再配布する際は、次の文言を含めてください。\n"
        "\n"
        f"{credit}\n"
    )


def feature(header, values):
    props = dict(zip(header, values))
    return {
        "type": "Feature",
        "geometry": {"type": "Point",
                     "coordinates": [float(props[LON]), float(props[LAT])]},
        "properties": props,
    }


def split_by_pref(src, names):
    """施設票と診療科の票を県ごとに分ける。

    返り値は (見出し, {県コード: {ファイル名: [レコード文字列]}}, {県コード: {ファイル名: [Feature]}})。
    """
    headers = {}
    csvs = collections.defaultdict(lambda: collections.defaultdict(list))
    geo = collections.defaultdict(lambda: collections.defaultdict(list))
    # 業態ごとの 施設ID -> 県コード。ファイル名の先頭2文字（01 が病院）で施設票と診療科の票を対にする
    pref_of = collections.defaultdict(dict)
    for name in names:
        if not RE_FACILITY.match(name):
            continue
        header, recs = records(os.path.join(src, name))
        headers[name] = header
        cols = fields(header)
        pi = cols.index(PREF_COL)
        li = cols.index(LAT)
        for r in recs:
            values = fields(r)
            code = values[pi]
            csvs[code][name].append(r)
            pref_of[name[:2]][values[0]] = code
            if values[li]:
                geo[code][name].append(feature(cols, values))
    for name in names:
        if not RE_HOURS.match(name):
            continue
        header, recs = records(os.path.join(src, name))
        headers[name] = header
        for r in recs:
            code = pref_of[name[:2]].get(fields(r)[0])
            if code is None:
                sys.exit(f"施設票に無い ID の行があります: {name} {fields(r)[0]}")
            csvs[code][name].append(r)
    return headers, csvs, geo


def write_zip(path, folder, date, files):
    """files の (名前, 中身) を、時刻を固定して ZIP に書く。"""
    stamp = (int(date[:4]), int(date[4:6]), int(date[6:]), 0, 0, 0)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files:
            info = zipfile.ZipInfo(f"{folder}/{name}", date_time=stamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, data)


def build(src, out, readme_path):
    """47個の ZIP を書き、{県コード: (ZIP のパス, {ファイル名: 行数})} を返す。"""
    names = sorted(os.listdir(src)) if os.path.isdir(src) else []
    names = [n for n in names if RE_FACILITY.match(n) or RE_HOURS.match(n)]
    if sum(1 for n in names if RE_FACILITY.match(n)) != 5 or \
            sum(1 for n in names if RE_HOURS.match(n)) != 3:
        sys.exit(f"{src} に8ファイルが揃っていません。先に npm run correct を実行してください")
    dates = {RE_DATE.search(n).group(1) for n in names}
    if len(dates) != 1:
        sys.exit(f"元データの日付がそろっていません: {sorted(dates)}")
    date = dates.pop()
    credit = attribution(readme_path)

    headers, csvs, geo = split_by_pref(src, names)
    unknown = sorted(set(csvs) - set(PREF))
    if unknown:
        sys.exit(f"都道府県コードが不正な行があります: {unknown}")
    os.makedirs(out, exist_ok=True)
    result = {}
    for code in sorted(PREF):
        files = []
        counts = {}
        for name in names:
            recs = csvs[code][name]
            counts[name] = len(recs)
            body = "﻿" + headers[name] + "\r\n" + "".join(r + "\r\n" for r in recs)
            files.append((name, body.encode("utf-8")))
        for name in names:
            if not RE_FACILITY.match(name):
                continue
            fc = {"type": "FeatureCollection", "features": geo[code][name]}
            files.append((name[:-len(".csv")] + ".geojson",
                          json.dumps(fc, ensure_ascii=False).encode("utf-8")))
        files.append(("README.txt", readme_text(code, date, credit).encode("utf-8")))
        path = os.path.join(out, f"{ZIP_PREFIX}_{date}_{code}.zip")
        write_zip(path, f"{code}_{PREF[code]}", date, files)
        result[code] = (path, counts)
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--src", default=os.path.join("output", "corrected"))
    p.add_argument("--out", default=os.path.join("output", "release"))
    p.add_argument("--readme", default="README.md")
    args = p.parse_args()
    result = build(args.src, args.out, args.readme)
    total = 0
    for code, (path, counts) in result.items():
        size = os.path.getsize(path)
        total += size
        print(f"  {os.path.basename(path)}  {PREF[code]:<4}  {size / 1e6:6.1f} MB")
    print(f"{len(result)} 個  合計 {total / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
