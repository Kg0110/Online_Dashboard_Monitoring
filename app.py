import os
import glob
import time
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import streamlit as st

# -----------------------------
# PAGE CONFIGURATION
# -----------------------------
st.set_page_config(
    page_title="Real-Time Current & Tool Life Monitor",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for dark industrial high-contrast styling
st.markdown("""
<style>
    .metric-card {
        background-color: #1E222B;
        border-radius: 8px;
        padding: 15px;
        border-left: 5px solid #00E676;
    }
    .stApp {
        background-color: #0E1117;
    }
</style>
""", unsafe_allow_html=True)

# -----------------------------
# HARDWARE CONFIGURATIONS
# -----------------------------
TOOL_THRESHOLDS = {
    1: {"start": 2.5, "stop": 0.5, "sharp_baseline": 8.0,  "wear_limit": 12.0},
    2: {"start": 4.0, "stop": 1.0, "sharp_baseline": 9.5,  "wear_limit": 14.0},
    3: {"start": 15.2, "stop": 3.0, "sharp_baseline": 6.5,  "wear_limit": 10.5},
    4: {"start": 15.8, "stop": 1.8, "sharp_baseline": 11.0, "wear_limit": 16.0},
    5: {"start": 11.0, "stop": 3.0, "sharp_baseline": 10.0, "wear_limit": 15.0},
    6: {"start": 20.8, "stop": 0.9, "sharp_baseline": 8.5,  "wear_limit": 13.0},
}
DEFAULT_THRESHOLDS = {"start": 2.5, "stop": 1.0, "sharp_baseline": 8.0, "wear_limit": 12.0}

# -----------------------------
# HELPER FUNCTIONS
# -----------------------------
def calculate_tool_life(current_val, config):
    stop_thresh = config["stop"]
    sharp_baseline = config["sharp_baseline"]
    wear_threshold = config["wear_limit"]

    if current_val < stop_thresh:
        return 100.0, "IDLE", "#888888"

    wear_range = max(1.0, wear_threshold - sharp_baseline)
    life_pct = 100.0 - ((current_val - sharp_baseline) / wear_range) * 100.0
    life_pct = max(0.0, min(100.0, life_pct))

    if current_val < sharp_baseline + (wear_range * 0.25):
        return round(life_pct, 1), "New Tool", "#00FF00"
    elif current_val < sharp_baseline + (wear_range * 0.75):
        return round(life_pct, 1), "Normal Wear", "#FFFF00"
    elif current_val <= wear_threshold:
        return round(life_pct, 1), "Worn Tool", "#FF8C00"
    else:
        return round(life_pct, 1), "Near Failure", "#FF0000"

def get_latest_csv():
    desktop_folder = os.path.join(os.path.expanduser("~"), "Desktop", "CSV(current)")
    if not os.path.exists(desktop_folder):
        return None
    files = glob.glob(os.path.join(desktop_folder, "Tool_Data_Continuous_*.csv"))
    if not files:
        return None
    return max(files, key=os.path.getctime)

# -----------------------------
# SIDEBAR CONTROLS
# -----------------------------
st.sidebar.title("⚡ Control Panel")

data_source = st.sidebar.radio(
    "Select Data Source:",
    ("Local DAQ CSV Auto-Sync", "Live Demo Simulation")
)

auto_refresh = st.sidebar.checkbox("Enable Real-Time Auto Refresh", value=True)
refresh_rate = st.sidebar.slider("Refresh Rate (seconds)", 0.5, 5.0, 1.0)

st.sidebar.markdown("---")
st.sidebar.subheader("Active Tool Config")
selected_tool_id = st.sidebar.selectbox("Override Active Tool ID:", [f"Tool_{i}" for i in range(1, 7)])
tool_num = int(selected_tool_id.split("_")[1])
active_config = TOOL_THRESHOLDS.get(tool_num, DEFAULT_THRESHOLDS)

# -----------------------------
# DATA LOADING ENGINE
# -----------------------------
df = pd.DataFrame()

if data_source == "Local DAQ CSV Auto-Sync":
    latest_file = get_latest_csv()
    if latest_file and os.path.exists(latest_file):
        try:
            df = pd.read_csv(latest_file)
            st.sidebar.success(f"Connected: {os.path.basename(latest_file)}")
        except Exception as e:
            st.sidebar.error(f"Error reading local CSV: {e}")
    else:
        st.sidebar.warning("No DAQ CSV continuous logs found on Desktop.")

elif data_source == "Live Demo Simulation":
    # Generate 50 simulated continuous data points
    t_vals = np.linspace(0, 10, 50)
    base_signal = 8.5 + 2.5 * np.sin(t_vals) + np.random.normal(0, 0.4, 50)
    
    df = pd.DataFrame({
        "Elapsed_Time_s": t_vals,
        "Timestamp": [pd.Timestamp.now().strftime("%H:%M:%S.%f")[:-3] for _ in range(50)],
        "Current_A": base_signal
    })

# -----------------------------
# MAIN DASHBOARD UI
# -----------------------------
st.title("🛡️ Real-Time Tool Health & Current Monitor")

if not df.empty and "Current_A" in df.columns:
    latest_row = df.iloc[-1]
    latest_current = float(latest_row["Current_A"])
    
    life_pct, health_status, status_color = calculate_tool_life(latest_current, active_config)

    # High-Priority Alarm Card
    if latest_current > 20.0:
        st.error(f"🚨 **OVERCURRENT ALERT**: Current has exceeded threshold! ({latest_current:.2f} A)")
    elif health_status == "Near Failure":
        st.warning(f"⚠️ **CRITICAL TOOL WEAR**: {selected_tool_id} is near failure state!")

    # KPI Top Bar
    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    
    kpi1.metric("Active Tool", selected_tool_id)
    kpi2.metric("Live Current", f"{latest_current:.2f} A")
    kpi3.metric("Remaining Life", f"{life_pct:.1f}%")
    kpi4.metric("Tool Condition", health_status)

    st.markdown("---")

    # Plotly Real-Time Waveform Chart
    fig = go.Figure()

    # Current Signal Line
    x_axis = df["Elapsed_Time_s"] if "Elapsed_Time_s" in df.columns else df.index
    fig.add_trace(go.Scatter(
        x=x_axis,
        y=df["Current_A"],
        mode='lines',
        name='Current (A)',
        line=dict(color='#00E676', width=2)
    ))

    # Baseline and Wear Threshold Lines
    fig.add_hline(
        y=active_config["sharp_baseline"],
        line_dash="dash",
        line_color="#00FF00",
        annotation_text=f"Sharp Baseline ({active_config['sharp_baseline']} A)",
        annotation_position="top right"
    )

    fig.add_hline(
        y=active_config["wear_limit"],
        line_dash="dash",
        line_color="#FF0000",
        annotation_text=f"Wear Limit ({active_config['wear_limit']} A)",
        annotation_position="top right"
    )

    fig.update_layout(
        title=f"Live Amperage Waveform — {selected_tool_id}",
        xaxis_title="Elapsed Time (s)",
        yaxis_title="Current (A)",
        yaxis=dict(range=[0, max(25.0, df["Current_A"].max() + 2)]),
        template="plotly_dark",
        height=450,
        margin=dict(l=20, r=20, t=40, b=20)
    )

    st.plotly_chart(fig, use_container_width=True)

    # Data Logs Expansion Table
    with st.expander("📋 View Raw Telemetry Log Table"):
        st.dataframe(df.tail(20), use_container_width=True)

else:
    st.info("Waiting for data stream... Ensure your Python DAQ application is running or select 'Live Demo Simulation'.")

# Auto-refresh loop
if auto_refresh:
    time.sleep(refresh_rate)
    st.rerun()