#!/usr/bin/env python3
"""医療情報ネットの元データに、誤りと確定できる値だけの訂正を当てる。

OSM のタグには変換しない。元データの列を同じ順で残し、末尾に 注記 を足す。
緯度経度の列を持つファイルには 座標の出典 も足す。行の順序と行数は元データと同じ。
規則は corrected_rules.py にあり、ここは読み書きと、規則をどの列に当てるかを持つ。

入力:
  NN-*_..._YYYYMMDD.csv                    元データ（--data-dir）
  output/build/<業態>_geocoded.csv          座標の判定（npm run geocode の生成物）
  output/build/chiban_points.csv  地番の点（geocode_chiban.mjs の生成物）

出力:
  output/corrected/<元データと同じファイル名>

書き出しは1行ずつだが、曜日フラグと時刻の矛盾の判定のために全区間を読み込む。
診療所のピークは約670MBになる。

使い方:
  python3 scripts/build_corrected.py [--sector hospital]
"""

import argparse
import collections
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
# 判定の関数は submodule の jp-healthcare-osm から読む
sys.path.insert(0, os.path.join(HERE, "..", "vendor", "jp-healthcare-osm", "scripts"))
from build_opening_hours import (EMERGENCY_CODES, SECTORS, classify,  # noqa: E402
                                 find_conflicts, load_facilities, load_intervals,
                                 load_intervals_inline, resolve)
from corrected_rules import (NOTE_SEP, closed_date_notes, decide_coord,  # noqa: E402
                             fix_time, fix_url, time_pairs)

LAT, LON = "所在地座標（緯度）", "所在地座標（経度）"
NOTE, SOURCE = "注記", "座標の出典"
URL_LABEL = "ホームページアドレス"


def load_geocoded(path):
    if not os.path.exists(path):
        sys.exit(f"座標の判定がありません: {path}\n先に npm run geocode を実行してください")
    with open(path, encoding="utf-8-sig", newline="") as f:
        return {r["ID"]: r for r in csv.DictReader(f)}


def load_chiban(path, sector):
    if not os.path.exists(path):
        sys.exit(f"地番の点がありません: {path}\n先に npm run chiban を実行してください")
    with open(path, encoding="utf-8-sig", newline="") as f:
        return {r["ID"]: (r["lat"], r["lon"])
                for r in csv.DictReader(f) if r["業態"] == sector}


def load_conflicts(profile, facility_path, hours_path):
    """曜日フラグと時刻の矛盾を 施設ID -> [(曜日, 内容)] にまとめる。

    判定は OSM 向けの処理と同じ find_conflicts に任せる。数える時刻は診療
    （助産所は就業、薬局は開店）の系列で、救急科と、classify が外す区間を除いたもの。
    """
    fac = load_facilities(facility_path, profile)
    if profile["mode"] == "inline":
        intervals = load_intervals_inline(facility_path, profile)[0]
    else:
        intervals = load_intervals(hours_path)[0]
    out = collections.defaultdict(list)
    for fid, _name, _pref, day, _flag, _has, what in find_conflicts(intervals, fac):
        out[fid].append((day, what))
    return out


def has_counted_time(row, idx, day):
    """診療科の票の行が、曜日 day の時刻として find_conflicts に数えられるか。

    load_intervals と同じ基準。救急科と、classify が外す区間は数えない。
    """
    a = row[idx[f"{day}_診療開始時間"]].strip()
    b = row[idx[f"{day}_診療終了時間"]].strip()
    if not (a and b):
        return False
    if row[idx["診療科目コード"]] in EMERGENCY_CODES:
        return False
    return classify(a, b) is None


def correct_times(row, idx, pairs, notes):
    for start, end, label in pairs:
        a, b, note = fix_time(row[idx[start]], row[idx[end]], label)
        row[idx[start]], row[idx[end]] = a, b
        if note:
            notes.append(note)


def correct_facility_row(row, idx, profile, pairs, url_col, geo, chiban, conflicts):
    """施設票（助産所と薬局では唯一の票）の1行を直す。(行, 注記の一覧) を返す。"""
    fid = row[0]
    if fid not in geo:
        raise ValueError(f"geocoded.csv に行がありません: {fid}")
    g = geo[fid]
    if (g["元_緯度"], g["元_経度"]) != (row[idx[LAT]], row[idx[LON]]):
        raise ValueError(f"geocoded.csv が元データと合いません。"
                         f"npm run geocode をやり直してください: {fid}")
    notes = []
    lat, lon, source, note = decide_coord(row[idx[LAT]], row[idx[LON]], geo[fid],
                                          chiban.get(fid))
    row[idx[LAT]], row[idx[LON]] = lat, lon
    if note:
        notes.append(note)
    correct_times(row, idx, pairs, notes)
    for day, what in conflicts.get(fid, []):
        notes.append(f"疑い: {day} {what}")
    notes += closed_date_notes(row[idx[profile["other"]]], profile["other"])
    if url_col:
        value, note = fix_url(row[idx[url_col]], URL_LABEL)
        row[idx[url_col]] = value
        if note:
            notes.append(note)
    return row + [NOTE_SEP.join(notes), source], notes


def correct_hours_row(row, idx, pairs, conflicts):
    """診療科の票の1行を直す。(行, 注記の一覧) を返す。

    矛盾の注記は、施設票で休みの曜日に、この行が数えられる時刻を持つときだけ書く。
    時刻を空欄にする前の値で判定する。
    """
    notes = []
    for day, what in conflicts.get(row[0], []):
        if "休みだが" in what and has_counted_time(row, idx, day):
            notes.append(f"疑い: {day} 施設票の{what}")
    correct_times(row, idx, pairs, notes)
    return row + [NOTE_SEP.join(notes)], notes


def quote(value):
    return '"' + value.replace('"', '""') + '"'


def format_record(fields, bare):
    """1件を CSV の1行にする。bare の位置の値だけ引用符を付けない（空欄は空のまま）。

    元データは緯度経度の2列だけ引用符が無いので、それに合わせる。
    """
    return ",".join(f if i in bare else quote(f) for i, f in enumerate(fields))


def rewrite(src, dst, extra_cols, fix_row, stat):
    """src を1行ずつ読み、fix_row(row, idx, pairs) で直して dst に書く。"""
    name = os.path.basename(src)
    with open(src, encoding="utf-8-sig", newline="") as fi, \
            open(dst, "w", encoding="utf-8-sig", newline="") as fo:
        r = csv.reader(fi)
        header = next(r)
        idx = {h: i for i, h in enumerate(header)}
        pairs = time_pairs(header)
        bare = {idx[LAT], idx[LON]} if LAT in idx else set()
        fo.write(format_record(header + extra_cols, set()) + "\r\n")
        for row in r:
            out, notes = fix_row(row, idx, header, pairs)
            fo.write(format_record(out, bare) + "\r\n")
            stat[(name, "行")] += 1
            for n in notes:
                stat[(name, n.split(":", 1)[0])] += 1
            if SOURCE in extra_cols:
                stat[(name, f"{SOURCE} {out[-1] or '空欄'}")] += 1


def correct_sector(sector, data_dir, build_dir, chiban_path, out_dir):
    profile = SECTORS[sector]
    f1 = resolve(data_dir, profile["facility"])
    f2 = resolve(data_dir, profile["hours"]) if profile["hours"] else None
    geo = load_geocoded(os.path.join(build_dir, f"{sector}_geocoded.csv"))
    chiban = load_chiban(chiban_path, sector)
    conflicts = load_conflicts(profile, f1, f2)
    os.makedirs(out_dir, exist_ok=True)
    stat = collections.Counter()

    def facility(row, idx, header, pairs):
        url_col = next((h for h in header if h.endswith(URL_LABEL)), None)
        return correct_facility_row(row, idx, profile, pairs, url_col, geo, chiban,
                                    conflicts)

    def hours(row, idx, header, pairs):
        return correct_hours_row(row, idx, pairs, conflicts)

    rewrite(f1, os.path.join(out_dir, os.path.basename(f1)), [NOTE, SOURCE], facility, stat)
    if f2:
        rewrite(f2, os.path.join(out_dir, os.path.basename(f2)), [NOTE], hours, stat)
    return stat


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data-dir", default=".")
    p.add_argument("--build-dir", default="output/build")
    p.add_argument("--chiban", default="output/build/chiban_points.csv")
    p.add_argument("--out-dir", default="output/corrected")
    p.add_argument("--sector", default="all", choices=["all"] + sorted(SECTORS))
    args = p.parse_args()

    sectors = list(SECTORS) if args.sector == "all" else [args.sector]
    for sector in sectors:
        stat = correct_sector(sector, args.data_dir, args.build_dir, args.chiban, args.out_dir)
        print(f"== {SECTORS[sector]['label']}")
        for (name, kind), n in sorted(stat.items()):
            print(f"  {name}  {kind:<16} {n:>9,}")


if __name__ == "__main__":
    main()
