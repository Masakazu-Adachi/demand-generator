#!/usr/bin/env python3
"""佐倉倉庫（香川電力・高圧）の2026年・時間別デマンドを作る。

電気料金明細には「検針期間の使用電力量（kWh）」と「最大需要電力（kW）」しかない。
このスクリプトは次の順で、入力テンプレート（日付 × 0時〜23時）を埋める。

1. 佐倉市の日平均気温から、その日の電気の「強さ」を計算する。
2. 強さに、倉庫の時間パターン（平日は日中高く、土日祝は低い）を掛ける。
3. 明細がある検針期間は、期間の合計が明細のkWhと一致するよう倍率で補正する。
4. 明細がまだない日（2026-08-11以降）は、補正せず予測値のまま入れる。

実行場所: プロジェクトルート（app.py があるディレクトリ）

    python3 scripts/build_sakura_2026_demand.py

9月分以降の明細が来たら、下の PERIODS に1行足して、同じコマンドを再実行する。
足した期間は自動で「予測」から「明細補正」に変わる。

標準ライブラリだけで動く。追加の pip install は不要。
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEATHER_PATH = ROOT / "data" / "sakura_daily_temperature.json"
TEMPLATE_PATH = ROOT / "output" / "入力テンプレート_2026.csv"
PERIOD_CHECK_PATH = ROOT / "output" / "佐倉倉庫_2026_検針期間チェック.csv"
MONTHLY_PATH = ROOT / "output" / "佐倉倉庫_2026_月別サマリ.csv"
DAILY_PATH = ROOT / "output" / "佐倉倉庫_2026_日別.csv"
README_PATH = ROOT / "output" / "佐倉倉庫_2026_読み方.txt"

# 佐倉市中心付近。倉庫は六崎だが、気温の差はモデルの誤差より小さい。
LATITUDE = 35.7235
LONGITUDE = 140.224

# アプリ（app.py）のプリセット「倉庫（日中のみ）」と同じ形。
# 平日のピーク時刻を 1.0 としたときの係数。休日は終日 HOLIDAY_RATIO。
# 休日に倉庫が動く場合は、この値を 0.5（半日程度）や 1.0（平日と同じ）に変えて再実行する。
HOLIDAY_RATIO = 0.20
WEEKDAY_SHAPE = [
    1, 1, 1, 1, 1, 1,
    2, 4,
    8, 8, 8, 8,
    6,
    8, 8, 8, 8,
    4, 2,
    1, 1, 1, 1, 1,
]
WEEKDAY_COEF = [v / max(WEEKDAY_SHAPE) for v in WEEKDAY_SHAPE]

# 日平均気温がこの値を下回ると暖房、上回ると冷房が増える、という折れ点。
# 2025-11〜2026-08 の明細10期間で、期間合計のずれが小さくなる組み合わせを選んだ。
HEAT_BASE_C = 14.0
COOL_BASE_C = 20.0

# 暑い日は午後へ、寒い日は朝夕へ、同じ日量のまま少し寄せる（自家消費の時刻合わせ用）。
# 夏は午後を厚くして、明細の最大需要電力（暑い日の8kW）に近づける。
# 冬の朝への寄せは弱めにする。強くすると朝だけ6kWで頭打ちになり、11時が急に落ちて見える。
COOL_TILT_PER_DEGREE = 0.05
HEAT_TILT_PER_DEGREE = 0.02
COOL_HOURS = range(11, 18)  # 11時〜17時
HEAT_HOURS = list(range(7, 12)) + list(range(17, 21))  # 7時〜11時と17時〜20時

# 明細がない日の上限。直近明細の契約電力・最大需要電力が 8kW。
FORECAST_PEAK_CAP_KW = 8.0

YEAR = 2026

# 明細から読み取った値。kWh は全日電力量（料金計算の数量と一致）。
# peak_kw は、その請求月に載っている最大需要電力（30分値）。
# 日付はその明細の「ご使用期間」（両端を含む）。
PERIODS = [
    ("2025年12月分", date(2025, 11, 11), date(2025, 12, 10), 1473, 7.0),
    ("2026年1月分", date(2025, 12, 11), date(2026, 1, 10), 1323, 6.0),
    ("2026年2月分", date(2026, 1, 11), date(2026, 2, 10), 1507, 6.0),
    ("2026年3月分", date(2026, 2, 11), date(2026, 3, 10), 1153, 6.0),
    ("2026年4月分", date(2026, 3, 11), date(2026, 4, 10), 1118, 5.0),
    ("2026年5月分", date(2026, 4, 11), date(2026, 5, 10), 992, 6.0),
    ("2026年6月分", date(2026, 5, 11), date(2026, 6, 10), 1123, 6.0),
    # 7月分は夏季（7/1〜）とその他季で数量が分かれていたので、2行に分けてある。
    ("2026年7月分・その他季", date(2026, 6, 11), date(2026, 6, 30), 856, 7.0),
    ("2026年7月分・夏季", date(2026, 7, 1), date(2026, 7, 10), 499, 7.0),
    ("2026年8月分", date(2026, 7, 11), date(2026, 8, 10), 1795, 8.0),
]

# 内閣府の公表に沿った祝日（holidays-jp の 2025/2026 一覧と一致）。
HOLIDAYS = {
    date(2025, 1, 1), date(2025, 1, 13),
    date(2025, 2, 11), date(2025, 2, 23), date(2025, 2, 24),
    date(2025, 3, 20),
    date(2025, 4, 29),
    date(2025, 5, 3), date(2025, 5, 4), date(2025, 5, 5), date(2025, 5, 6),
    date(2025, 7, 21),
    date(2025, 8, 11),
    date(2025, 9, 15), date(2025, 9, 23),
    date(2025, 10, 13),
    date(2025, 11, 3), date(2025, 11, 23), date(2025, 11, 24),
    date(2026, 1, 1), date(2026, 1, 12),
    date(2026, 2, 11), date(2026, 2, 23),
    date(2026, 3, 20),
    date(2026, 4, 29),
    date(2026, 5, 3), date(2026, 5, 4), date(2026, 5, 5), date(2026, 5, 6),
    date(2026, 7, 20),
    date(2026, 8, 11),
    date(2026, 9, 21), date(2026, 9, 22), date(2026, 9, 23),
    date(2026, 10, 12),
    date(2026, 11, 3), date(2026, 11, 23),
}

WEEKDAY_JA = "月火水木金土日"


def inclusive_dates(start: date, end: date):
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def is_closed_day(day: date) -> bool:
    """土日または祝日なら、倉庫は休みとみなす。"""
    return day.weekday() >= 5 or day in HOLIDAYS


def shape_coef(day: date, holiday_ratio: float) -> list[float]:
    if is_closed_day(day):
        return [holiday_ratio] * 24
    return list(WEEKDAY_COEF)


def tilt_shape(coef: list[float], hdd: float, cdd: float) -> list[float]:
    """日量は変えず、暑い日は午後、寒い日は朝夕に寄せる。"""
    weights = list(coef)
    if cdd > 0:
        factor = 1.0 + COOL_TILT_PER_DEGREE * cdd
        for hour in COOL_HOURS:
            weights[hour] *= factor
    if hdd > 0:
        factor = 1.0 + HEAT_TILT_PER_DEGREE * hdd
        for hour in HEAT_HOURS:
            weights[hour] *= factor
    original = sum(coef)
    tilted = sum(weights)
    if tilted <= 0:
        return list(coef)
    scale = original / tilted
    return [w * scale for w in weights]


def degree_days(tmean: float) -> tuple[float, float]:
    hdd = max(0.0, HEAT_BASE_C - tmean)
    cdd = max(0.0, tmean - COOL_BASE_C)
    return hdd, cdd


def solve_linear(matrix: list[list[float]], target: list[float]) -> list[float]:
    """ガウス消去。列が独立でないときは例外にする。"""
    size = len(target)
    rows = [matrix[i][:] + [target[i]] for i in range(size)]
    for col in range(size):
        pivot = max(range(col, size), key=lambda r: abs(rows[r][col]))
        if abs(rows[pivot][col]) < 1e-12:
            raise ZeroDivisionError("singular")
        rows[col], rows[pivot] = rows[pivot], rows[col]
        divisor = rows[col][col]
        for j in range(col, size + 1):
            rows[col][j] /= divisor
        for r in range(size):
            if r == col:
                continue
            factor = rows[r][col]
            for j in range(col, size + 1):
                rows[r][j] -= factor * rows[col][j]
    return [rows[i][size] for i in range(size)]


def fit_nonnegative(x_rows: list[list[float]], y: list[float]) -> tuple[list[float], float]:
    """係数がマイナスにならない最小二乗。戻り値は (係数, MAPE)。"""
    width = len(x_rows[0])
    best: tuple[float, list[float]] | None = None
    for mask in range(1, 2**width):
        cols = [j for j in range(width) if mask & (1 << j)]
        ata = [[0.0 for _ in cols] for _ in cols]
        aty = [0.0 for _ in cols]
        for row, yi in zip(x_rows, y):
            for a, j in enumerate(cols):
                aty[a] += row[j] * yi
                for b, k in enumerate(cols):
                    ata[a][b] += row[j] * row[k]
        try:
            beta = solve_linear(ata, aty)
        except ZeroDivisionError:
            continue
        if any(value < -1e-8 for value in beta):
            continue
        coef = [0.0] * width
        for a, j in enumerate(cols):
            coef[j] = max(0.0, beta[a])
        abs_pct = 0.0
        for row, yi in zip(x_rows, y):
            pred = sum(coef[j] * row[j] for j in range(width))
            abs_pct += abs(pred - yi) / yi
        mape = abs_pct / len(y)
        if best is None or mape < best[0]:
            best = (mape, coef)
    if best is None:
        raise RuntimeError("気温モデルの係数を決められませんでした。")
    return best[1], best[0]


def period_design_row(start: date, end: date, temps: dict[date, float], holiday_ratio: float) -> list[float]:
    sum_shape = 0.0
    sum_shape_hdd = 0.0
    sum_shape_cdd = 0.0
    for day in inclusive_dates(start, end):
        daily_shape = sum(shape_coef(day, holiday_ratio))
        hdd, cdd = degree_days(temps[day])
        sum_shape += daily_shape
        sum_shape_hdd += daily_shape * hdd
        sum_shape_cdd += daily_shape * cdd
    return [sum_shape, sum_shape_hdd, sum_shape_cdd]


def enforce_cap(values: list[float], cap: float) -> list[float]:
    """合計を保ったまま、各時間を cap 以下に収める。"""
    capped = list(values)
    for _ in range(60):
        excess = 0.0
        for i, value in enumerate(capped):
            if value > cap:
                excess += value - cap
                capped[i] = cap
        if excess <= 1e-8:
            return capped
        room_index = [i for i, value in enumerate(capped) if value < cap - 1e-9]
        room = sum(cap - capped[i] for i in room_index)
        if room <= 1e-8:
            raise RuntimeError("最大需要電力の上限に収められませんでした。")
        for i in room_index:
            capped[i] += excess * ((cap - capped[i]) / room)
    raise RuntimeError("最大需要電力の上限処理が収束しませんでした。")


def cents_from_kw(value: float) -> int:
    return int(math.floor(value * 100 + 0.5))


def place_residual(cents: list[int], target: int, cap_cents: int) -> None:
    """四捨五入の端数を、0〜上限の範囲で 0.01kWh ずつ散らす。"""
    diff = target - sum(cents)
    if diff == 0:
        return
    step = 1 if diff > 0 else -1
    remaining = abs(diff)
    order = list(range(len(cents)))
    if step > 0:
        order.sort(key=lambda i: cents[i])
    else:
        order.sort(key=lambda i: -cents[i])
    guard = 0
    cursor = 0
    limit = remaining * len(cents) + 5
    while remaining > 0 and guard < limit:
        i = order[cursor % len(order)]
        new_value = cents[i] + step
        if 0 <= new_value <= cap_cents:
            cents[i] = new_value
            remaining -= 1
        cursor += 1
        guard += 1
    if remaining:
        raise RuntimeError(f"端数 {remaining}（0.01kWh単位）を配分できませんでした。")


def fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "sakura-demand/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def open_meteo_daily(url: str) -> dict[date, dict]:
    payload = fetch_json(url)
    if "daily" not in payload:
        raise RuntimeError(f"気温の取得に失敗しました: {payload}")
    daily = payload["daily"]
    found: dict[date, dict] = {}
    for raw_day, tmean, tmax, tmin in zip(
        daily["time"],
        daily["temperature_2m_mean"],
        daily["temperature_2m_max"],
        daily["temperature_2m_min"],
    ):
        if tmean is None:
            continue
        found[date.fromisoformat(raw_day)] = {
            "tmean": float(tmean),
            "tmax": None if tmax is None else float(tmax),
            "tmin": None if tmin is None else float(tmin),
        }
    return found


def download_weather(today: date) -> dict:
    """観測を優先し、近い未来は予報、残りは前年同日で埋める。"""
    end = today - timedelta(days=1)
    observed: dict[date, dict] = {}
    for _ in range(6):
        url = (
            "https://archive-api.open-meteo.com/v1/archive"
            f"?latitude={LATITUDE}&longitude={LONGITUDE}"
            f"&start_date=2025-01-01&end_date={end.isoformat()}"
            "&daily=temperature_2m_mean,temperature_2m_max,temperature_2m_min"
            "&timezone=Asia%2FTokyo"
        )
        try:
            observed = open_meteo_daily(url)
            break
        except Exception:
            end -= timedelta(days=1)
    if not observed:
        raise RuntimeError("過去気温を取得できませんでした。")

    forecast_url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={LATITUDE}&longitude={LONGITUDE}"
        "&daily=temperature_2m_mean,temperature_2m_max,temperature_2m_min"
        "&timezone=Asia%2FTokyo&forecast_days=16"
    )
    forecast = open_meteo_daily(forecast_url)

    days: dict[str, dict] = {}
    cursor = date(2025, 1, 1)
    last = date(YEAR, 12, 31)
    while cursor <= last:
        if cursor in observed:
            item = dict(observed[cursor])
            item["source"] = "観測"
        elif cursor in forecast:
            item = dict(forecast[cursor])
            item["source"] = f"予報（{today.isoformat()}時点）"
        else:
            previous = date(cursor.year - 1, cursor.month, cursor.day)
            if previous not in observed:
                raise RuntimeError(f"{cursor.isoformat()} の気温がありません。")
            item = dict(observed[previous])
            item["source"] = "2025年同日の気温で代用"
        days[cursor.isoformat()] = item
        cursor += timedelta(days=1)

    return {
        "meta": {
            "latitude": LATITUDE,
            "longitude": LONGITUDE,
            "location": "千葉県佐倉市中心付近（対象倉庫は佐倉市六崎）",
            "fetched_on": today.isoformat(),
            "observed_through": end.isoformat(),
            "note": "Open-Meteo の日平均気温。11月中旬以降で観測も予報もない日は、2025年の同じ日付で代用。",
        },
        "days": days,
    }


def load_weather(refresh: bool, today: date) -> dict[date, dict]:
    if refresh or not WEATHER_PATH.exists():
        payload = download_weather(today)
        WEATHER_PATH.parent.mkdir(parents=True, exist_ok=True)
        WEATHER_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"気温を保存しました: {WEATHER_PATH}")
    else:
        payload = json.loads(WEATHER_PATH.read_text(encoding="utf-8"))
        print(f"保存済みの気温を使います: {WEATHER_PATH}")
    loaded = {}
    for raw_day, item in payload["days"].items():
        loaded[date.fromisoformat(raw_day)] = item
    return loaded


def write_csv(path: Path, rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\r\n")
        writer.writerows(rows)


def check_periods() -> None:
    expected_days = {
        "2025年12月分": 30,
        "2026年1月分": 31,
        "2026年2月分": 31,
        "2026年3月分": 28,
        "2026年4月分": 31,
        "2026年5月分": 30,
        "2026年6月分": 31,
        "2026年7月分・その他季": 20,
        "2026年7月分・夏季": 10,
        "2026年8月分": 31,
    }
    covered: set[date] = set()
    for name, start, end, _kwh, _peak in PERIODS:
        count = (end - start).days + 1
        if count != expected_days[name]:
            raise RuntimeError(f"{name} の日数が明細と違います: {count}")
        for day in inclusive_dates(start, end):
            if day in covered:
                raise RuntimeError(f"検針期間が重なっています: {day.isoformat()} / {name}")
            covered.add(day)


def build(holiday_ratio: float, weather: dict[date, dict]) -> dict:
    check_periods()
    temps = {day: float(item["tmean"]) for day, item in weather.items()}
    needed = []
    for _name, start, end, _kwh, _peak in PERIODS:
        needed.extend(inclusive_dates(start, end))
    needed.extend(inclusive_dates(date(YEAR, 1, 1), date(YEAR, 12, 31)))
    missing = [day for day in needed if day not in temps]
    if missing:
        raise RuntimeError(f"気温が足りません: {missing[0].isoformat()} ほか {len(missing)} 日")

    design = []
    actual = []
    for name, start, end, kwh, _peak in PERIODS:
        design.append(period_design_row(start, end, temps, holiday_ratio))
        actual.append(float(kwh))
    coef, mape = fit_nonnegative(design, actual)
    base, heat_coef, cool_coef = coef

    records: dict[date, dict] = {}
    first = min(start for _n, start, _e, _k, _p in PERIODS)
    for day in inclusive_dates(first, date(YEAR, 12, 31)):
        hdd, cdd = degree_days(temps[day])
        intensity = base + heat_coef * hdd + cool_coef * cdd
        weights = tilt_shape(shape_coef(day, holiday_ratio), hdd, cdd)
        hours = [intensity * weight for weight in weights]
        records[day] = {
            "hours": hours,
            "pre_kwh": sum(hours),
            "kind": "予測",
            "period": "",
            "cap": FORECAST_PEAK_CAP_KW,
            "tmean": temps[day],
            "source": weather[day]["source"],
            "closed": is_closed_day(day),
        }

    period_reports = []
    for name, start, end, kwh, peak in PERIODS:
        days = list(inclusive_dates(start, end))
        modeled = sum(records[day]["pre_kwh"] for day in days)
        if modeled <= 0:
            raise RuntimeError(f"{name} の予測合計が 0 です。")
        factor = kwh / modeled
        scaled_hours: list[float] = []
        for day in days:
            scaled = [value * factor for value in records[day]["hours"]]
            records[day]["hours"] = scaled
            records[day]["kind"] = "明細で補正"
            records[day]["period"] = name
            records[day]["cap"] = peak
            scaled_hours.extend(scaled)
        capped = enforce_cap(scaled_hours, peak)
        cursor = 0
        for day in days:
            records[day]["hours"] = capped[cursor:cursor + 24]
            cursor += 24
        cents: list[int] = []
        for day in days:
            day_cents = [cents_from_kw(value) for value in records[day]["hours"]]
            records[day]["cents"] = day_cents
            cents.extend(day_cents)
        place_residual(cents, int(round(kwh * 100)), cents_from_kw(peak))
        cursor = 0
        for day in days:
            records[day]["cents"] = cents[cursor:cursor + 24]
            cursor += 24
        in_template = 0
        outside = 0
        peak_in_template = 0
        for day in days:
            day_sum = sum(records[day]["cents"])
            if day.year == YEAR:
                in_template += day_sum
                peak_in_template = max(peak_in_template, max(records[day]["cents"]))
            else:
                outside += day_sum
        period_reports.append({
            "name": name,
            "start": start,
            "end": end,
            "days": len(days),
            "bill_kwh": kwh,
            "modeled_kwh": modeled,
            "factor": factor,
            "in_template_kwh": in_template / 100,
            "outside_kwh": outside / 100,
            "total_kwh": (in_template + outside) / 100,
            "peak_kw": peak,
            "template_peak_kw": peak_in_template / 100,
        })

    for day, record in records.items():
        if "cents" in record:
            continue
        capped = enforce_cap(record["hours"], record["cap"])
        record["hours"] = capped
        record["cents"] = [cents_from_kw(value) for value in capped]

    return {
        "records": records,
        "coef": coef,
        "mape": mape,
        "periods": period_reports,
        "holiday_ratio": holiday_ratio,
    }


def kw_text(cents: int) -> str:
    return f"{cents / 100:.2f}"


def write_outputs(result: dict, weather_meta_note: str) -> None:
    records: dict[date, dict] = result["records"]
    header = ["日付"] + [f"{hour}時" for hour in range(24)]
    template_rows = [header]
    daily_rows = [[
        "日付", "曜日", "営業区分", "日平均気温", "気温の出所",
        "補正前kWh", "日合計kWh", "日最大kW", "区分", "検針期間",
    ]]
    for day in inclusive_dates(date(YEAR, 1, 1), date(YEAR, 12, 31)):
        record = records[day]
        cents = record["cents"]
        template_rows.append(
            [day.strftime("%Y/%m/%d")] + [kw_text(value) for value in cents]
        )
        daily_rows.append([
            day.strftime("%Y/%m/%d"),
            WEEKDAY_JA[day.weekday()],
            "休日" if record["closed"] else "営業日",
            f"{record['tmean']:.1f}",
            record["source"],
            f"{record['pre_kwh']:.2f}",
            kw_text(sum(cents)),
            kw_text(max(cents)),
            record["kind"],
            record["period"],
        ])

    period_rows = [[
        "検針期間", "開始", "終了", "日数", "明細kWh", "補正前kWh", "補正倍率",
        "テンプレートに入ったkWh", "テンプレート外kWh", "補正後の合計kWh", "明細との差kWh",
        "明細の最大需要電力kW", "テンプレート内の最大kW",
    ]]
    for item in result["periods"]:
        period_rows.append([
            item["name"],
            item["start"].isoformat(),
            item["end"].isoformat(),
            item["days"],
            item["bill_kwh"],
            f"{item['modeled_kwh']:.1f}",
            f"{item['factor']:.4f}",
            f"{item['in_template_kwh']:.2f}",
            f"{item['outside_kwh']:.2f}",
            f"{item['total_kwh']:.2f}",
            f"{item['total_kwh'] - item['bill_kwh']:.2f}",
            f"{item['peak_kw']:.1f}",
            f"{item['template_peak_kw']:.2f}",
        ])

    monthly_rows = [[
        "月", "日数", "合計kWh", "最大kW", "平均kW",
        "明細補正kWh", "予測kWh", "扱い",
    ]]
    month_stats = []
    for month in range(1, 13):
        days = [
            day for day in inclusive_dates(date(YEAR, 1, 1), date(YEAR, 12, 31))
            if day.month == month
        ]
        total = sum(sum(records[day]["cents"]) for day in days)
        corrected = sum(
            sum(records[day]["cents"]) for day in days if records[day]["kind"] == "明細で補正"
        )
        forecast = total - corrected
        peak = max(max(records[day]["cents"]) for day in days)
        hours = 24 * len(days)
        if corrected == 0:
            label = "予測"
        elif forecast == 0:
            label = "明細で補正"
        else:
            label = "一部予測"
        monthly_rows.append([
            f"{month}月",
            len(days),
            kw_text(total),
            kw_text(peak),
            f"{(total / 100) / hours:.2f}",
            kw_text(corrected),
            kw_text(forecast),
            label,
        ])
        month_stats.append({
            "month": month,
            "days": len(days),
            "kwh": total / 100,
            "peak": peak / 100,
            "corrected": corrected / 100,
            "forecast": forecast / 100,
            "label": label,
        })

    write_csv(TEMPLATE_PATH, template_rows)
    write_csv(DAILY_PATH, daily_rows)
    write_csv(PERIOD_CHECK_PATH, period_rows)
    write_csv(MONTHLY_PATH, monthly_rows)
    README_PATH.write_text(
        render_readme(result, month_stats, weather_meta_note),
        encoding="utf-8",
    )


def render_readme(result: dict, month_stats: list[dict], weather_note: str) -> str:
    records = result["records"]
    base, heat_coef, cool_coef = result["coef"]
    annual = sum(item["kwh"] for item in month_stats)
    corrected = sum(item["corrected"] for item in month_stats)
    forecast = sum(item["forecast"] for item in month_stats)
    lines = []
    lines.append("佐倉倉庫 2026年デマンド（入力テンプレート）の読み方")
    lines.append("")
    lines.append("■ どれをシミュレーションに入れるか")
    lines.append("  output/入力テンプレート_2026.csv")
    lines.append("  列は添付テンプレートと同じです（日付と、0時から23時まで）。")
    lines.append("  各マスの単位は kWh です。1時間の平均kWと同じ数値です。")
    lines.append("")
    lines.append("■ 年間の合計")
    lines.append(f"  2026年の合計: {annual:,.0f} kWh")
    lines.append(f"  うち明細で合計を合わせた分: {corrected:,.0f} kWh")
    lines.append(f"  うち予測（2026-08-11〜12-31）: {forecast:,.0f} kWh")
    lines.append("")
    lines.append("■ 月ごとの合計")
    lines.append("  月    合計kWh   最大kW   扱い")
    for item in month_stats:
        lines.append(
            f"  {item['month']:2d}月  {item['kwh']:8.1f}  {item['peak']:6.2f}   {item['label']}"
        )
    lines.append("")
    lines.append("■ 明細がある期間は、すでに補正してある")
    lines.append("  検針は毎月10日前後で、暦月とはずれています。")
    lines.append("  例えば「2026年1月分」の明細は 2025-12-11〜2026-01-10 の 1,323 kWh です。")
    lines.append("  このうち 2026-01-01〜01-10 だけをテンプレートに入れ、残りは2025年側です。")
    lines.append("  1月11日以降は「2026年2月分」の明細で補正しています。")
    lines.append("  だから、テンプレートの1月合計を 1,323 kWh に置き換えないでください。")
    lines.append("  明細との突合は output/佐倉倉庫_2026_検針期間チェック.csv を見てください。")
    lines.append("  「補正後の合計kWh」が明細kWhと一致していれば成功です。")
    lines.append("")
    lines.append("■ 予測している日")
    lines.append("  手元の明細は 2026-08-10 までです。2026-08-11 から 12-31 は予測です。")
    lines.append("  8月は 8/1〜8/10 が明細補正、8/11〜8/31 が予測なので「一部予測」です。")
    lines.append("  9月〜12月は全日が予測です。")
    lines.append("")
    lines.append("■ 時間の形（ここが仮定です）")
    lines.append("  明細には時間帯がないので、アプリの「倉庫（日中のみ）」を使いました。")
    lines.append("  平日: 0〜6時と19〜23時は低く、8〜17時が高い（12時は昼休みで少し下がる）。")
    lines.append(f"  土日祝: 終日、平日ピークの {result['holiday_ratio'] * 100:.0f}% です。")
    lines.append("  1日の電力量にすると、休日は平日のおよそ4割です。")
    lines.append("  倉庫が土曜も動くなら、scripts/build_sakura_2026_demand.py の")
    lines.append("  HOLIDAY_RATIO を 0.5 や 1.0 に変えて、同じコマンドを再実行してください。")
    lines.append("  明細がある期間の合計kWhは、比率を変えても明細と一致したままです。")
    lines.append("  変わるのは、平日と休日の配分と、8月11日以降の予測量です。")
    lines.append("")
    lines.append("■ 気温で日ごとの量を変えている")
    lines.append(
        f"  平日ピークの強さ I = {base:.3f} + {heat_coef:.3f}×暖房度 + {cool_coef:.3f}×冷房度"
    )
    lines.append(f"  暖房度 = 日平均気温が {HEAT_BASE_C:.0f}℃を下回った分")
    lines.append(f"  冷房度 = 日平均気温が {COOL_BASE_C:.0f}℃を上回った分")
    lines.append(
        f"  補正前のモデルは、明細10期間に対して平均 {result['mape'] * 100:.1f}% のずれでした。"
    )
    lines.append("  そのずれは、期間ごとの倍率で吸収しています（補正倍率の列）。")
    lines.append("  明細の最大需要電力は30分間の最大で、テンプレートは1時間の平均です。")
    lines.append("  1時間平均がその最大需要電力を超えないよう、上限をかけています。")
    lines.append("  寒い朝や暑い午後は、上限ちょうどまで上がることがあります。")
    lines.append("  上限に届かない月は、30分だけ出た尖りを1時間に広げていないためです。")
    lines.append("")
    lines.append("■ 予測に使った気温")
    lines.append(f"  {weather_note}")
    lines.append("  8月11日〜10月28日ころは2026年の観測気温です。")
    lines.append("  その翌日から約2週間は、気温を取得した日の予報です。")
    lines.append("  予報もない先（おおよそ11月中旬〜12月31日）は、2025年の同じ日付の気温です。")
    lines.append("  補正前のずれから見て、9〜10月の予測はおおよそ±10%、")
    lines.append("  11〜12月は冬の稼働が年で振れるのでおおよそ±15%の幅を見てください。")
    lines.append("  小数第2位は、期間合計を明細の整数kWhに合わせるための桁です。")
    lines.append("  時間ごとの精度が 0.01kW という意味ではありません。")
    lines.append("")
    lines.append("■ 次の明細が来たときの直し方")
    lines.append("  1. 明細の「ご使用期間」「全日電力量」「最大需要電力」を控える。")
    lines.append("  2. scripts/build_sakura_2026_demand.py の PERIODS の末尾に1行足す。")
    lines.append("     例: (\"2026年9月分\", date(2026, 8, 11), date(2026, 9, 10), 1234, 7.0),")
    lines.append("     日付と kWh と kW は明細の数字に置き換える。")
    lines.append("  3. プロジェクトルートで次を実行する。")
    lines.append("     python3 scripts/build_sakura_2026_demand.py")
    lines.append("  4. output/佐倉倉庫_2026_検針期間チェック.csv の差が 0.00 か確認する。")
    lines.append("")
    lines.append("■ この予測に入っていないもの")
    lines.append("  年末年始の特別休業（12/29〜1/3のうち、祝日でない日）は入れていません。")
    lines.append("  止める日が分かっていれば、その日の24時間を休日並みに下げてください。")
    return "\n".join(lines) + "\n"


def validate(result: dict) -> None:
    records = result["records"]
    template_days = list(inclusive_dates(date(YEAR, 1, 1), date(YEAR, 12, 31)))
    if len(template_days) != 365:
        raise RuntimeError("2026年は365日である必要があります。")
    for item in result["periods"]:
        gap = abs(item["total_kwh"] - item["bill_kwh"])
        if gap > 0.001:
            raise RuntimeError(f"{item['name']} の合計が明細と違います: 差 {gap}")
        for day in inclusive_dates(item["start"], item["end"]):
            if max(records[day]["cents"]) > cents_from_kw(item["peak_kw"]):
                raise RuntimeError(f"{item['name']} で最大需要電力を超えています: {day}")
            if min(records[day]["cents"]) < 0:
                raise RuntimeError(f"マイナスのデマンドがあります: {day}")
    forecast_days = [
        day for day in template_days if records[day]["kind"] == "予測"
    ]
    if not forecast_days or forecast_days[0] != date(YEAR, 8, 11):
        raise RuntimeError("予測の開始日が 2026-08-11 ではありません。")
    if forecast_days[-1] != date(YEAR, 12, 31):
        raise RuntimeError("予測が年末まで続いていません。")


def print_report(result: dict) -> None:
    base, heat_coef, cool_coef = result["coef"]
    print("")
    print(
        f"モデル: I = {base:.3f} + {heat_coef:.3f}*HDD + {cool_coef:.3f}*CDD"
        f"   補正前MAPE {result['mape'] * 100:.1f}%"
    )
    print(f"{'期間':<16} {'明細':>8} {'補正前':>8} {'倍率':>7} {'入った':>8} {'外':>8} {'最大':>6}")
    for item in result["periods"]:
        print(
            f"{item['name']:<16} {item['bill_kwh']:8.0f} {item['modeled_kwh']:8.1f}"
            f" {item['factor']:7.3f} {item['in_template_kwh']:8.1f}"
            f" {item['outside_kwh']:8.1f} {item['template_peak_kw']:6.2f}"
        )
    records = result["records"]
    print("")
    print(f"{'月':<4} {'kWh':>10} {'最大kW':>8} {'補正':>10} {'予測':>10}")
    annual = 0.0
    for month in range(1, 13):
        days = [
            day for day in inclusive_dates(date(YEAR, 1, 1), date(YEAR, 12, 31))
            if day.month == month
        ]
        total = sum(sum(records[day]["cents"]) for day in days) / 100
        corrected = sum(
            sum(records[day]["cents"])
            for day in days
            if records[day]["kind"] == "明細で補正"
        ) / 100
        peak = max(max(records[day]["cents"]) for day in days) / 100
        annual += total
        print(f"{month:<4} {total:10.2f} {peak:8.2f} {corrected:10.2f} {total - corrected:10.2f}")
    print(f"年間 {annual:.2f} kWh")


def main() -> None:
    parser = argparse.ArgumentParser(description="佐倉倉庫の2026年デマンドを作ります。")
    parser.add_argument(
        "--refresh-weather",
        action="store_true",
        help="保存済みの気温を使わず、Open-Meteo から取り直す",
    )
    parser.add_argument(
        "--holiday-ratio",
        type=float,
        default=HOLIDAY_RATIO,
        help="休日の電力を、平日ピークの何倍にするか（初期値 0.20）",
    )
    args = parser.parse_args()
    if not 0 < args.holiday_ratio <= 1.5:
        raise SystemExit("holiday-ratio は 0 より大きく 1.5 以下にしてください。")

    today = date.today()
    weather = load_weather(args.refresh_weather, today)
    meta = {}
    if WEATHER_PATH.exists():
        meta = json.loads(WEATHER_PATH.read_text(encoding="utf-8")).get("meta", {})
    result = build(args.holiday_ratio, weather)
    validate(result)
    note = meta.get("note", "")
    fetched = meta.get("fetched_on", "不明")
    observed = meta.get("observed_through", "不明")
    weather_note = f"気温の取得日 {fetched}、観測の最終日 {observed}。{note}"
    write_outputs(result, weather_note)
    print_report(result)
    print("")
    print(f"テンプレート: {TEMPLATE_PATH}")
    print(f"読み方: {README_PATH}")


if __name__ == "__main__":
    main()
