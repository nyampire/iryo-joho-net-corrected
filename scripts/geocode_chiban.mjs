#!/usr/bin/env node
/**
 * 座標を置き換える必要があり、住居表示の点が無い施設について、地番の点を取る。
 *
 * 地番の位置データには登記所備付地図データ利用規約がかかり、OSM には入れられない。
 * nja-osm-tags はこの点を返さないよう止めているので、ここでは NJA を直接呼ぶ。
 * このスクリプトを jp-healthcare-osm ではなくこのリポジトリに置くのは、
 * OSM 向けの処理が地番の点に触れない形を保つため。
 *
 * 入力: output/build/<業態>_geocoded.csv（npm run geocode の生成物）
 * 出力: output/build/chiban_points.csv（業態, ID, lat, lon）
 *
 * 採るのは metadata.chiban.point があり、point.level が 8 の点だけ。
 * 照合結果の level が 8 でも、地番の位置データが無ければ point.level は 2 や 3 になる。
 *
 * 使い方:
 *   NJA_API_BASE=/path/to/japanese-addresses-v2/out/api/ja node scripts/geocode_chiban.mjs
 */
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { config, normalize } from "@geolonia/normalize-japanese-addresses";
import { formatCsv, parseCsvText } from "../vendor/jp-healthcare-osm/vendor/nja-osm-tags/src/csv.ts";
import { API_BASE_ENV, resolveApiBase } from "../vendor/jp-healthcare-osm/vendor/nja-osm-tags/src/apiBase.ts";

const PUBLIC_API_HOST = "japanese-addresses-v2.geoloniamaps.com";
const SECTORS = ["hospital", "clinic", "dental", "maternity", "pharmacy"];
const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");

/** 座標を置き換える行のうち、住居表示の点が無いもの。 */
export function needsChiban(g) {
  return g["座標の出典"] !== "原データ" && g["住所_位置レベル"] !== "8";
}

/** NJA の結果から地番の点を採る。採れなければ null。 */
export function pickChibanPoint(result) {
  if (!result?.metadata?.chiban?.point) return null;
  if (result.point?.level !== 8) return null;
  return { lat: String(result.point.lat), lon: String(result.point.lng) };
}

/**
 * 住所データの取得先を確かめて NJA に設定する。
 * build_addr.js の requireLocalApiBase と同じ理由で、手元の構築物以外は使わない。
 */
function useLocalApiBase() {
  const raw = (process.env[API_BASE_ENV] || "").trim();
  if (!raw) {
    console.error(`住所データの取得先が設定されていません: ${API_BASE_ENV}`);
    console.error("japanese-addresses-v2 を手元に構築し、その out/api/ja を指してください");
    process.exit(2);
  }
  if (raw.includes(PUBLIC_API_HOST)) {
    console.error(`公開 API は使いません: ${raw}`);
    process.exit(2);
  }
  const base = resolveApiBase(raw);
  if (base.startsWith("file://") && !existsSync(fileURLToPath(`${base}.json`))) {
    console.error(`住所データが見つかりません: ${fileURLToPath(`${base}.json`)}`);
    process.exit(2);
  }
  config.japaneseAddressesApi = base;
  console.error(`住所データの取得先: ${base}`);
}

function readRows(file) {
  const [header, ...rows] = parseCsvText(readFileSync(file, "utf8"));
  return rows
    .filter((r) => r.length > 1)
    .map((r) => Object.fromEntries(header.map((h, i) => [h, r[i] ?? ""])));
}

async function main() {
  useLocalApiBase();
  const out = [["業態", "ID", "lat", "lon"]];
  for (const sector of SECTORS) {
    const file = path.join(ROOT, "output", "build", `${sector}_geocoded.csv`);
    if (!existsSync(file)) {
      console.error(`入力がありません: ${file}`);
      console.error("先に npm run geocode を実行してください");
      process.exit(2);
    }
    const targets = readRows(file).filter(needsChiban);
    let found = 0;
    let failed = 0;
    for (const g of targets) {
      let result;
      try {
        result = await normalize(g["元_所在地"]);
      } catch (e) {
        failed++;
        console.error(`${sector} ${g["ID"]}: ${e.message}`);
        continue;
      }
      const p = pickChibanPoint(result);
      if (p) {
        out.push([sector, g["ID"], p.lat, p.lon]);
        found++;
      }
    }
    console.log(`${sector}: 対象 ${targets.length} / 地番の点 ${found} / 失敗 ${failed}`);
  }
  const dir = path.join(ROOT, "output", "build");
  mkdirSync(dir, { recursive: true });
  writeFileSync(path.join(dir, "chiban_points.csv"), "﻿" + formatCsv(out));
}

if (import.meta.main) await main();
