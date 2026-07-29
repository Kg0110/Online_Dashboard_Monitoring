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

# Load DAQNavi
import clr
clr.AddReference(
    r"C:\Advantech\DAQNavi\Automation.BDaq\1.0.0.0\Automation.BDaq.dll"
)
from Automation.BDaq import *

# -----------------------------
# SETTINGS
# -----------------------------
DEVICE_DESC = "USB-4716,BID#1"
AI_CHANNEL = 0

WINDOW_SIZE = 10
SCALE = 19.7
FILTER_ALPHA = 0.2

# -----------------------------
# TOOL DETECTION CONFIGURATION
# -----------------------------
TOOL_START_THRESHOLD = 2.5    # Minimum current (A) to consider a tool ACTIVE
IDLE_TIMEOUT = 0.5            # Duration (s) below threshold to consider tool FINISHED

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
            print(f"Created dedicated output folder: {folder}")
        except Exception as e:
            print(f"Warning: Could not create directory {folder}. Error: {e}")

# -----------------------------
# ANALOG INPUT
# -----------------------------
ai = InstantAiCtrl()
ai.SelectedDevice = DeviceInformation(DEVICE_DESC)
ai.Channels[AI_CHANNEL].ValueRange = ValueRange.V_0To5

# -----------------------------
# AUTO ZERO
# -----------------------------
print("Make sure NO LOAD is connected...")
time.sleep(2)

samples = []

for _ in range(30):
    result = ai.Read(AI_CHANNEL)
    if isinstance(result, tuple):
        _, v = result
    else:
        v = result

    v = float(v)

    if v > 100:
        v = v / 1000

    samples.append(v)
    time.sleep(0.02)

OFFSET = sum(samples) / len(samples)
print(f"OFFSET = {OFFSET:.3f} V")

# -----------------------------
# GRAPH SETUP
# -----------------------------
app = QtWidgets.QApplication(sys.argv)

win = pg.GraphicsLayoutWidget(show=True, title="DAQ Monitoring")
win.resize(1000, 600)

plot = win.addPlot(title="Current vs Time (Automated Tool Detection Active)")
plot.setLabel('bottom', 'Time', units='s')
plot.setLabel('left', 'Current', units='A')
plot.showGrid(x=True, y=True)

curve = plot.plot(pen=pg.mkPen('y', width=2))
plot.setYRange(0, 50)

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
    "tool_id": "",
    "start_t": 0.0,
    "start_clock": "",
    "times": [],
    "currents": []
}
tool_summary_history = []
tool_raw_curves = []  # Stores full raw time and current arrays per tool for overlay plot

# -----------------------------
# EXPORT DATA FUNCTIONS
# -----------------------------
def export_tool_summary_csv():
    """Exports a dedicated summary CSV containing stats for every detected tool cycle."""
    if not tool_summary_history:
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_filename = f"Tool_Operations_Summary_{timestamp}.csv"
    filepath = os.path.join(CSV_FOLDER, csv_filename) if os.path.exists(CSV_FOLDER) else csv_filename

    try:
        with open(filepath, mode='w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow([
                "Tool_ID", 
                "Start_Clock_Time", 
                "Start_Elapsed_s", 
                "End_Elapsed_s", 
                "Duration_s", 
                "Peak_Current_A", 
                "Avg_Current_A", 
                "Energy_AmpSec"
            ])
            for tool in tool_summary_history:
                writer.writerow([
                    tool["tool_id"],
                    tool["start_clock"],
                    f"{tool['start_t']:.2f}",
                    f"{tool['end_t']:.2f}",
                    f"{tool['duration']:.2f}",
                    f"{tool['peak']:.2f}",
                    f"{tool['avg']:.2f}",
                    f"{tool['energy']:.2f}"
                ])
        print(f"\n[TOOL LOG UPDATED] Tool summary report saved to: {filepath}")
    except Exception as e:
        print(f"Error saving Tool Summary CSV: {e}")

def export_combined_csv():
    """Saves all logged continuous data to CSV upon exit or manual trigger."""
    if not data_time:
        print("No data recorded to export.")
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_filename = f"Tool_Data_Continuous_{timestamp}.csv"
    filepath = os.path.join(CSV_FOLDER, csv_filename) if os.path.exists(CSV_FOLDER) else csv_filename

    try:
        with open(filepath, mode='w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(["Elapsed_Time_s", "Timestamp", "Current_A"])
            for t, clock_t, i in zip(data_time, data_clock_time, data_current):
                writer.writerow([f"{t:.2f}", clock_t, f"{i:.3f}"])
        print(f"Successfully recorded continuous data saved to: {filepath}")
    except Exception as e:
        print(f"Error saving CSV: {e}")

def export_tool_comparison_plot(tool_id, times, currents, tool_history=None):
    """Generates and saves a PNG plot with 5-second tick intervals and labeled tool spans."""
    if len(times) == 0:
        return

    sub_times = np.array(times)
    sub_currents = np.array(currents)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    img_filename = f"{tool_id}_Comparison_{timestamp}.png"
    filepath = os.path.join(IMAGE_FOLDER, img_filename) if os.path.exists(IMAGE_FOLDER) else img_filename

    try:
        fig, ax = plt.subplots(figsize=(14, 6))
        ax.plot(sub_times, sub_currents, color='#0055ff', linewidth=1.5, label='Current (A)')
        
        # --- ADD TOOL IDENTIFICATION LABELS AND HIGHLIGHTS ---
        if tool_history and len(tool_history) > 0:
            colors = ['#ffaaaa', '#aaffaa', '#aaaaff', '#ffffaa', '#ffaaff', '#aaffff']
            for idx, tool in enumerate(tool_history):
                start_t = tool["start_t"]
                end_t = tool["end_t"]
                t_id = tool["tool_id"]
                color = colors[idx % len(colors)]
                
                # Highlight active tool region with translucent color
                ax.axvspan(start_t, end_t, color=color, alpha=0.3, label=f"{t_id} Active" if tool_id == "Session_Final" else None)
                
                # Place text label above the peak/middle of the active region
                mid_t = (start_t + end_t) / 2
                peak_in_range = max([c for t, c in zip(times, currents) if start_t <= t <= end_t], default=max(sub_currents))
                ax.text(mid_t, peak_in_range + 1.5, t_id, fontsize=9, fontweight='bold', 
                        ha='center', va='bottom', bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="gray", alpha=0.8))

        # Set x-axis tick marks strictly at 5-second intervals
        ax.xaxis.set_major_locator(ticker.MultipleLocator(5))
        plt.xticks(rotation=45, fontsize=8)
        
        ax.set_xlim(min(sub_times), max(sub_times))

        peak_val = max(sub_currents)
        avg_val = np.mean(sub_currents)
        
        ax.set_title(f"Current Waveform ({tool_id})\nPeak: {peak_val:.2f} A | Avg: {avg_val:.2f} A", fontsize=12, fontweight='bold')
        ax.set_xlabel("Elapsed Time (s)", fontsize=10)
        ax.set_ylabel("Current (A)", fontsize=10)
        ax.grid(True, linestyle='--', alpha=0.6)
        ax.legend(loc='upper right')
        
        plt.tight_layout()
        plt.savefig(filepath, dpi=300)
        plt.close(fig)
        print(f"Successfully saved comparison plot PNG to: {filepath}")
    except Exception as e:
        print(f"Error saving comparison plot image: {e}")

def export_final_tools_overlay_plot():
    """Overlays all recorded tool current profiles from t=0 to compare Tool 1 through Tool N on one graph."""
    if not tool_raw_curves:
        print("No tool operation data available for overlay comparison.")
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    img_filename = f"ALL_TOOLS_COMPARISON_OVERLAY_{timestamp}.png"
    filepath = os.path.join(IMAGE_FOLDER, img_filename) if os.path.exists(IMAGE_FOLDER) else img_filename

    try:
        fig, ax = plt.subplots(figsize=(14, 7))
        colors = plt.cm.tab10(np.linspace(0, 1, len(tool_raw_curves)))

        for idx, tool_data in enumerate(tool_raw_curves):
            t_id = tool_data["tool_id"]
            raw_times = np.array(tool_data["times"])
            raw_currents = np.array(tool_data["currents"])

            # Zero-align time axis for direct side-by-side comparison
            rel_times = raw_times - raw_times[0]
            
            peak = np.max(raw_currents)
            avg = np.mean(raw_currents)
            
            ax.plot(rel_times, raw_currents, label=f"{t_id} (Peak: {peak:.1f}A, Avg: {avg:.1f}A)", 
                    color=colors[idx], linewidth=2.0)

        ax.set_title(f"Direct Comparison: Tool 1 to Tool {len(tool_raw_curves)} Waveform Profiles", fontsize=14, fontweight='bold')
        ax.set_xlabel("Normalized Operation Time (s)", fontsize=11)
        ax.set_ylabel("Current (A)", fontsize=11)
        ax.grid(True, linestyle='--', alpha=0.7)
        ax.legend(loc='upper right', fontsize=10)

        plt.tight_layout()
        plt.savefig(filepath, dpi=300)
        plt.close(fig)
        print(f"Successfully saved multi-tool overlaid comparison image to: {filepath}")
    except Exception as e:
        print(f"Error generating tool overlay comparison plot: {e}")

def export_on_exit():
    """Handler to export CSV data, summaries, full session PNG, and Tool 1..N Overlay on exit."""
    export_combined_csv()
    export_tool_summary_csv()
    if data_time:
        export_tool_comparison_plot("Session_Final", data_time, data_current, tool_history=tool_summary_history)
    export_final_tools_overlay_plot()

# Register export on application exit
app.aboutToQuit.connect(export_on_exit)

# -----------------------------
# TOOL SEGMENTATION ENGINE
# -----------------------------
def process_tool_detection(current_t, clock_str, current_val):
    """Detects when a tool starts and stops, logging individual tool metrics."""
    global is_tool_active, idle_start_time, tool_counter, active_tool_data

    # Check if current indicates tool activity
    if current_val >= TOOL_START_THRESHOLD:
        idle_start_time = None  # Reset idle timer

        if not is_tool_active:
            # TOOL OPERATION STARTED
            is_tool_active = True
            tool_counter += 1
            tool_id = f"Tool_{tool_counter}"
            
            active_tool_data = {
                "tool_id": tool_id,
                "start_t": current_t,
                "start_clock": clock_str,
                "times": [current_t],
                "currents": [current_val]
            }
            print(f"\n---> [STARTED] {tool_id} at {current_t:.2f}s ({clock_str})")
        else:
            # TOOL IS CONTINUING
            active_tool_data["times"].append(current_t)
            active_tool_data["currents"].append(current_val)

    else:
        # Current is below threshold (Tool potentially idle)
        if is_tool_active:
            if idle_start_time is None:
                idle_start_time = time.time()
            
            # Record data during brief pause
            active_tool_data["times"].append(current_t)
            active_tool_data["currents"].append(current_val)

            # Check if idle threshold duration exceeded
            if (time.time() - idle_start_time) >= IDLE_TIMEOUT:
                # TOOL OPERATION COMPLETED
                is_tool_active = False
                end_t = current_t
                duration = end_t - active_tool_data["start_t"] - IDLE_TIMEOUT
                if duration < 0.5:
                    duration = 0.5

                currents_arr = np.array(active_tool_data["currents"])
                peak_curr = float(np.max(currents_arr))
                avg_curr = float(np.mean(currents_arr))
                
                # Updated for NumPy 2.0+ compatibility
                energy = float(np.trapezoid(currents_arr, active_tool_data["times"]))  # Ampere-seconds

                summary = {
                    "tool_id": active_tool_data["tool_id"],
                    "start_clock": active_tool_data["start_clock"],
                    "start_t": active_tool_data["start_t"],
                    "end_t": end_t,
                    "duration": duration,
                    "peak": peak_curr,
                    "avg": avg_curr,
                    "energy": energy
                }
                
                tool_summary_history.append(summary)
                tool_raw_curves.append({
                    "tool_id": active_tool_data["tool_id"],
                    "times": list(active_tool_data["times"]),
                    "currents": list(active_tool_data["currents"])
                })
                
                print(f"---> [COMPLETED] {active_tool_data['tool_id']} | Duration: {duration:.2f}s | Peak: {peak_curr:.2f}A | Avg: {avg_curr:.2f}A")
                
                # Export individual image plot for this finished tool operation
                export_tool_comparison_plot(
                    active_tool_data["tool_id"],
                    active_tool_data["times"],
                    active_tool_data["currents"]
                )

                # Auto-export tool summary CSV
                export_tool_summary_csv()

# -----------------------------
# UPDATE LOOP (Continuous Sampling)
# -----------------------------
def update():
    global filtered_current

    # Read DAQ hardware
    result = ai.Read(AI_CHANNEL)
    v = result[1] if isinstance(result, tuple) else result
    v = float(v)
    if v > 100:
        v = v / 1000.0

    # Calculate calibrated current with zero offset
    raw_current = (v - OFFSET) * SCALE
    if raw_current < 0:
        raw_current = 0.0

    # Low-pass filter for visual stability
    filtered_current = (FILTER_ALPHA * raw_current) + ((1 - FILTER_ALPHA) * filtered_current)

    current_t = time.time() - start_time
    clock_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    # Append continuously without interval resets
    data_time.append(current_t)
    data_clock_time.append(clock_str)
    data_current.append(filtered_current)

    # Process automated tool detection logic
    process_tool_detection(current_t, clock_str, filtered_current)

    # Maintain rolling plot window for UI performance
    display_time = np.array(data_time)
    display_current = np.array(data_current)

    mask = display_time >= (current_t - WINDOW_SIZE)
    curve.setData(display_time[mask], display_current[mask])

    # Update real-time numerical overlay with tool status
    status_str = f"ACTIVE ({active_tool_data['tool_id']})" if is_tool_active else "IDLE / NO LOAD"
    text.setText(f"Status: {status_str}\nCurrent: {filtered_current:.2f} A\nDetected Tools: {len(tool_summary_history)}")
    text.setPos(current_t - WINDOW_SIZE + 0.5 if current_t > WINDOW_SIZE else 0.5, 42)

# Timer to trigger update every 50ms (20 Hz sampling)
timer = QtCore.QTimer()
timer.timeout.connect(update)
timer.start(50)

if __name__ == '__main__':
    sys.exit(app.exec_())