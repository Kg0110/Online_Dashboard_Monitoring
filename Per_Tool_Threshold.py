import sys
import time
import os  
import csv  
import pyqtgraph as pg
from pyqtgraph.Qt import QtWidgets, QtCore
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np
from datetime import datetime

# NumPy 2.0+ Compatibility Fix for np.trapz
if not hasattr(np, 'trapz'):
    np.trapz = np.trapezoid

# Load DAQNavi DLL
import clr
clr.AddReference(
    r"C:\Advantech\DAQNavi\Automation.BDaq\1.0.0.0\Automation.BDaq.dll"
)
from Automation.BDaq import *

# -----------------------------
# HARDWARE & SIGNAL SETTINGS
# -----------------------------
DEVICE_DESC = "USB-4716,BID#1"
AI_CHANNEL = 0

WINDOW_SIZE = 10
SCALE = 19.7
FILTER_ALPHA = 0.2

# -----------------------------
# PER-TOOL CONFIGURATIONS (Tool 1 to Tool 6)
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

IDLE_TIMEOUT = 0.1           # Duration (s) below TOOL_STOP_THRESHOLD to finish cycle
OVERCURRENT_THRESHOLD = 20.0  # Alert threshold in Amperes

# -----------------------------
# TOOL LIFE EVALUATION HELPER
# -----------------------------
def calculate_tool_life_metrics(current_val, config=None):
    """
    Calculates remaining tool life percentage and health status string based on 
    the active tool's dynamic parameters.
    """
    if config is None:
        config = DEFAULT_THRESHOLDS

    stop_thresh = config["stop"]
    sharp_baseline = config["sharp_baseline"]
    wear_threshold = config["wear_limit"]

    if current_val < stop_thresh:
        return 100.0, "IDLE", "#888888"

    # Linear interpolation for Tool Life %
    wear_range = wear_threshold - sharp_baseline
    if wear_range <= 0:
        wear_range = 1.0  # Prevent division by zero
    
    life_pct = 100.0 - ((current_val - sharp_baseline) / wear_range) * 100.0
    life_pct = max(0.0, min(100.0, life_pct))  # Clamp between 0% and 100%

    # State Classification based on Active Current Ranges
    if current_val < sharp_baseline + (wear_range * 0.25):
        status = "New Tool"
        color = "#00FF00"  # Green
    elif current_val < sharp_baseline + (wear_range * 0.75):
        status = "Normal Wear"
        color = "#FFFF00"  # Yellow
    elif current_val <= wear_threshold:
        status = "Worn Tool"
        color = "#FF8C00"  # Dark Orange
    else:
        status = "Near Failure"
        color = "#FF0000"  # Red

    return round(life_pct, 1), status, color

# -----------------------------
# DYNAMIC FOLDER SETUP
# -----------------------------
DESKTOP_PATH = os.path.join(os.path.expanduser("~"), "Desktop")
CSV_FOLDER = os.path.join(DESKTOP_PATH, "CSV(current)")
IMAGE_FOLDER = os.path.join(DESKTOP_PATH, "Visual Comparison")

for folder in [CSV_FOLDER, IMAGE_FOLDER]:
    if not os.path.exists(folder):
        try:
            os.makedirs(folder)
            print(f"Created output folder: {folder}")
        except Exception as e:
            print(f"Warning: Could not create directory {folder}. Error: {e}")

# -----------------------------
# ANALOG INPUT INITIALIZATION
# -----------------------------
ai = InstantAiCtrl()
ai.SelectedDevice = DeviceInformation(DEVICE_DESC)
ai.Channels[AI_CHANNEL].ValueRange = ValueRange.V_0To5

# -----------------------------
# AUTO ZERO CALIBRATION
# -----------------------------
print("Calibrating hardware... Make sure NO LOAD is connected.")
time.sleep(0.5)

samples = []
for _ in range(30):
    result = ai.Read(AI_CHANNEL)
    v = float(result[1] if isinstance(result, tuple) else result)
    if v > 100:
        v /= 1000.0
    samples.append(v)
    time.sleep(0.02)

OFFSET = sum(samples) / len(samples)
print(f"OFFSET = {OFFSET:.3f} V")

# -----------------------------
# GUI INITIALIZATION
# -----------------------------
app = QtWidgets.QApplication(sys.argv)

win = pg.GraphicsLayoutWidget(show=True, title="DAQ Real-Time Tool Life Monitoring")
win.resize(1000, 600)

plot = win.addPlot(title="Current Monitoring(Tool Life Monitoring)")
plot.setLabel('bottom', 'Time', units='s')
plot.setLabel('left', 'Current', units='A')
plot.showGrid(x=True, y=True)

curve = plot.plot(pen=pg.mkPen('y', width=2))
plot.setYRange(0, 25, padding=0.05)

# --- REAL-TIME BASELINE & WEAR LINES ---
# FIX: Angle set to 0 for horizontal lines so .setValue() works cleanly without 2D coordinate errors
baseline_line = pg.InfiniteLine(
    angle=0, 
    pen=pg.mkPen(color='g', width=1.5, style=QtCore.Qt.DashLine), 
    label='Sharp Baseline', 
    labelOpts={'position': 0.85, 'color': (0, 255, 0)}
)
wear_line = pg.InfiniteLine(
    angle=0, 
    pen=pg.mkPen(color='r', width=1.5, style=QtCore.Qt.DashLine), 
    label='Tool Wear Limit', 
    labelOpts={'position': 0.85, 'color': (255, 0, 0)}
)

plot.addItem(baseline_line)
plot.addItem(wear_line)

text = pg.TextItem("", anchor=(0, 0))
plot.addItem(text)

# -----------------------------
# DATA BUFFERS & STATE
# -----------------------------
data_time = []          
data_clock_time = []    
data_current = []

start_time = time.time()
filtered_current = 0.0

# Tool Detection State Variables
is_tool_active = False
idle_start_time = None
tool_counter = 0
active_tool_data = {
    "tool_id": "None",
    "tool_number": 1,
    "config": TOOL_THRESHOLDS[1],
    "start_t": 0.0,
    "start_clock": "",
    "times": [],
    "currents": []
}
tool_summary_history = []

# -----------------------------
# CSV / PLOT EXPORT LOGIC
# -----------------------------
def export_tool_summary_csv():
    if not tool_summary_history:
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(CSV_FOLDER, f"Tool_Operations_Summary_{timestamp}.csv")

    try:
        with open(filepath, mode='w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(["Tool_ID", "Start_Clock", "Start_s", "End_s", "Duration_s", "Peak_A", "Avg_A", "Energy_AmpSec", "Min_Life_Pct", "Final_Status"])
            for tool in tool_summary_history:
                writer.writerow([
                    tool["tool_id"], tool["start_clock"], f"{tool['start_t']:.2f}",
                    f"{tool['end_t']:.2f}", f"{tool['duration']:.2f}", f"{tool['peak']:.2f}",
                    f"{tool['avg']:.2f}", f"{tool['energy']:.2f}", f"{tool['min_life_pct']:.1f}%",
                    tool["status"]
                ])
        print(f"[SUMMARY EXPORT] Summary updated: {filepath}")
    except Exception as e:
        print(f"Error writing summary CSV: {e}")

def export_combined_csv():
    if not data_time:
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(CSV_FOLDER, f"Tool_Data_Continuous_{timestamp}.csv")

    try:
        with open(filepath, mode='w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(["Elapsed_Time_s", "Timestamp", "Current_A", "Tool_Life_Pct", "Status"])
            for t, clock_t, i in zip(data_time, data_clock_time, data_current):
                active_cfg = active_tool_data.get("config", DEFAULT_THRESHOLDS)
                life_pct, status_str, _ = calculate_tool_life_metrics(i, config=active_cfg)
                writer.writerow([f"{t:.2f}", clock_t, f"{i:.3f}", f"{life_pct:.1f}%", status_str])
        print(f"[CONTINUOUS EXPORT] Continuous data saved: {filepath}")
    except Exception as e:
        print(f"Error saving continuous CSV: {e}")

def export_tool_comparison_plot(tool_id, times, currents, tool_history=None, config=None):
    if len(times) == 0:
        return

    sub_times = np.array(times)
    sub_currents = np.array(currents)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(IMAGE_FOLDER, f"{tool_id}_Comparison_{timestamp}.png")

    if config is None:
        config = DEFAULT_THRESHOLDS

    try:
        fig, ax = plt.subplots(figsize=(14, 6))
        ax.plot(sub_times, sub_currents, color='#0055ff', linewidth=1.5, label='Current (A)')
        
        # --- EXPORT PLOT BASELINES ---
        ax.axhline(y=config["sharp_baseline"], color='green', linestyle='--', linewidth=1.5, label=f'Sharp Baseline ({config["sharp_baseline"]}A)')
        ax.axhline(y=config["wear_limit"], color='red', linestyle='--', linewidth=1.5, label=f'Tool Wear Limit ({config["wear_limit"]}A)')

        if tool_history:
            colors = ['#ffaaaa', '#aaffaa', '#aaaaff', '#ffffaa', '#ffaaff', '#aaffff']
            for idx, tool in enumerate(tool_history):
                start_t, end_t, t_id = tool["start_t"], tool["end_t"], tool["tool_id"]
                ax.axvspan(start_t, end_t, color=colors[idx % len(colors)], alpha=0.3)
                mid_t = (start_t + end_t) / 2
                label_txt = f"{t_id}\n({tool['min_life_pct']:.0f}% Life)"
                ax.text(mid_t, max(sub_currents) * 0.85 if max(sub_currents) > 0 else 10, label_txt, fontsize=8, fontweight='bold', ha='center')

        ax.xaxis.set_major_locator(ticker.MultipleLocator(5))
        plt.xticks(rotation=45, fontsize=8)
        ax.set_xlim(min(sub_times), max(sub_times))
        ax.set_title(f"Waveform Analysis ({tool_id}) - Tool Health Monitoring", fontsize=12, fontweight='bold')
        ax.set_xlabel("Elapsed Time (s)")
        ax.set_ylabel("Current (A)")
        ax.grid(True, linestyle='--', alpha=0.6)
        ax.legend(loc='upper right')
        
        plt.tight_layout()
        plt.savefig(filepath, dpi=300)
        plt.close(fig)
    except Exception as e:
        print(f"Error rendering plot image: {e}")

def export_on_exit():
    export_combined_csv()
    export_tool_summary_csv()
    if data_time:
        export_tool_comparison_plot("Session_Final", data_time, data_current, tool_history=tool_summary_history)

app.aboutToQuit.connect(export_on_exit)

# -----------------------------
# TOOL DETECTION ENGINE (DYNAMIC PER-TOOL THRESHOLDS)
# -----------------------------
def process_tool_detection(current_t, clock_str, current_val):
    global is_tool_active, idle_start_time, tool_counter, active_tool_data

    # Cycle tool index sequentially from 1 to 6
    next_tool_num = (tool_counter % 6) + 1 if not is_tool_active else ((tool_counter - 1) % 6) + 1
    current_config = TOOL_THRESHOLDS.get(next_tool_num, DEFAULT_THRESHOLDS)

    # Case 1: Start a new tool (Current >= Next Tool's Start Threshold)
    if current_val >= current_config["start"] and not is_tool_active:
        is_tool_active = True
        idle_start_time = None
        tool_counter += 1
        
        active_tool_num = ((tool_counter - 1) % 6) + 1
        tool_id = f"Tool_{active_tool_num}"
        
        active_tool_data = {
            "tool_id": tool_id,
            "tool_number": active_tool_num,
            "config": TOOL_THRESHOLDS.get(active_tool_num, DEFAULT_THRESHOLDS),
            "start_t": current_t,
            "start_clock": clock_str,
            "times": [current_t],
            "currents": [current_val]
        }
        print(f"---> [STARTED] {tool_id} (Start Thresh: {current_config['start']}A) at {current_t:.2f}s")

    # Case 2: Tool is currently ACTIVE
    elif is_tool_active:
        active_tool_data["times"].append(current_t)
        active_tool_data["currents"].append(current_val)
        active_config = active_tool_data["config"]

        # Current stays above Stop Threshold -> reset idle timer
        if current_val >= active_config["stop"]:
            idle_start_time = None

        # Current drops below Stop Threshold -> start tracking idle timeout
        else:
            if idle_start_time is None:
                idle_start_time = time.time()

            # Confirm tool STOP if below Stop Threshold for longer than IDLE_TIMEOUT
            if (time.time() - idle_start_time) >= IDLE_TIMEOUT:
                is_tool_active = False
                end_t = current_t
                duration = max(0.5, end_t - active_tool_data["start_t"] - IDLE_TIMEOUT)

                currents_arr = np.array(active_tool_data["currents"])
                peak_current = float(np.max(currents_arr))
                min_life, final_status, _ = calculate_tool_life_metrics(peak_current, config=active_config)

                summary = {
                    "tool_id": active_tool_data["tool_id"],
                    "start_clock": active_tool_data["start_clock"],
                    "start_t": active_tool_data["start_t"],
                    "end_t": end_t,
                    "duration": duration,
                    "peak": peak_current,
                    "avg": float(np.mean(currents_arr)),
                    "energy": float(np.trapezoid(currents_arr, active_tool_data["times"])),
                    "min_life_pct": min_life,
                    "status": final_status
                }
                
                tool_summary_history.append(summary)
                print(f"---> [COMPLETED] {active_tool_data['tool_id']} | Life: {min_life:.1f}% | Status: {final_status}")
                
                export_tool_comparison_plot(
                    active_tool_data["tool_id"],
                    active_tool_data["times"],
                    active_tool_data["currents"],
                    config=active_config
                )
                export_tool_summary_csv()

# -----------------------------
# MAIN LOOP (20 Hz Update)
# -----------------------------
def update():
    global filtered_current

    # Hardware Read
    result = ai.Read(AI_CHANNEL)
    v = float(result[1] if isinstance(result, tuple) else result)
    if v > 100:
        v /= 1000.0

    raw_current = max(0.0, (v - OFFSET) * SCALE)
    filtered_current = (FILTER_ALPHA * raw_current) + ((1 - FILTER_ALPHA) * filtered_current)

    now = time.time()
    current_t = now - start_time
    clock_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    data_time.append(current_t)
    data_clock_time.append(clock_str)
    data_current.append(filtered_current)

    process_tool_detection(current_t, clock_str, filtered_current)

    # Determine Active Tool Configuration for Live Overlay
    if is_tool_active:
        active_cfg = active_tool_data["config"]
    else:
        next_num = (tool_counter % 6) + 1
        active_cfg = TOOL_THRESHOLDS.get(next_num, DEFAULT_THRESHOLDS)

    # Tool Life & Health Metrics
    tool_life_pct, tool_status, status_color = calculate_tool_life_metrics(filtered_current, config=active_cfg)

    # Dynamically Update Dynamic Threshold Lines on pyqtgraph Window
    baseline_line.setValue(active_cfg["sharp_baseline"])
    wear_line.setValue(active_cfg["wear_limit"])

    # Plot UI updates
    display_time = np.array(data_time)
    display_current = np.array(data_current)
    mask = display_time >= (current_t - WINDOW_SIZE)
    
    curve.setData(display_time[mask], display_current[mask])

    op_status = f"ACTIVE ({active_tool_data['tool_id']})" if is_tool_active else "IDLE"
    
    # Formatted Real-time Health Overlay
    text_content = (
        f"Operation: {op_status}\n"
        f"Current: {filtered_current:.2f} A\n"
        f"Tool Condition: {tool_status}\n"
        f"Remaining Life: {tool_life_pct:.1f}%\n"
        f"Detected Tools: {len(tool_summary_history)}"
    )
    text.setText(text_content)
    text.setPos(current_t - WINDOW_SIZE + 0.5 if current_t > WINDOW_SIZE else 0.5, 22)

timer = QtCore.QTimer()
timer.timeout.connect(update)
timer.start(20)

if __name__ == '__main__':
    sys.argv.append("-platform")
    sys.argv.append("windows")
    sys.exit(app.exec_())