#!/usr/bin/env python3
"""validate_corrected.py の逆テスト。

正しい出力が通ることと、わざと壊した出力が落ちることを確かめる。
壊し方は検査の表の各行に1つずつ対応させる。検査が何も見なくなっても
「問題なし」と出るだけなので、落ちることを確かめないと検証器の故障に気づけない。
"""

import csv
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_corrected import correct_sector  # noqa: E402
from corrected_fixtures import LAT, LON, make_fixture  # noqa: E402
from validate_corrected import validate  # noqa: E402

BBOX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "vendor",
                    "jp-healthcare-osm", "mapping", "pref_bbox.csv")
FAC = "01-1_hospital_facility_info_20990101.csv"
HRS = "01-2_hospital_speciality_hours_20990101.csv"


def edit(path, fn):
    """CSV を読み、fn(header, rows) で書き換えて書き戻す。"""
    with open(path, encoding="utf-8-sig", newline="") as f:
        r = csv.reader(f)
        header = next(r)
        rows = list(r)
    fn(header, rows)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
        w.writerow(header)
        w.writerows(rows)


def replace_text(path, old, new):
    """出力ファイルの文字列を直接置き換える。csv で読み書きすると引用符が変わるため。"""
    with open(path, encoding="utf-8-sig", newline="") as f:
        text = f.read()
    if old not in text:
        raise ValueError(f"置き換え元の文字列がありません: {old!r}")
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        f.write(text.replace(old, new, 1))


def cell(header, rows, row_id, col, value, nth=0):
    """ID が row_id の nth 番目の行の col を value にする。"""
    hits = [r for r in rows if r[0] == row_id]
    hits[nth][header.index(col)] = value


def main():
    breaks = [
        ("診療科の票の行を落とすと落ちる", "行数",
         HRS, lambda h, rows: rows.pop()),
        ("名称を書き換えると落ちる", "書き換えてよい列ではない",
         FAC, lambda h, rows: cell(h, rows, "H001", "正式名称", "別の名前")),
        ("注記なしで時刻を書き換えると落ちる", "注記に元の値が無い",
         HRS, lambda h, rows: cell(h, rows, "H001", "月_診療開始時間", "10:00")),
        ("0,0 を残すと落ちる", "0.0 が残っている",
         FAC, lambda h, rows: (cell(h, rows, "H003", LAT, "0.0"), cell(h, rows, "H003", LON, "0.0"))),
        ("開始と終了が同じ区間を残すと落ちる", "開始と終了が同じ区間が残っている",
         HRS, lambda h, rows: (cell(h, rows, "H001", "火_診療開始時間", "17:00", 1),
                               cell(h, rows, "H001", "火_診療終了時間", "17:00", 1))),
        ("地番の点が県の外にあると落ちる", "県の矩形の外",
         FAC, lambda h, rows: (cell(h, rows, "H003", LAT, "26.2"), cell(h, rows, "H003", LON, "127.7"))),
        ("座標の出典と座標の有無が食い違うと落ちる", "座標の出典",
         FAC, lambda h, rows: cell(h, rows, "H004", "座標の出典", "住居表示")),
        ("元データの座標を使ったのに値が違うと落ちる", "原データ",
         FAC, lambda h, rows: cell(h, rows, "H006", "座標の出典", "原データ")),
        ("空だった値を埋めると落ちる", "空欄だった値が埋まっている",
         HRS, lambda h, rows: cell(h, rows, "H001", "日_診療開始時間", "10:00")),
        ("注記が値だけでラベルが無いと落ちる", "注記に元の値が無い",
         FAC, lambda h, rows: cell(h, rows, "H002", "注記", "0.0")),
        ("時刻を空欄以外に変えると落ちる", "時刻が空欄以外に変わっている",
         HRS, lambda h, rows: cell(h, rows, "H001", "火_診療開始時間", "10:00", 1)),
    ]

    # 文字列の置き換えで壊すもの: (名前, キーワード, 対象, 置き換え元, 置き換え先)
    text_breaks = [
        ("値が同じで引用符だけ違う行は落ちる", "変わっていない行の書式が元データと違う",
         HRS, '"09010"', "09010"),
    ]

    failed = 0
    total = 0
    print("=== validate_corrected.py 逆テスト ===\n")

    def report(name, ok, detail):
        nonlocal failed, total
        total += 1
        if not ok:
            failed += 1
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        if not ok:
            print(f"        {detail}")

    with tempfile.TemporaryDirectory() as tmp:
        p = make_fixture(tmp)
        for sector in ("hospital", "pharmacy"):
            correct_sector(sector, p["data_dir"], p["build_dir"], p["chiban"], p["out_dir"])
        good = validate(p["data_dir"], p["out_dir"], BBOX)
        report("正しい出力は通る", good == [], good)

        for name, keyword, target, fn in breaks:
            broken = os.path.join(tmp, "broken")
            shutil.rmtree(broken, ignore_errors=True)
            shutil.copytree(p["out_dir"], broken)
            edit(os.path.join(broken, target), fn)
            got = validate(p["data_dir"], broken, BBOX)
            report(name, any(keyword in g for g in got), got)

        for name, keyword, target, old, new in text_breaks:
            broken = os.path.join(tmp, "broken")
            shutil.rmtree(broken, ignore_errors=True)
            shutil.copytree(p["out_dir"], broken)
            replace_text(os.path.join(broken, target), old, new)
            got = validate(p["data_dir"], broken, BBOX)
            report(name, any(keyword in g for g in got), got)

        # 出力ファイルが1つ欠けている
        broken = os.path.join(tmp, "broken")
        shutil.rmtree(broken, ignore_errors=True)
        shutil.copytree(p["out_dir"], broken)
        os.remove(os.path.join(broken, "05_pharmacy_20990101.csv"))
        got = validate(p["data_dir"], broken, BBOX)
        report("出力ファイルが欠けると落ちる", any("出力がありません" in g for g in got), got)

        # 県の矩形から少しはみ出す地番の点。北海道の南端は 41.358899 で、0.049度外
        broken = os.path.join(tmp, "broken")
        shutil.rmtree(broken, ignore_errors=True)
        shutil.copytree(p["out_dir"], broken)
        edit(os.path.join(broken, FAC),
             lambda h, rows: (cell(h, rows, "H003", LAT, "41.31"),
                              cell(h, rows, "H003", LON, "141.4")))
        got = validate(p["data_dir"], broken, BBOX)
        report("矩形から0.1度以内のはみ出しは通す",
               not any("県の矩形の外" in g for g in got), got)

    print(f"\n  {total - failed}/{total} 件")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
