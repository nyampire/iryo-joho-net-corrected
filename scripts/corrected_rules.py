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
import unicodedata

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
    "overnight_implausible": f"日跨ぎとしても {NIGHT_MAX_DURATION // 60}時間以上",
}

# parse_closed_dates が解釈しなかった範囲を残り文字列に埋める形
RE_REJECTED_RANGE = re.compile(r"\[\d+日超の範囲:(.+?)\]")

# 曜日の列の 0 と 1 の意味と、時刻の呼び方。業態ごとに定義書の「フォーマット」列の語を使う。
# どの業態も 0 が閉、1 が開で、列名の「休診」「休業」とは逆になる
SECTOR_WORDS = {
    "hospital": ("休診", "診療", "診療時間"),
    "clinic": ("休診", "診療", "診療時間"),
    "dental": ("休診", "診療", "診療時間"),
    "maternity": ("休業", "就業", "就業時間"),
    "pharmacy": ("閉店", "開店", "開店時間"),
}


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


def fix_time(a, b, label, suspect=True):
    """開始と終了の組を直す。(開始, 終了, 注記) を返す。

    suspect が偽の行（救急科）は、早朝、深夜、長い日跨ぎに疑いを付けない。
    救急科は深夜や24時間の受け付けが普通で、外来の基準が当てはまらないため。
    開始と終了が同じ区間は、救急科でも空欄にする。
    """
    if not (a.strip() and b.strip()):
        return a, b, ""
    kind = classify(a.strip(), b.strip())
    if kind == "null_placeholder":
        return "", "", f"空欄にした: {label} {a}-{b}（開始と終了が同じ）"
    if suspect and kind in SUSPECT_NOTE:
        return a, b, f"疑い: {label} {a}-{b}（{SUSPECT_NOTE[kind]}）"
    return a, b, ""


def conflict_note(sector, profile, day, what, on_hours_row=False):
    """曜日の列と時刻の矛盾を、元データの列名で注記にする。

    what は build_opening_hours.find_conflicts が返す内容の文。
    「曜日フラグ」は元データを見る人に通じないので、列名と値の意味で書く。
    on_hours_row が真なら診療科の票の行に書く文で、列が別のファイルにあることを添える。
    """
    closed, opened, time_word = SECTOR_WORDS[sector]
    col = profile["ph"] if day == "祝" else profile["weekly"].format(d=day)
    when = "祝日" if day == "祝" else f"{day}曜"
    where = "施設情報のファイルの" if on_hours_row else ""
    if "時刻が無い" in what:
        return f"疑い: {where}「{col}」が 1（{opened}）だが、{when}の{time_word}が無い"
    here = "この行に" if on_hours_row else ""
    return f"疑い: {where}「{col}」が 0（{closed}）だが、{here}{when}の{time_word}が入っている"


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

    http:// や https:// が無い値には https:// を補う。元データからはどちらか決められないが、
    今のウェブでは http だけのサイトはほとんど無いので、https を採る（2026-10-07 に決定）。
    OSM 向けの clean_url と違い、300文字の上限では落とさない。
    それは OSM のタグ値の上限で、元の値の誤りではないため。
    """
    v = value.strip()
    if not v:
        return value, ""
    if RE_REDIRECT.match(v):
        return "", f"空欄にした: {label} {value}（検索エンジンの転送 URL）"
    # スキームは大文字小文字を区別しない（`HTTP://` も開ける）。
    # build_osm の正規表現は小文字だけを受け付けるので、スキームだけ小文字にして照らす
    lowered = RE_SCHEME.sub(lambda s: s.group(0).lower(), v)
    if RE_URL.match(lowered):
        return value, ""
    m = RE_MISSING_COLON.match(lowered)
    if m:
        # 補うのはコロンだけで、スキームの大文字小文字は元のまま残す
        n = len(m.group(1))
        fixed = f"{v[:n]}://{m.group(2)}"
        return fixed, f"書き換えた: {label} {value} → {fixed}（コロンの脱字）"
    if RE_BARE_DOMAIN.match(v):
        fixed = f"https://{v}"
        return fixed, f"書き換えた: {label} {value} → {fixed}（http:// や https:// が無いので https:// を補った）"
    repaired = repair_url(v)
    if repaired:
        fixed, typos, added = repaired
        parts = []
        if typos:
            parts.append("打ち間違いを直した: " + "、".join(typos))
        if added:
            parts.append("http:// や https:// が無いので https:// を補った")
        why = "。".join(parts)
        return fixed, f"書き換えた: {label} {value} → {fixed}（{why}）"
    return value, f"疑い: {label} {value}（URL として読めない形式）"


def edit_distance(a, b):
    """1文字の挿入、削除、置換を1回と数えた編集距離。"""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def repair_url(v):
    """打ち間違いの程度の崩れを直す。(直した値, 直した箇所の一覧, https:// を補ったか) を返す。

    直した結果がホスト名の形にならないもの、URL が2つ以上あるものは直さず None を返す。
    元データでは http:/、http:www、https;//、htpp://、途中の空白などが見つかった（2026-10-07）。
    www// や www:// は www. の打ち間違いとも読めるので直さない。
    """
    typos = []
    # 先頭の記号を先に除く。半角の「･」は NFKC で全角の「・」になるので、
    # 逆の順では全角を直したと数えてしまう
    head = RE_URL_JUNK.match(v)
    s = v[head.end():]
    if head.group(0):
        typos.append("先頭の余分な文字")
    normalized = unicodedata.normalize("NFKC", s)
    if normalized != s:
        s = normalized
        typos.append("全角の文字")
    if len(RE_URL_SEP.findall(s)) > 1:
        return None
    scheme = None
    if s.startswith("//"):
        scheme, rest = "https", s[2:]
        typos.append("「https:」の抜け")
    else:
        m = RE_URL_HEAD.match(s)
        sep = re.sub(r"\s", "", m.group(2)) if m else ""
        # 区切りにコロン、セミコロン、スラッシュのどれかが要る。ピリオドだけの区切りは
        # hp.example.jp のようなホスト名の一部なので、スキームと見なさない
        if m and m.group(1).lower() != "www" and re.search(r"[:;/]", sep):
            token = m.group(1)
            target = "https" if token.lower().endswith("s") else "http"
            if edit_distance(token.lower(), target) <= URL_SCHEME_MAX_EDITS:
                if token.lower() != target:
                    typos.append(f"「{target}」の綴り")
                    token = target
                if m.group(2) != "://":
                    typos.append("「://」の形")
                scheme, rest = token, s[m.end():]
    if scheme is None:
        rest = s
    if re.search(r"\s", rest):
        rest = re.sub(r"\s+", "", rest)
        typos.append("途中の空白")
    host, slash, path = rest.partition("/")
    if "," in host:
        host = host.replace(",", ".")
        typos.append("ピリオドの代わりのカンマ")
    if ".." in host:
        host = re.sub(r"\.{2,}", ".", host)
        typos.append("重なったピリオド")
    # 「akiba-dental.com.」のように、文の句点が紛れたもの
    if host.endswith("."):
        host = host.rstrip(".")
        typos.append("末尾のピリオド")
    if not RE_URL_HOST.match(host):
        return None
    added = scheme is None
    return f"{scheme or 'https'}://{host}{slash}{path}", typos, added


# build_addr.js と fix_placeholder_coords.js が 座標の理由 に書く文から、理由の句を取り出す
RE_COORD_REASON = re.compile(r"^元データの座標 [-\d.]+, [-\d.]+ [がを](.+?)ため")
# fix_placeholder_coords.js が丸め値に書く句。「0.1度の格子に乗る丸め値の」
RE_GRID = re.compile(r"^([\d.]+)度の格子に乗る丸め値の?$")
# URL のスキーム部分。大文字小文字をそろえて照らすために使う
RE_SCHEME = re.compile(r"^https?(?=:|//)", re.I)
# 打ち間違いを直すときに使う形。
# 先頭の「URL:」や記号、スキームらしい語と区切り、ホスト名、URL の区切り（2つ目の URL を見つける）
RE_URL_JUNK = re.compile(r"^(?:url\s*:\s*|[\s'\"`･・:\-]+)?", re.I)
# スキームらしい語と、その後の区切り（コロン、セミコロン、ピリオド、カンマ、スラッシュ、空白の並び）
RE_URL_HEAD = re.compile(r"^([A-Za-z]{2,7})([\s:;.,/]*)")
# 最後のラベル（.jp や .com）は英字2文字以上とする。tomio.d.c のような値をドメインと見なさない
RE_URL_HOST = re.compile(r"^[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$")
RE_URL_SEP = re.compile(r"h[a-z]{1,5}[:;.,]{0,2}//", re.I)
# スキームらしい語を http か https の打ち間違いと見なす編集距離の上限。
# 2 なら htpps、hyyps、hrrp を直し、hppt（3）は直さない
URL_SCHEME_MAX_EDITS = 2


def coord_reason(raw_lat, raw_lon, geo):
    """元データの座標を使わない理由を、句点を含まない句で返す。"""
    # 元データは座標の無い施設に 0.0, 0.0 を入れている。
    # 「欠損を示す値」と書くと、元の座標を捨てたように読まれたので、座標が無かったことを書く
    if float(raw_lat or 0) == 0 or float(raw_lon or 0) == 0:
        return "元データに座標が無い"
    text = geo.get("座標の理由", "")
    m = RE_COORD_REASON.match(text)
    if not m:
        raise ValueError(f"座標を置き換える理由が読めません: {geo['ID']} {text!r}")
    phrase = m.group(1)
    # 「0.1度の格子に乗る丸め値」では伝わらなかった。
    # 実データには 28.1, 129.2 のほか 33, 130 のような整数もあるので、桁の数は書かない
    if RE_GRID.match(phrase):
        return "小数点以下の桁が少なく、施設の位置を表せない大まかな値"
    return phrase.replace("ジオコーダ座標から", "住所から")


def decide_coord(raw_lat, raw_lon, geo, chiban):
    """座標を決める。(緯度, 経度, 座標の出典, 注記) を返す。

    置き換えるかどうかは既存の処理の判定（geocoded.csv の 座標の出典）に従う。
    置き換え先は位置レベル8の点だけで、住居表示の点を先に使う。
    注記には捨てた座標と理由だけを書く。新しい値は緯度経度の列にあり、注記に重ねない。
    geocoded.csv の 住所_位置レベル が8の点は、nja-osm-tags が地番の点を返さないので
    住居表示の点に限られる。
    """
    if geo["座標の出典"] == "原データ":
        return raw_lat, raw_lon, "原データ", ""
    why = coord_reason(raw_lat, raw_lon, geo)
    if geo["住所_位置レベル"] == "8" and geo["住所_lat"] and geo["住所_lon"]:
        lat, lon = geo["住所_lat"], geo["住所_lon"]
        return lat, lon, "住居表示", (f"書き換えた: 緯度経度 {raw_lat}, {raw_lon} → "
                                    f"住居表示の住所から求めた位置（{why}）")
    if chiban:
        lat, lon = chiban
        return lat, lon, "地番", (f"書き換えた: 緯度経度 {raw_lat}, {raw_lon} → "
                                f"地番の住所から求めた位置（{why}）")
    return "", "", "", (f"空欄にした: 緯度経度 {raw_lat}, {raw_lon}"
                        f"（{why}。住所から建物の位置を特定できなかった）")
