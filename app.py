import streamlit as st
import pandas as pd
import numpy as np
import datetime
import io
import os
import altair as alt

# ==========================================
# 定数・初期設定
# ==========================================
HOLIDAYS_2024 = [
    "2024-01-01", "2024-01-08", "2024-02-11", "2024-02-12", "2024-02-23",
    "2024-03-20", "2024-04-29", "2024-05-03", "2024-05-04", "2024-05-05", "2024-05-06",
    "2024-07-15", "2024-08-11", "2024-08-12", "2024-09-16", "2024-09-22", "2024-09-23",
    "2024-10-14", "2024-11-03", "2024-11-04", "2024-11-23", 
    "2024-12-30", "2024-12-31", "2024-01-02", "2024-01-03" 
]

# プリセットパターンの定義
PRESET_PATTERNS = {
    "標準（オフィス/日中型）": {
        # 平日: 14時頃を最大ピーク（10）とし、前後をなだらかにする（ピークカットしやすく）
        "weekday": [2, 2, 2, 2, 2, 3, 5, 7, 8, 9, 9, 8, 7, 9, 10, 9, 8, 7, 6, 5, 4, 3, 2, 2],
        "holiday": [3]*24,
        "holiday_ratio": 30 # 休日は平日の30%程度
    },
    "工場（土日休み）": {
        # 平日: 午前(10時)と午後(14時)にピークを作り、平坦な時間を減らす
        "weekday": [2, 2, 2, 2, 2, 3, 5, 8, 9, 10, 9, 9, 5, 9, 10, 9, 8, 6, 3, 2, 2, 2, 2, 2],
        "holiday": [2]*24,
        "holiday_ratio": 15 # 待機電力のみ
    },
    "工場（土日稼働）": {
        # 平日・休日問わず、メリハリのある山を作る
        "weekday": [3, 3, 3, 3, 3, 4, 6, 8, 9, 10, 9, 9, 6, 9, 10, 9, 8, 7, 5, 4, 3, 3, 3, 3],
        "holiday": [3, 3, 3, 3, 3, 4, 6, 8, 9, 10, 9, 9, 6, 9, 10, 9, 8, 7, 5, 4, 3, 3, 3, 3],
        "holiday_ratio": 100 # 平日と同じ
    },
    "スーパーマーケット": {
        # 夕方17-18時頃に鋭いピークを作る（蓄電池効果が出やすい形状）
        "weekday": [4, 4, 4, 4, 4, 5, 6, 7, 8, 8, 9, 9, 9, 9, 9, 9.5, 10, 9.5, 8, 7, 6, 5, 4, 4],
        "holiday": [4, 4, 4, 4, 4, 5, 7, 8, 9, 9, 9.5, 10, 9.5, 9, 9, 9.5, 10, 9, 8, 7, 6, 5, 4, 4],
        "holiday_ratio": 100 # 休日もフル稼働
    },
    "倉庫（日中のみ）": {
        # 日中照明・空調のみ、メリハリは弱い
        "weekday": [1, 1, 1, 1, 1, 1, 2, 4, 8, 8, 8, 8, 6, 8, 8, 8, 8, 4, 2, 1, 1, 1, 1, 1],
        "holiday": [1]*24,
        "holiday_ratio": 20 # 休日はほぼ稼働なし
    },
    "コンビニ（24時間）": {
        # 昼ピーク、深夜も一定ある
        "weekday": [4, 4, 4, 4, 5, 6, 7, 8, 9, 9, 9, 10, 10, 9, 9, 8, 8, 7, 6, 5, 5, 5, 4, 4],
        "holiday": [4, 4, 4, 4, 5, 6, 7, 8, 9, 9, 9, 10, 10, 9, 9, 8, 8, 7, 6, 5, 5, 5, 4, 4],
        "holiday_ratio": 90 # 休日もほぼ同じ
    },
    "ほぼフラット（気温連動風）": {
        # ベースロードがメインで、日中わずかに山ができる（空調負荷など）。変動は緩やか。
        "weekday": [6, 6, 6, 6, 6, 6, 7, 8, 9, 10, 10, 10, 10, 10, 9, 8, 7, 6, 6, 6, 6, 6, 6, 6],
        "holiday": [6, 6, 6, 6, 6, 6, 7, 8, 9, 10, 10, 10, 10, 10, 9, 8, 7, 6, 6, 6, 6, 6, 6, 6],
        "holiday_ratio": 90 # 休日もほぼ変わらない
    }
}

def is_holiday(date_obj):
    """日付が休日（土日または祝日）か判定する"""
    if date_obj.weekday() >= 5:
        return True
    date_str = date_obj.strftime("%Y-%m-%d")
    if date_str in HOLIDAYS_2024:
        return True
    return False

def calculate_monthly_params(target_peak, target_total, patterns_in_month):
    """
    その月のPeakとTotalを満たす Base_Load(B) と Variable_Width(V) を計算する
    """
    n_hours = len(patterns_in_month)
    sum_p = sum(patterns_in_month)
    max_p = max(patterns_in_month)
    
    denominator = sum_p - (n_hours * max_p)
    
    if denominator == 0:
        return target_total / n_hours, 0.0

    numerator = target_total - (n_hours * target_peak)
    
    v = numerator / denominator
    b = target_peak - (v * max_p)
    
    return b, v

def normalize_to_percentage(raw_list):
    """リストの合計が100になるように正規化する"""
    total = sum(raw_list)
    if total == 0:
        return [0]*len(raw_list)
    return [x / total * 100 for x in raw_list]

def optimize_pattern_shape(target_peak, target_total, patterns_in_month, max_iter=20):
    """
    ターゲットのPeakとTotalを満たす解(B>=0, V>=0)が存在するように、
    パターンの「鋭さ（ガンマ値）」を自動調整する。
    B < 0 (Total不足) -> パターンを鋭くする (gamma > 1)
    V < 0 (Total過多) -> パターンを平坦にする (gamma < 1)
    """
    current_patterns = np.array(patterns_in_month)
    
    # 二分探索の範囲 (0.1 = 超平坦 〜 10.0 = 超鋭角)
    low = 0.1
    high = 10.0
    best_patterns = current_patterns
    best_b = 0
    best_v = 0
    min_error = float('inf')

    # まず初期状態で計算
    b, v = calculate_monthly_params(target_peak, target_total, current_patterns)
    
    # 既にOKならそのまま返す
    if b >= -0.001 and v >= -0.001:
        return current_patterns, b, v

    # 探索ループ
    for _ in range(max_iter):
        mid = (low + high) / 2
        
        # ガンマ補正 (x^gamma)
        # 元の値が小さいと消えてしまうので、最大値で正規化してからべき乗し、戻す
        p_max = current_patterns.max()
        if p_max == 0: break
        
        temp_patterns = np.power(current_patterns / p_max, mid) * p_max
        
        b, v = calculate_monthly_params(target_peak, target_total, temp_patterns)
        
        # 評価
        # 我々が目指すのは B>=0 かつ V>=0
        if b < 0:
            # Baseが負 = Totalが少なすぎる = パターンが平坦すぎる
            # -> もっと鋭くする必要がある -> gammaを大きく
            low = mid
        elif v < 0:
            # Variableが負 = Totalが多すぎる = パターンが鋭すぎる
            # -> もっと平坦にする必要がある -> gammaを小さく
            high = mid
        else:
            # 解が見つかった！
            return temp_patterns, b, v
            
    # ループを抜けた場合（収束しなかった場合）、最もマシな（境界に近い）値を返す
    # 最後にもう一度計算
    p_max = current_patterns.max()
    if p_max > 0:
        final_patterns = np.power(current_patterns / p_max, mid) * p_max
        b, v = calculate_monthly_params(target_peak, target_total, final_patterns)
        return final_patterns, b, v
    
    return current_patterns, b, v

# ==========================================
# Streamlit UI構築
# ==========================================
st.set_page_config(page_title="電力デマンド生成シミュレーター", layout="wide")
st.title("⚡ 電力デマンド生成シミュレーター")

# セッションステートの初期化
if 'calculated_data' not in st.session_state:
    st.session_state.calculated_data = None

# パターンデータの初期化関数
def set_pattern_data(preset_name="標準（オフィス/日中型）"):
    data = PRESET_PATTERNS.get(preset_name, PRESET_PATTERNS["標準（オフィス/日中型）"])
    
    hours = list(range(24))
    weekday_vals = normalize_to_percentage(data["weekday"])
    holiday_vals = normalize_to_percentage(data["holiday"])
    
    st.session_state.pattern_df = pd.DataFrame({
        'Hour': hours,
        'Weekday': weekday_vals,
        'Holiday': holiday_vals
    })
    
    # 休日の稼働率も更新
    st.session_state.holiday_ratio = data.get("holiday_ratio", 100)

# 初回起動時の初期化
if 'pattern_df' not in st.session_state:
    if 'holiday_ratio' not in st.session_state:
        st.session_state.holiday_ratio = 30 # 初期値
    set_pattern_data()

# --- サイドバー: パターン設定 (視覚的操作) ---
st.sidebar.header("1. 負荷パターン設定")

# プリセット選択
preset_options = list(PRESET_PATTERNS.keys())
selected_preset = st.sidebar.selectbox(
    "業態プリセットを選択してください",
    options=preset_options,
    index=0,
    key="preset_selector",
    on_change=lambda: set_pattern_data(st.session_state.preset_selector)
)

st.sidebar.markdown("---")

# 休日の稼働率スライダー
st.sidebar.subheader("休日の電力レベル調整")
holiday_ratio = st.sidebar.slider(
    "平日ピークに対する休日の割合 (%)",
    min_value=0,
    max_value=120,
    value=st.session_state.holiday_ratio,
    step=5,
    key="holiday_ratio_slider",
    help="平日の一番高い電力を100としたとき、休日の電力レベルをどの程度にするか設定します。0にすると待機電力なしになります。"
)
# session_stateと同期（スライダー操作時）
st.session_state.holiday_ratio = holiday_ratio


st.sidebar.markdown("---")
st.sidebar.markdown("##### 時間ごとの配分形状(%)")
st.sidebar.caption("※ここでは「形状」を編集します。休日の高さ（絶対量）は上のスライダーで調整されます。")

# 編集可能なデータフレーム
edited_pattern_df = st.sidebar.data_editor(
    st.session_state.pattern_df,
    column_config={
        "Hour": st.column_config.NumberColumn("時", min_value=0, max_value=23, disabled=True, format="%d時"),
        "Weekday": st.column_config.NumberColumn("平日形状(%)", min_value=0.0, max_value=100.0, step=0.1, format="%.1f%%"),
        "Holiday": st.column_config.NumberColumn("休日形状(%)", min_value=0.0, max_value=100.0, step=0.1, format="%.1f%%")
    },
    hide_index=True,
    num_rows="fixed",
    height=300
)

# 合計値の確認
sum_weekday = edited_pattern_df['Weekday'].sum()
sum_holiday = edited_pattern_df['Holiday'].sum()

if abs(sum_weekday - 100.0) > 0.1:
    st.sidebar.warning("平日の合計が100%になっていません（計算時に自動補正されます）")

# グラフで可視化 (Altair)
# ここでは視覚的に分かりやすくするため、休日の値にスライダーの係数を掛けて表示する
df_preview = edited_pattern_df.copy()
ratio_val = st.session_state.holiday_ratio / 100.0

# 表示用にスケーリング（平日の最大値を基準に、休日の高さを調整）
# 注: データフレームの値は「合計100%」なので、ピークの値は時間数による。
# ここでは簡易的に、「入力された値」に対して係数をかけるだけでイメージを表示する。
df_preview['Holiday'] = df_preview['Holiday'] * ratio_val

pattern_long = df_preview.melt('Hour', var_name='Type', value_name='Value')

# グラフタイトル
chart = alt.Chart(pattern_long).mark_bar().encode(
    x=alt.X('Hour:O', title='時間'),
    y=alt.Y('Value', title='相対強度 (イメージ)'),
    color=alt.Color('Type', title='区分', scale=alt.Scale(domain=['Weekday', 'Holiday'], range=['#1f77b4', '#ff7f0e'])),
    xOffset=alt.XOffset('Type', sort=['Weekday', 'Holiday']),
    tooltip=['Hour', 'Type', alt.Tooltip('Value', format='.1f')]
).properties(height=220, title="時間別パターンプレビュー (高さ調整済)")

st.sidebar.altair_chart(chart, use_container_width=True)

# パターン配列の更新
pattern_weekday_ratio = edited_pattern_df['Weekday'].tolist()
pattern_holiday_ratio = edited_pattern_df['Holiday'].tolist()


# --- メイン画面: データ入力 ---
st.header("2. 月別ターゲット入力")
st.markdown("各月の「契約電力(Peak)」と「使用電力量(Total)」を入力してください。")

default_data = {
    "月": list(range(1, 13)),
    "契約電力(kW)": [50, 50, 45, 45, 50, 55, 60, 60, 55, 45, 45, 50],
    "使用電力量(kWh)": [22000, 20000, 19000, 18000, 20000, 24000, 28000, 30000, 26000, 20000, 19000, 23000]
}
df_input = pd.DataFrame(default_data)

edited_df = st.data_editor(
    df_input,
    column_config={
        "月": st.column_config.NumberColumn("月", format="%d月", min_value=1, max_value=12, disabled=True),
        "契約電力(kW)": st.column_config.NumberColumn("契約電力 (kW)", min_value=0, format="%.1f"),
        "使用電力量(kWh)": st.column_config.NumberColumn("使用電力量 (kWh)", min_value=0, format="%d"),
    },
    hide_index=True,
    num_rows="fixed"
)


# --- 計算実行 ---
st.header("3. シミュレーション実行")
st.caption("※目標のPeak/Totalに合わせるため、波形の鋭さを自動調整します（1点だけ突出するのを防ぎます）")

if st.button("計算実行", type="primary"):
    year = 2024
    start_date = datetime.datetime(year, 1, 1, 0, 0)
    end_date = datetime.datetime(year, 12, 31, 23, 0)
    
    # 1. 全期間の生成
    all_hours = pd.date_range(start=start_date, end=end_date, freq='h')
    
    # 2. うるう日(2/29)を除外する
    is_leap_day = (all_hours.month == 2) & (all_hours.day == 29)
    all_hours = all_hours[~is_leap_day]
    
    df_temp = pd.DataFrame({'timestamp': all_hours})
    df_temp['month'] = df_temp['timestamp'].dt.month
    
    final_data = []
    
    targets = {}
    for index, row in edited_df.iterrows():
        targets[row['月']] = {
            'peak_kw': row['契約電力(kW)'], 
            'total_kwh': row['使用電力量(kWh)']
        }

    progress_bar = st.progress(0)
    
    # パターンの正規化 (最大値を1.0にする)
    def normalize_pattern_to_coefficient(ratio_list):
        max_val = max(ratio_list)
        if max_val == 0: return [0.0] * len(ratio_list)
        return [r / max_val for r in ratio_list]

    p_weekday_coef = normalize_pattern_to_coefficient(pattern_weekday_ratio)
    p_holiday_coef = normalize_pattern_to_coefficient(pattern_holiday_ratio)
    
    # 休日のパターン係数全体を下げる (スライダーの値を使用)
    h_ratio = st.session_state.holiday_ratio / 100.0
    p_holiday_coef = [x * h_ratio for x in p_holiday_coef]

    for month, group in df_temp.groupby('month'):
        progress_bar.progress(month / 12)
        
        target = targets.get(month)
        target_peak = target['peak_kw']
        target_total = target['total_kwh']
        
        monthly_patterns = []
        month_timestamps = group['timestamp'].tolist()
        
        for ts in month_timestamps:
            hour = ts.hour
            if is_holiday(ts):
                monthly_patterns.append(p_holiday_coef[hour])
            else:
                monthly_patterns.append(p_weekday_coef[hour])
        
        # --- ここで自動形状補正を行う ---
        # 単純に計算してB, Vが負になる場合、パターンを変形させて解を見つける
        optimized_patterns, b, v = optimize_pattern_shape(target_peak, target_total, monthly_patterns)
        
        # 強制補正フラグ（最適化してもダメだった場合の安全策）
        force_adjust = False
        if v < 0:
            v = 0
            b = target_total / len(optimized_patterns)
            force_adjust = True
        elif b < 0:
            b = 0
            v = target_total / sum(optimized_patterns)
            force_adjust = True
        
        month_data = []
        max_val = -1.0
        max_idx = -1
        
        for i, ts in enumerate(month_timestamps):
            p = optimized_patterns[i]
            demand = b + (v * p)
            if demand < 0: demand = 0
            
            month_data.append({
                'Date_obj': ts.date(), 
                'Time': ts.strftime('%H:00'),
                'Weekday_Type': "休日" if is_holiday(ts) else "平日",
                'Demand_kW': demand,
                'datetime': ts 
            })
            
            if demand > max_val:
                max_val = demand
                max_idx = i

        # --- ピーク強制一致ロジック（最終微調整） ---
        diff = target_peak - max_val
        
        if abs(diff) > 0.000001:
            current_val = month_data[max_idx]['Demand_kW']
            month_data[max_idx]['Demand_kW'] = target_peak
            
            # 差分を1点ではなく、月全体にうっすら分散させる（トータルを変えないため、ここでは微修正のみ）
            # だが、ピークを合わせるとトータルがズレる...
            # 形状最適化がうまくいっていればdiffはほぼゼロのはず。
            # 念の為、他の点には触らずピークだけ合わせるとトータルが微小にズレるが、
            # 1点スパイクよりはマシなので、ピーク点のみ修正する（ただし最適化後なので差は小さいはず）
            pass 
            # ↑最適化を入れたので、無理やりな1点修正は一旦OFFにして様子を見る。
            # もしどうしてもピークぴったりにしたいなら、最後にスケーリングする手もあるが...
            # ここでは「ピーク値」を優先して書き換える
            month_data[max_idx]['Demand_kW'] = target_peak

        final_data.extend(month_data)

    df_result = pd.DataFrame(final_data)
    df_result['Demand_kW'] = df_result['Demand_kW'].round(2)

    st.session_state.calculated_data = df_result
    st.success("計算が完了しました！")


# --- 結果表示 (セッションステートから読み出し) ---
if st.session_state.calculated_data is not None:
    df_result = st.session_state.calculated_data
    year = 2024 # 固定

    # 年間デマンド推移 (幅いっぱいに表示)
    st.subheader("年間デマンド推移")
    
    # Altairで折れ線グラフを作成 (Streamlit標準のline_chartより高機能)
    # データ点数が多すぎると重いので、描画用にダウンサンプリングするか、そのまま描画するか検討
    # ここでは8760点ならギリギリいけるのでそのまま描画
    chart_year = alt.Chart(df_result).mark_line(strokeWidth=1).encode(
        x=alt.X('datetime:T', title='日時'),
        y=alt.Y('Demand_kW:Q', title='デマンド値 (kW)'),
        tooltip=['datetime', 'Demand_kW']
    ).properties(
        height=400
    ).interactive() # ズーム・パン可能に
    
    st.altair_chart(chart_year, use_container_width=True)
    
    # 検証用
    st.subheader("計算結果の検証 (月別)")
    df_result['month'] = df_result['datetime'].dt.month
    monthly_stats = df_result.groupby('month')['Demand_kW'].agg(['max', 'sum']).reset_index()
    monthly_stats.columns = ['月', '計算ピーク(kW)', '計算合計(kWh)']
    
    validation_df = pd.merge(edited_df, monthly_stats, left_on='月', right_on='月')
    validation_df['ピーク差分'] = validation_df['計算ピーク(kW)'] - validation_df['契約電力(kW)']
    validation_df['合計差分'] = validation_df['計算合計(kWh)'] - validation_df['使用電力量(kWh)']
    
    st.dataframe(validation_df.style.format({
        '計算ピーク(kW)': '{:.2f}', 
        '計算合計(kWh)': '{:.0f}',
        'ピーク差分': '{:.2f}',
        '合計差分': '{:.0f}'
    }))

    # --- ダウンロード ---
    st.header("4. データダウンロード")
    
    df_pivot = df_result.pivot(index='Date_obj', columns='Time', values='Demand_kW')
    df_pivot.index = df_pivot.index.map(lambda d: f"{d.month}/{d.day}")
    df_pivot.index.name = "Date"

    time_columns = [f"{h:02d}:00" for h in range(24)]
    existing_cols = [c for c in time_columns if c in df_pivot.columns]
    df_pivot = df_pivot[existing_cols]
    
    csv = df_pivot.to_csv(encoding='utf-8-sig')
    
    st.subheader("生成データのプレビュー (横持ち形式)")
    st.dataframe(df_pivot.head())
    
    st.download_button(
        label="CSVファイルをダウンロード (横持ち形式)",
        data=csv,
        file_name=f"demand_simulation_{year}_pivot.csv",
        mime="text/csv"
    )
    
    if st.button("プロジェクトフォルダに保存する"):
        file_path = os.path.join(os.getcwd(), f"demand_simulation_{year}_pivot.csv")
        try:
            df_pivot.to_csv(file_path, encoding='utf-8-sig')
            st.success(f"保存しました: {file_path}")
        except PermissionError:
            st.error(f"エラー: ファイル '{file_path}' は現在開かれているため保存できません。Excelなどを閉じてから再試行してください。")
