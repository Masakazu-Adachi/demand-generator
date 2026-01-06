import streamlit as st
import pandas as pd
import numpy as np
import datetime
import io
import os
import altair as alt

# ==========================================
# ページ設定（最初に呼ぶ必要あり）
# ==========================================
st.set_page_config(
    page_title="⚡ デマンド生成",
    page_icon="⚡",
    layout="centered",  # 1列レイアウト
    initial_sidebar_state="collapsed"  # サイドバーを非表示
)

# ==========================================
# カスタムCSS
# ==========================================
st.markdown("""
<style>
    /* 全体の背景 */
    .stApp {
        background: #ffffff;
    }
    
    /* メインコンテンツエリア */
    .main .block-container {
        background: #ffffff;
        border-radius: 20px;
        padding: 2rem 3rem;
        margin-top: 1rem;
    }
    
    /* セクションカード */
    .section-card {
        background: linear-gradient(135deg, #f5f7fa 0%, #e4e8ec 100%);
        border-radius: 15px;
        padding: 1.5rem;
        margin: 1rem 0;
        border-left: 5px solid #4CAF50;
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.05);
    }
    
    /* セクションタイトル */
    .section-title {
        font-size: 1.3rem;
        font-weight: bold;
        color: #4a5568;
        margin-bottom: 1rem;
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }
    
    /* ボタンのスタイル */
    .stButton > button {
        background: linear-gradient(135deg, #00c853 0%, #64dd17 100%);
        color: white;
        border: none;
        border-radius: 25px;
        padding: 0.75rem 2rem;
        font-size: 1.1rem;
        font-weight: bold;
        transition: all 0.3s ease;
        box-shadow: 0 4px 15px rgba(0, 200, 83, 0.4);
    }
    
    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 20px rgba(0, 200, 83, 0.6);
        background: linear-gradient(135deg, #00e676 0%, #76ff03 100%);
    }
    
    /* データエディタのスタイル */
    .stDataFrame {
        border-radius: 10px;
        overflow: hidden;
    }
    
    /* スライダーのスタイル */
    .stSlider > div > div > div {
        background: #4CAF50 !important;
    }
    
    /* 成功メッセージ */
    .stSuccess {
        background: linear-gradient(135deg, #c8e6c9 0%, #a5d6a7 100%);
        border-radius: 10px;
    }
    
    /* ヘッダー */
    h1 {
        text-align: center;
        color: #2d3748;
        font-size: 1.8rem !important;
    }
    
    /* サブヘッダー */
    h2 {
        color: #4a5568;
        font-size: 1.3rem !important;
    }
    
    h3 {
        color: #4a5568;
        font-size: 1.1rem !important;
    }
    
    /* 全体の文字サイズ調整 */
    .stMarkdown p, .stMarkdown li {
        font-size: 0.95rem;
    }
    
    /* 説明テキスト */
    .description {
        color: #718096;
        font-size: 0.95rem;
        line-height: 1.6;
    }
    
    /* プログレスバー */
    .stProgress > div > div > div {
        background: linear-gradient(135deg, #4CAF50 0%, #8BC34A 100%);
    }
</style>
""", unsafe_allow_html=True)

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
    "🏢 標準（オフィス/日中型）": {
        "weekday": [2, 2, 2, 2, 2, 3, 5, 7, 8, 9, 9, 8, 7, 9, 10, 9, 8, 7, 6, 5, 4, 3, 2, 2],
        "holiday": [3]*24,
        "holiday_ratio": 30
    },
    "🏭 工場（土日休み）": {
        "weekday": [2, 2, 2, 2, 2, 3, 5, 8, 9, 10, 9, 9, 5, 9, 10, 9, 8, 6, 3, 2, 2, 2, 2, 2],
        "holiday": [2]*24,
        "holiday_ratio": 15
    },
    "🏭 工場（土日稼働）": {
        "weekday": [3, 3, 3, 3, 3, 4, 6, 8, 9, 10, 9, 9, 6, 9, 10, 9, 8, 7, 5, 4, 3, 3, 3, 3],
        "holiday": [3, 3, 3, 3, 3, 4, 6, 8, 9, 10, 9, 9, 6, 9, 10, 9, 8, 7, 5, 4, 3, 3, 3, 3],
        "holiday_ratio": 100
    },
    "🛒 スーパーマーケット": {
        "weekday": [4, 4, 4, 4, 4, 5, 6, 7, 8, 8, 9, 9, 9, 9, 9, 9.5, 10, 9.5, 8, 7, 6, 5, 4, 4],
        "holiday": [4, 4, 4, 4, 4, 5, 7, 8, 9, 9, 9.5, 10, 9.5, 9, 9, 9.5, 10, 9, 8, 7, 6, 5, 4, 4],
        "holiday_ratio": 100
    },
    "📦 倉庫（日中のみ）": {
        "weekday": [1, 1, 1, 1, 1, 1, 2, 4, 8, 8, 8, 8, 6, 8, 8, 8, 8, 4, 2, 1, 1, 1, 1, 1],
        "holiday": [1]*24,
        "holiday_ratio": 20
    },
    "🏪 コンビニ（24時間）": {
        "weekday": [4, 4, 4, 4, 5, 6, 7, 8, 9, 9, 9, 10, 10, 9, 9, 8, 8, 7, 6, 5, 5, 5, 4, 4],
        "holiday": [4, 4, 4, 4, 5, 6, 7, 8, 9, 9, 9, 10, 10, 9, 9, 8, 8, 7, 6, 5, 5, 5, 4, 4],
        "holiday_ratio": 90
    },
    "🌡️ ほぼフラット（気温連動風）": {
        "weekday": [6, 6, 6, 6, 6, 6, 7, 8, 9, 10, 10, 10, 10, 10, 9, 8, 7, 6, 6, 6, 6, 6, 6, 6],
        "holiday": [6, 6, 6, 6, 6, 6, 7, 8, 9, 10, 10, 10, 10, 10, 9, 8, 7, 6, 6, 6, 6, 6, 6, 6],
        "holiday_ratio": 100
    }
}

# ==========================================
# ユーティリティ関数
# ==========================================
def is_holiday(date_obj):
    """日付が休日（土日または祝日）か判定する"""
    if date_obj.weekday() >= 5:
        return True
    date_str = date_obj.strftime("%Y-%m-%d")
    if date_str in HOLIDAYS_2024:
        return True
    return False

def calculate_monthly_params(target_peak, target_total, patterns_in_month):
    """その月のPeakとTotalを満たす Base_Load(B) と Variable_Width(V) を計算する"""
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
    """パターンの「鋭さ（ガンマ値）」を自動調整する"""
    current_patterns = np.array(patterns_in_month)
    
    low = 0.1
    high = 10.0
    best_patterns = current_patterns
    best_b = 0
    best_v = 0
    min_error = float('inf')

    b, v = calculate_monthly_params(target_peak, target_total, current_patterns)
    
    if b >= -0.001 and v >= -0.001:
        return current_patterns, b, v

    for _ in range(max_iter):
        mid = (low + high) / 2
        
        p_max = current_patterns.max()
        if p_max == 0: break
        
        temp_patterns = np.power(current_patterns / p_max, mid) * p_max
        
        b, v = calculate_monthly_params(target_peak, target_total, temp_patterns)
        
        if b < 0:
            low = mid
        elif v < 0:
            high = mid
        else:
            return temp_patterns, b, v
            
    p_max = current_patterns.max()
    if p_max > 0:
        final_patterns = np.power(current_patterns / p_max, mid) * p_max
        b, v = calculate_monthly_params(target_peak, target_total, final_patterns)
        return final_patterns, b, v
    
    return current_patterns, b, v

# ==========================================
# セッションステートの初期化
# ==========================================
if 'calculated_data' not in st.session_state:
    st.session_state.calculated_data = None

def set_pattern_data(preset_name):
    key_name = preset_name
    data = PRESET_PATTERNS.get(key_name, list(PRESET_PATTERNS.values())[0])
    
    hours = list(range(24))
    weekday_vals = normalize_to_percentage(data["weekday"])
    holiday_vals = normalize_to_percentage(data["holiday"])
    
    st.session_state.pattern_df = pd.DataFrame({
        'Hour': hours,
        'Weekday': weekday_vals,
        'Holiday': holiday_vals
    })
    
    st.session_state.holiday_ratio = data.get("holiday_ratio", 100)

if 'pattern_df' not in st.session_state:
    if 'holiday_ratio' not in st.session_state:
        st.session_state.holiday_ratio = 30
    set_pattern_data(list(PRESET_PATTERNS.keys())[0])

# ==========================================
# メインUI
# ==========================================

# ヘッダー
st.markdown("# ⚡ デマンド生成")
st.markdown("""
<p style="text-align: center; color: #718096; font-size: 0.95rem;">
    月別の契約電力と使用電力量から、時間ごとのデマンドデータを生成します
</p>
""", unsafe_allow_html=True)

st.markdown("---")

# ==========================================
# STEP 1: 負荷パターン設定
# ==========================================
st.markdown("## STEP 1: 負荷パターン設定")

st.markdown("""
<div class="description">
    業態を選択すると、対応する電力パターンが自動設定されます。
</div>
""", unsafe_allow_html=True)

# プリセット選択
col1, col2 = st.columns([2, 1])

with col1:
    preset_options = list(PRESET_PATTERNS.keys())
    selected_preset = st.selectbox(
        "業態プリセット",
        options=preset_options,
        index=0,
        key="preset_selector",
        on_change=lambda: set_pattern_data(st.session_state.preset_selector),
        label_visibility="collapsed"
    )

with col2:
    holiday_ratio = st.slider(
        "休日の電力レベル (%)",
        min_value=0,
        max_value=120,
        value=st.session_state.holiday_ratio,
        step=5,
        help="平日の一番高い電力を100としたとき、休日の電力レベルをどの程度にするか"
    )
    st.session_state.holiday_ratio = holiday_ratio

# パターンのプレビューグラフ
st.markdown("### パターンプレビュー")

df_preview = st.session_state.pattern_df.copy()
ratio_val = st.session_state.holiday_ratio / 100.0
df_preview['Holiday'] = df_preview['Holiday'] * ratio_val

pattern_long = df_preview.melt('Hour', var_name='Type', value_name='Value')
pattern_long['Type'] = pattern_long['Type'].replace({'Weekday': '平日', 'Holiday': '休日'})

chart = alt.Chart(pattern_long).mark_bar(
    cornerRadiusTopLeft=3,
    cornerRadiusTopRight=3
).encode(
    x=alt.X('Hour:O', title='時間', axis=alt.Axis(labelAngle=0)),
    y=alt.Y('Value:Q', title='比率 (%)'),
    color=alt.Color('Type:N', 
                    title='区分',
                    scale=alt.Scale(
                        domain=['平日', '休日'],
                        range=['#4CAF50', '#FF9800']
                    )),
    xOffset=alt.XOffset('Type:N', sort=['平日', '休日']),
    tooltip=[
        alt.Tooltip('Hour:O', title='時間'),
        alt.Tooltip('Type:N', title='区分'),
        alt.Tooltip('Value:Q', title='比率 (%)', format='.1f')
    ]
).properties(
    height=250
).configure_axis(
    grid=True,
    gridOpacity=0.3
).configure_view(
    strokeWidth=0
)

st.altair_chart(chart, use_container_width=True)

# 詳細設定（折りたたみ）
with st.expander("詳細設定：時間別パターンの調整"):
    st.markdown("各時間帯の配分を直接編集できます。合計は自動で100%に調整されます。")
    
    edited_pattern_df = st.data_editor(
        st.session_state.pattern_df,
        column_config={
            "Hour": st.column_config.NumberColumn("時", min_value=0, max_value=23, disabled=True, format="%d時"),
            "Weekday": st.column_config.NumberColumn("平日 (%)", min_value=0.0, max_value=100.0, step=0.1, format="%.1f"),
            "Holiday": st.column_config.NumberColumn("休日 (%)", min_value=0.0, max_value=100.0, step=0.1, format="%.1f")
        },
        hide_index=True,
        num_rows="fixed",
        height=400,
        use_container_width=True
    )
    st.session_state.pattern_df = edited_pattern_df

pattern_weekday_ratio = st.session_state.pattern_df['Weekday'].tolist()
pattern_holiday_ratio = st.session_state.pattern_df['Holiday'].tolist()

st.markdown("---")

# ==========================================
# STEP 2: ターゲット入力
# ==========================================
st.markdown("## STEP 2: 月別電力データ入力")

st.markdown("""
<div class="description">
    各月の契約電力（ピーク値）と使用電力量（月間合計）を入力してください。
</div>
""", unsafe_allow_html=True)

default_data = {
    "月": list(range(1, 13)),
    "契約電力(kW)": [50, 50, 45, 45, 50, 55, 60, 60, 55, 45, 45, 50],
    "使用電力量(kWh)": [22000, 20000, 19000, 18000, 20000, 24000, 28000, 30000, 26000, 20000, 19000, 23000]
}
df_input = pd.DataFrame(default_data)

edited_df = st.data_editor(
    df_input,
    column_config={
        "月": st.column_config.NumberColumn("📅 月", format="%d月", min_value=1, max_value=12, disabled=True),
        "契約電力(kW)": st.column_config.NumberColumn("⚡ 契約電力 (kW)", min_value=0.1, max_value=10000, format="%.1f", required=True, default=50.0),
        "使用電力量(kWh)": st.column_config.NumberColumn("🔋 使用電力量 (kWh)", min_value=1, max_value=10000000, format="%d", required=True, default=20000),
    },
    hide_index=True,
    num_rows="fixed",
    use_container_width=True
)

st.markdown("---")

# ==========================================
# STEP 3: シミュレーション実行
# ==========================================
st.markdown("## STEP 3: シミュレーション実行")

st.markdown("""
<div class="description">
    設定が完了したら、計算実行ボタンをクリックしてください。
</div>
""", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    run_button = st.button("計算実行", use_container_width=True)

if run_button:
    year = 2024
    start_date = datetime.datetime(year, 1, 1, 0, 0)
    end_date = datetime.datetime(year, 12, 31, 23, 0)
    
    all_hours = pd.date_range(start=start_date, end=end_date, freq='h')
    
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
    status_text = st.empty()
    
    def normalize_pattern_to_coefficient(ratio_list):
        max_val = max(ratio_list)
        if max_val == 0: return [0.0] * len(ratio_list)
        return [r / max_val for r in ratio_list]

    p_weekday_coef = normalize_pattern_to_coefficient(pattern_weekday_ratio)
    p_holiday_coef = normalize_pattern_to_coefficient(pattern_holiday_ratio)
    
    h_ratio = st.session_state.holiday_ratio / 100.0
    p_holiday_coef = [x * h_ratio for x in p_holiday_coef]

    for month, group in df_temp.groupby('month'):
        progress_bar.progress(month / 12)
        status_text.text(f"🔄 {month}月を計算中...")
        
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
        
        optimized_patterns, b, v = optimize_pattern_shape(target_peak, target_total, monthly_patterns)
        
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

        # ピーク値を目標に合わせる
        diff = target_peak - max_val
        if abs(diff) > 0.000001:
            month_data[max_idx]['Demand_kW'] = target_peak
        
        # 合計値を目標に合わせる（ピーク以外の1時間だけ調整）
        current_total = sum([d['Demand_kW'] for d in month_data])
        total_diff = target_total - current_total
        
        if abs(total_diff) > 0.001:
            # ピーク以外で、調整しても問題ない時間を1つ選ぶ
            # （2番目に大きい値の時間を選ぶと目立ちにくい）
            sorted_indices = sorted(
                range(len(month_data)), 
                key=lambda i: month_data[i]['Demand_kW'], 
                reverse=True
            )
            
            # ピーク以外の時間を探す
            adjust_idx = None
            for idx in sorted_indices:
                if idx != max_idx:
                    # この時間に差分を足しても、ピークを超えないか確認
                    new_val = month_data[idx]['Demand_kW'] + total_diff
                    if new_val >= 0 and new_val <= target_peak:
                        adjust_idx = idx
                        break
            
            # 見つからなければ、最も小さい値の時間を使う
            if adjust_idx is None:
                for idx in reversed(sorted_indices):
                    if idx != max_idx:
                        adjust_idx = idx
                        break
            
            if adjust_idx is not None:
                month_data[adjust_idx]['Demand_kW'] += total_diff

        final_data.extend(month_data)

    progress_bar.progress(1.0)
    status_text.empty()
    
    df_result = pd.DataFrame(final_data)
    df_result['Demand_kW'] = df_result['Demand_kW'].round(2)
    
    # 丸め後の合計差分を月ごとに再調整
    df_result['month'] = df_result['datetime'].dt.month
    
    for month in range(1, 13):
        target_total = targets[month]['total_kwh']
        target_peak = targets[month]['peak_kw']
        
        month_mask = df_result['month'] == month
        current_total = df_result.loc[month_mask, 'Demand_kW'].sum()
        total_diff = target_total - current_total
        
        if abs(total_diff) >= 0.01:
            # ピーク以外の時間を1つ選んで調整
            month_data = df_result.loc[month_mask].copy()
            max_idx = month_data['Demand_kW'].idxmax()
            
            # ピーク以外で調整可能な時間を探す
            for idx in month_data.index:
                if idx != max_idx:
                    current_val = df_result.loc[idx, 'Demand_kW']
                    new_val = round(current_val + total_diff, 2)
                    # ピークを超えず、0以上なら調整
                    if 0 <= new_val <= target_peak:
                        df_result.loc[idx, 'Demand_kW'] = new_val
                        break

    st.session_state.calculated_data = df_result
    st.success("計算が完了しました。")

# ==========================================
# 結果表示
# ==========================================
if st.session_state.calculated_data is not None:
    df_result = st.session_state.calculated_data
    year = 2024

    st.markdown("---")
    st.markdown("## 計算結果")
    
    # 月別デマンド推移グラフ
    st.markdown("### 月別ピーク値")
    
    # 月ごとの集計データを作成
    df_monthly = df_result.groupby('month').agg({
        'Demand_kW': ['max', 'mean', 'sum']
    }).reset_index()
    df_monthly.columns = ['月', 'ピーク (kW)', '平均 (kW)', '合計 (kWh)']
    df_monthly['月表示'] = df_monthly['月'].astype(str) + '月'
    
    chart_monthly = alt.Chart(df_monthly).mark_bar(
        cornerRadiusTopLeft=5,
        cornerRadiusTopRight=5,
        color='#4CAF50'
    ).encode(
        x=alt.X('月表示:N', title='月', sort=list(df_monthly['月表示'])),
        y=alt.Y('ピーク (kW):Q', title='ピーク (kW)'),
        tooltip=[
            alt.Tooltip('月表示:N', title='月'),
            alt.Tooltip('ピーク (kW):Q', title='ピーク', format='.1f'),
            alt.Tooltip('平均 (kW):Q', title='平均', format='.1f'),
            alt.Tooltip('合計 (kWh):Q', title='合計', format=',.0f')
        ]
    ).properties(
        height=300
    )
    
    st.altair_chart(chart_monthly, use_container_width=True)
    
    # 検証テーブル
    st.markdown("### 検証テーブル")
    
    monthly_stats = df_result.groupby('month')['Demand_kW'].agg(['max', 'sum']).reset_index()
    monthly_stats.columns = ['月', '計算ピーク(kW)', '計算合計(kWh)']
    
    validation_df = pd.merge(edited_df, monthly_stats, left_on='月', right_on='月')
    
    # 月を日本語表記に
    validation_df['月'] = validation_df['月'].astype(str) + '月'
    
    st.dataframe(
        validation_df.style.format({
            '計算ピーク(kW)': '{:.2f}', 
            '計算合計(kWh)': '{:.0f}'
        }),
        use_container_width=True,
        hide_index=True
    )

    st.markdown("---")
    
    # ダウンロード
    st.markdown("## データダウンロード")
    
    df_pivot = df_result.pivot(index='Date_obj', columns='Time', values='Demand_kW')
    df_pivot.index = df_pivot.index.map(lambda d: f"{d.month}/{d.day}")
    df_pivot.index.name = "Date"

    time_columns = [f"{h:02d}:00" for h in range(24)]
    existing_cols = [c for c in time_columns if c in df_pivot.columns]
    df_pivot = df_pivot[existing_cols]
    
    csv = df_pivot.to_csv(encoding='utf-8-sig')
    
    with st.expander("データプレビュー"):
        st.dataframe(df_pivot.head(10), use_container_width=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.download_button(
            label="CSVダウンロード",
            data=csv,
            file_name=f"demand_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            use_container_width=True
        )

# フッター
st.markdown("---")
st.markdown("""
<p style="text-align: center; color: #a0aec0; font-size: 0.9rem;">
    © 2026 ONE'S ENERGY. All rights reserved.
</p>
""", unsafe_allow_html=True)
