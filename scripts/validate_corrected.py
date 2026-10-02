#!/usr/bin/env python3
"""訂正済みデータセットを元データと突き合わせる。

build_corrected.py と corrected_rules.py の関数は使わない。
同じ関数で作って同じ関数で確かめると、関数の誤りが両方に入って見つからないため。

検査:
  行数、行の順序、ID 列が元データと一致する
  元データと値が違うセルは、緯度、経度、時刻、ホームページアドレスの列に限られる
  値が違うセルは、同じ行の 注記 に元の値が書かれている
  0.0 の座標と、開始と終了が同じ区間が残っていない
  座標の出典 の値が決まった語のどれかで、座標の有無と食い違わない
  座標の出典 が 原データ の行は、座標が元データと同じ
  座標の出典 が 地番 の行は、座標が住所の県の矩形の中にある

地番の点が OSM 向けの出力に混じらないことは、リポジトリを jp-healthcare-osm と
分けたことで保たれるので、ここでは確かめない。

使い方:
  python3 scripts/validate_corrected.py
"""

import argparse
import csv
import itertools
import os
import re
import sys

LAT, LON = "所在地座標（緯度）", "所在地座標（経度）"
NOTE, SOURCE = "注記", "座標の出典"
SOURCES = {"原データ", "住居表示", "地番", ""}
RE_RAW = re.compile(r"^0\d(-\d)?_[a-z_]+_\d{8}\.csv$")
RE_TIME_COL = re.compile(r"^[月火水木金土日祝]_.+時間$")
# 1ファイルで同じ種類の問題をいくつまで書き出すか。全件は件数だけ数える
MAX_PER_KIND = 20
# 県の矩形は町字の代表点を囲んだもので、県の実際の範囲より小さい。
# 県の端にある施設の正しい点が外に出るので、上下左右に広げてから判定する。
# 2026-10-02 の実データでは、地番の点2,873件のうち2件が最大0.079度はみ出した。
BBOX_MARGIN = 0.1


def editable(col):
    return col in (LAT, LON) or bool(RE_TIME_COL.match(col)) or col.endswith("ホームページアドレス")


def load_bbox(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return {r["都道府県コード"]: tuple(float(r[k]) for k in
                                         ("lat_min", "lat_max", "lon_min", "lon_max"))
                for r in csv.DictReader(f)}


class Problems:
    def __init__(self):
        self.lines = []
        self.counts = {}

    def add(self, name, kind, text):
        key = (name, kind)
        self.counts[key] = self.counts.get(key, 0) + 1
        if self.counts[key] <= MAX_PER_KIND:
            self.lines.append(f"{name}: {kind}: {text}")

    def summary(self):
        extra = [f"{name}: {kind}: ほか {n - MAX_PER_KIND} 件"
                 for (name, kind), n in self.counts.items() if n > MAX_PER_KIND]
        return self.lines + extra


def check_file(raw_path, out_path, bbox, problems):
    name = os.path.basename(raw_path)
    with open(raw_path, encoding="utf-8-sig", newline="") as fr, \
            open(out_path, encoding="utf-8-sig", newline="") as fo:
        rr, ro = csv.reader(fr), csv.reader(fo)
        rh, oh = next(rr), next(ro)
        has_coord = LAT in rh
        want = rh + [NOTE] + ([SOURCE] if has_coord else [])
        if oh != want:
            problems.add(name, "列が元データと合わない", f"末尾 {oh[len(rh):]}")
            return
        ri = {h: i for i, h in enumerate(rh)}
        note_i = len(rh)
        starts = [(ri[c], ri[c[: -len("開始時間")] + "終了時間"], c)
                  for c in rh if RE_TIME_COL.match(c) and c.endswith("開始時間")]
        for n, (raw, out) in enumerate(itertools.zip_longest(rr, ro), start=2):
            if raw is None or out is None:
                problems.add(name, "行数が元データと合わない", f"{n} 行目で片方が尽きた")
                return
            if raw[0] != out[0]:
                problems.add(name, "ID が元データと合わない", f"{n} 行目 {raw[0]} / {out[0]}")
                continue
            note = out[note_i]
            for i, col in enumerate(rh):
                if raw[i] == out[i]:
                    continue
                if not editable(col):
                    problems.add(name, "書き換えてよい列ではない", f"{raw[0]} {col}")
                elif raw[i] not in note:
                    problems.add(name, "注記に元の値が無い", f"{raw[0]} {col} {raw[i]!r}")
            for si, ei, col in starts:
                if out[si] and out[si] == out[ei]:
                    problems.add(name, "開始と終了が同じ区間が残っている",
                                 f"{raw[0]} {col} {out[si]}")
            if has_coord:
                check_coord(name, raw, out, ri, bbox, problems)


def check_coord(name, raw, out, ri, bbox, problems):
    lat, lon, source = out[ri[LAT]], out[ri[LON]], out[-1]
    fid = raw[0]
    if lat and float(lat) == 0 or lon and float(lon) == 0:
        problems.add(name, "0.0 が残っている", fid)
    if source not in SOURCES:
        problems.add(name, "座標の出典の値が決まった語ではない", f"{fid} {source!r}")
    if (source == "") != (lat == "" and lon == ""):
        problems.add(name, "座標の出典と座標の有無が食い違う", f"{fid} {source!r} {lat!r}")
    if source == "原データ" and (lat, lon) != (raw[ri[LAT]], raw[ri[LON]]):
        problems.add(name, "座標の出典が原データなのに元データと違う", fid)
    if source == "地番" and lat and lon:
        box = bbox.get(raw[ri["都道府県コード"]])
        y, x = float(lat), float(lon)
        if box is None or not (box[0] - BBOX_MARGIN <= y <= box[1] + BBOX_MARGIN
                               and box[2] - BBOX_MARGIN <= x <= box[3] + BBOX_MARGIN):
            problems.add(name, "地番の点が県の矩形の外", f"{fid} {lat}, {lon}")


def validate(raw_dir, out_dir, bbox_path):
    problems = Problems()
    bbox = load_bbox(bbox_path)
    raws = sorted(f for f in os.listdir(raw_dir) if RE_RAW.match(f))
    if not raws:
        problems.add(raw_dir, "元データがありません", "")
    for f in raws:
        out = os.path.join(out_dir, f)
        if not os.path.exists(out):
            problems.add(f, "出力がありません", out)
            continue
        check_file(os.path.join(raw_dir, f), out, bbox, problems)
    return problems.summary()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--raw-dir", default=".")
    p.add_argument("--out-dir", default="output/corrected")
    p.add_argument("--bbox", default="vendor/jp-healthcare-osm/mapping/pref_bbox.csv")
    args = p.parse_args()
    found = validate(args.raw_dir, args.out_dir, args.bbox)
    for line in found:
        print(line)
    print(f"問題 {len(found)} 種類の行" if found else "問題なし")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
