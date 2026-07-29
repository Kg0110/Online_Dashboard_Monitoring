import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import time
from io import StringIO

st.set_page_config(
    page_title="Industrial Tool Monitoring",
    layout="wide"
)

# =====================================================
# THEME
# =====================================================

st.markdown("""
<style>

.stApp {
    background-color:#0E1117;
    color:white;
}

.kpi-card{
    background:#161B22;
    padding:20px;
    border-radius:12px;
    border:1px solid #30363D;
    text-align:center;
}

.metric-value{
    font-size:32px;
    font-weight:bold;
}

.green{color:#00FF88;}
.yellow{color:#F7E733;}
.orange{color:#FF9900;}
.red{color:#FF4444;}

hr{
    border:1px solid #222;
}

</style>
""", unsafe_allow_html=True)

# =====================================================
# SIDEBAR
# =====================================================

st.sidebar.title("⚙ Tool Configuration")

uploaded_file = st.sidebar.file_uploader(
    "Upload Current Log CSV",
    type=["csv"]
)

simulate = st.sidebar.checkbox(
    "Live Simulation (20Hz)",
    True
)

speed = st.sidebar.slider(
    "Playback Speed",
    0.5,
    5.0,
    1.0,
    0.5
)

tool_thresholds = {}

for i in range(1, 7):

    with st.sidebar.expander(f"Tool {i}"):

        start_th = st.number_input(
            f"Tool {i} Start Threshold",
            value=5.0,
            key=f"start{i}"
        )

        stop_th = st.number_input(
            f"Tool {i} Stop Threshold",
            value=2.0,
            key=f"stop{i}"
        )

        baseline = st.number_input(
            f"Tool {i} Sharp Baseline",
            value=12.0,
            key=f"base{i}"
        )

        wear_limit = st.number_input(
            f"Tool {i} Wear Limit",
            value=20.0,
            key=f"wear{i}"
        )

        tool_thresholds[f"Tool_{i}"] = {
            "start": start_th,
            "stop": stop_th,
            "baseline": baseline,
            "wear_limit": wear_limit
        }

# =====================================================
# DATA LOADING
# =====================================================

if uploaded_file:

    df = pd.read_csv(uploaded_file)

else:

    elapsed = np.arange(0, 300, 0.05)

    current = (
        10
        + np.sin(elapsed*0.4)*3
        + np.random.normal(0, 0.5, len(elapsed))
    )

    life = np.linspace(100, 5, len(elapsed))

    status = np.where(current > 11, "CUTTING", "IDLE")

    df = pd.DataFrame({
        "Elapsed_Time_s": elapsed,
        "Timestamp": pd.Timestamp.now(),
        "Current_A": current,
        "Tool_Life_Pct": life,
        "Status": status
    })

# =====================================================
# TOOL DETECTION
# =====================================================

def identify_tool(current):

    if current < 5:
        return "IDLE"

    if current < 8:
        return "Tool_1"

    elif current < 10:
        return "Tool_2"

    elif current < 12:
        return "Tool_3"

    elif current < 14:
        return "Tool_4"

    elif current < 16:
        return "Tool_5"

    else:
        return "Tool_6"

# =====================================================
# STATUS EVALUATION
# =====================================================

def wear_status(tool, current, life):

    config = tool_thresholds.get(tool)

    if tool == "IDLE":
        return "IDLE"

    if current < config["baseline"]:
        return "New Tool"

    elif current < (
        config["baseline"]
        + config["wear_limit"]
    )/2:
        return "Normal Wear"

    elif current < config["wear_limit"]:
        return "Worn Tool"

    return "Near Failure"

# =====================================================
# TABS
# =====================================================

dashboard_tab, analytics_tab = st.tabs(
    ["Live Dashboard", "Analytics"]
)

# =====================================================
# LIVE DASHBOARD
# =====================================================

with dashboard_tab:

    latest = df.iloc[-1]

    current = latest["Current_A"]

    life = latest["Tool_Life_Pct"]

    active_tool = identify_tool(current)

    condition = wear_status(
        active_tool,
        current,
        life
    )

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.markdown(f"""
        <div class='kpi-card'>
        Active Tool<br>
        <div class='metric-value green'>
        {active_tool}
        </div>
        </div>
        """, unsafe_allow_html=True)

    with col2:
        color = "green"

        if current > 15:
            color = "red"
        elif current > 12:
            color = "orange"

        st.markdown(f"""
        <div class='kpi-card'>
        Current
        <div class='metric-value {color}'>
        {current:.2f} A
        </div>
        </div>
        """, unsafe_allow_html=True)

    with col3:
        st.markdown(f"""
        <div class='kpi-card'>
        Tool Life
        <div class='metric-value yellow'>
        {life:.1f}%
        </div>
        </div>
        """, unsafe_allow_html=True)

        st.progress(float(life)/100)

    with col4:
        st.markdown(f"""
        <div class='kpi-card'>
        Status
        <div class='metric-value'>
        {condition}
        </div>
        </div>
        """, unsafe_allow_html=True)

# =====================================================
# LIVE PLOT
# =====================================================

    selected_tool = (
        active_tool
        if active_tool != "IDLE"
        else "Tool_1"
    )

    baseline = tool_thresholds[selected_tool]["baseline"]
    wear_limit = tool_thresholds[selected_tool]["wear_limit"]

    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=df["Elapsed_Time_s"],
            y=df["Current_A"],
            mode="lines",
            name="Current"
        )
    )

    fig.add_hline(
        y=baseline,
        line_dash="dash",
        line_color="green",
        annotation_text="Sharp Baseline"
    )

    fig.add_hline(
        y=wear_limit,
        line_dash="dash",
        line_color="red",
        annotation_text="Wear Limit"
    )

    fig.update_layout(
        template="plotly_dark",
        height=550,
        title="Real-Time Current Monitoring",
        paper_bgcolor="#0E1117",
        plot_bgcolor="#0E1117"
    )

    st.plotly_chart(
        fig,
        use_container_width=True
    )

# =====================================================
# LIVE SIMULATION
# =====================================================

    if simulate:

        progress = st.progress(0)

        chart_placeholder = st.empty()

        live_data = []

        for idx, row in df.iterrows():

            live_data.append(row)

            live_df = pd.DataFrame(live_data)

            fig_live = go.Figure()

            fig_live.add_trace(
                go.Scatter(
                    x=live_df["Elapsed_Time_s"],
                    y=live_df["Current_A"],
                    mode="lines",
                    line=dict(color="#00FF88")
                )
            )

            fig_live.update_layout(
                template="plotly_dark",
                height=450
            )

            chart_placeholder.plotly_chart(
                fig_live,
                use_container_width=True
            )

            progress.progress(
                min(
                    (idx + 1) / len(df),
                    1.0
                )
            )

            time.sleep(0.05 / speed)

# =====================================================
# ANALYTICS
# =====================================================

with analytics_tab:

    summary = df.groupby("Status").agg(
        Peak_Current=("Current_A", "max"),
        Avg_Current=("Current_A", "mean"),
        Amp_Seconds=("Current_A", "sum"),
        Min_Tool_Life=("Tool_Life_Pct", "min")
    ).reset_index()

    st.subheader("Cycle Summary")

    st.dataframe(
        summary,
        use_container_width=True
    )

    csv = summary.to_csv(index=False)

    st.download_button(
        label="Export CSV",
        data=csv,
        file_name="tool_summary.csv",
        mime="text/csv"
    )