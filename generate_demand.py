import pandas as pd
import numpy as np
import datetime
import calendar

# ==========================================
# 1. 入力データ定義 (ユーザー設定エリア)
# ==========================================

# 2024年の対象月ごとの「契約電力(kW)」と「使用電力量(kWh)」
# ※ここを実際のデータに書き換えて使用してください。
MONTHLY_TARGETS = {
    1:  {'peak_kw': 50.0, 'total_kwh': 22000},
    2:  {'peak_kw': 50.0, 'total_kwh': 20000},
    3:  {'peak_kw': 45.0, 'total_kwh': 19000},
    4:  {'peak_kw': 45.0, 'total_kwh': 18000},
    5:  {'peak_kw': 50.0, 'total_kwh': 20000},
    6:  {'peak_kw': 55.0, 'total_kwh': 24000},
    7:  {'peak_kw': 60.0, 'total_kwh': 28000},
    8:  {'peak_kw': 60.0, 'total_kwh': 30000},
    9:  {'peak_kw': 55.0, 'total_kwh': 26000},
    10: {'peak_kw': 45.0, 'total_kwh': 20000},
    11: {'peak_kw': 45.0, 'total_kwh': 19000},
    12: {'peak_kw': 50.0, 'total_kwh': 23000},
}

# ==========================================
# 2. パターン定義 (0:00 ~ 23:00 の係数)
# ==========================================

# コンビニ（昼ピーク型）を想定したパターン
# 平日: 日中(7時-22時)は高く、深夜は低い
PATTERN_WEEKDAY = [
    0.3, 0.3, 0.3, 0.3, 0.4, 0.5,  # 0-5時
    0.6, 0.8, 0.9, 0.9, 1.0, 1.0,  # 6-11時 (昼ピーク)
    1.0, 1.0, 0.9, 0.9, 0.9, 0.8,  # 12-17時
    0.7, 0.6, 0.5, 0.4, 0.4, 0.3   # 18-23時
]

# 休日: 平日のパターンをベースに少し下げる (例: 0.8倍)
# ※ここでは単純に全体を少し下げつつ、形は維持する設定にします
PATTERN_HOLIDAY = [p * 0.8 for p in PATTERN_WEEKDAY]

# 2024年の祝日リスト (日本の祝日 + 振替休日)
HOLIDAYS_2024 = [
    "2024-01-01", "2024-01-08", "2024-02-11", "2024-02-12", "2024-02-23",
    "2024-03-20", "2024-04-29", "2024-05-03", "2024-05-04", "2024-05-05", "2024-05-06",
    "2024-07-15", "2024-08-11", "2024-08-12", "2024-09-16", "2024-09-22", "2024-09-23",
    "2024-10-14", "2024-11-03", "2024-11-04", "2024-11-23", 
    # 必要に応じて年末年始などを追加
    "2024-12-30", "2024-12-31", "2024-01-02", "2024-01-03" 
]

def is_holiday(date_obj):
    """日付が休日（土日または祝日）か判定する"""
    # 土曜日(5) または 日曜日(6)
    if date_obj.weekday() >= 5:
        return True
    # 祝日リストに含まれるか
    date_str = date_obj.strftime("%Y-%m-%d")
    if date_str in HOLIDAYS_2024:
        return True
    return False

def calculate_monthly_params(target_peak, target_total, patterns_in_month):
    """
    その月のPeakとTotalを満たす Base_Load(B) と Variable_Width(V) を計算する
    式: Demand(t) = B + V * Pattern(t)
    
    条件1: Max(Demand) = B + V * Max(Pattern) = Target_Peak
    条件2: Sum(Demand) = N * B + V * Sum(Pattern) = Target_Total
    
    (1)より B = Target_Peak - V * Max(Pattern)
    (2)に代入して V を解く
    """
    n_hours = len(patterns_in_month)
    sum_p = sum(patterns_in_month)
    max_p = max(patterns_in_month)
    
    # 分母: Sum(P) - N * Max(P)
    denominator = sum_p - (n_hours * max_p)
    
    if denominator == 0:
        # パターンがフラット(全て同じ値)の場合の例外処理
        # B + V * k = Peak => B = Peak - V*k
        # N(Peak - V*k) + V*N*k = Total => N*Peak = Total となりVが定まらない
        # ここでは単純にフラットな負荷として返す
        return target_total / n_hours, 0.0

    # 分子: Target_Total - N * Target_Peak
    numerator = target_total - (n_hours * target_peak)
    
    v = numerator / denominator
    b = target_peak - (v * max_p)
    
    return b, v

def main():
    year = 2024
    records = []
    
    # 1年間のループ
    start_date = datetime.datetime(year, 1, 1, 0, 0)
    end_date = datetime.datetime(year, 12, 31, 23, 0)
    
    # 月ごとの処理を行うため、まずは全時間のリストを作成し、月ごとに分割処理する
    all_hours = pd.date_range(start=start_date, end=end_date, freq='H')
    
    # 月ごとにグルーピング
    df_temp = pd.DataFrame({'timestamp': all_hours})
    df_temp['month'] = df_temp['timestamp'].dt.month
    
    print(f"{year}年のデマンドデータ生成を開始します...")
    
    final_data = []

    for month, group in df_temp.groupby('month'):
        target = MONTHLY_TARGETS.get(month)
        if not target:
            print(f"Warning: {month}月の設定が見つかりません。スキップします。")
            continue
            
        target_peak = target['peak_kw']
        target_total = target['total_kwh']
        
        # この月の時間ごとのパターン配列を作成
        monthly_patterns = []
        month_timestamps = group['timestamp'].tolist()
        
        for ts in month_timestamps:
            hour = ts.hour
            if is_holiday(ts):
                monthly_patterns.append(PATTERN_HOLIDAY[hour])
            else:
                monthly_patterns.append(PATTERN_WEEKDAY[hour])
        
        # パラメータ計算
        b, v = calculate_monthly_params(target_peak, target_total, monthly_patterns)
        
        # 調整ロジック
        # ケース1: 計算上の変動幅 V が負になる場合（Target_Totalが大きすぎて、Peak制約を守ると達成できない）
        # -> ベースを上げて対応（Peak超過を許容）
        if v < 0:
            print(f"[{month}月] 負荷率が高すぎます。ベース電力を上げて調整します。(契約電力超過)")
            v = 0 # パターン変動なし（フラット）にするのが最も効率が良い
            b = target_total / len(monthly_patterns)
        
        # ケース2: 計算上のベース B が負になる場合（Target_Totalが小さすぎる）
        # -> B=0 にして V を再計算（Target_Peakには届かない）
        elif b < 0:
            # print(f"[{month}月] 負荷率が低すぎます。ベース電力を0とし、ピークを下げて調整します。")
            b = 0
            # Sum(0 + V * P) = Total => V * Sum(P) = Total => V = Total / Sum(P)
            v = target_total / sum(monthly_patterns)
            
        # 確定した b, v でデマンド値を計算
        for i, ts in enumerate(month_timestamps):
            p = monthly_patterns[i]
            demand = b + (v * p)
            
            # 念のため負の値は0にする
            if demand < 0: demand = 0
            
            weekday_type = "休日" if is_holiday(ts) else "平日"
            
            final_data.append({
                'Date': ts.strftime('%Y-%m-%d'),
                'Time': ts.strftime('%H:00'),
                'Weekday_Type': weekday_type,
                'Demand_kW': round(demand, 2)
            })
            
        # 検証用ログ
        calc_total = sum([d['Demand_kW'] for d in final_data[-len(month_timestamps):]])
        calc_peak = max([d['Demand_kW'] for d in final_data[-len(month_timestamps):]])
        print(f"{month}月作成完了: Target(Peak={target_peak}, Total={target_total}) -> Result(Peak={calc_peak:.2f}, Total={calc_total:.0f})")

    # DataFrame作成と出力
    df_result = pd.DataFrame(final_data)
    output_file = f"demand_simulation_{year}.csv"
    df_result.to_csv(output_file, index=False, encoding='utf-8-sig')
    print(f"\n完了しました。ファイルを出力しました: {output_file}")

if __name__ == "__main__":
    main()










