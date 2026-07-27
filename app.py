import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px

# --- PAGE CONFIGURATION ---
st.set_page_config(
    page_title="Live Operations Dashboard",
    page_icon="📊",
    layout="wide"
)

# --- TITLE & HEADER ---
st.title("📊 Real-Time Operations Dashboard")
st.markdown("Monitor performance, revenue, and system metrics in pure Python.")

# --- MOCK DATA GENERATION ---
@st.cache_data
def load_data():
    np.random.seed(42)
    dates = pd.date_range(start="2026-01-01", periods=100)
    data = pd.DataFrame({
        "Date": dates,
        "Region": np.random.choice(["North", "South", "East", "West"], size=100),
        "Sales": np.random.randint(100, 1000, size=100),
        "Active_Users": np.random.randint(50, 500, size=100),
        "Error_Rate": np.random.uniform(0.1, 2.5, size=100)
    })
    return data

df = load_data()

# --- SIDEBAR FILTERS ---
st.sidebar.header("Filter Options")
selected_region = st.sidebar.multiselect(
    "Select Region(s):",
    options=df["Region"].unique(),
    default=df["Region"].unique()
)

# Filter Dataframe
filtered_df = df[df["Region"].isin(selected_region)]

# --- KEY METRICS (KPI CARDS) ---
col1, col2, col3 = st.columns(3)

total_sales = filtered_df["Sales"].sum()
avg_users = int(filtered_df["Active_Users"].mean()) if not filtered_df.empty else 0
avg_error = filtered_df["Error_Rate"].mean() if not filtered_df.empty else 0.0

col1.metric("Total Revenue", f"${total_sales:,.2f}", delta="+12%")
col2.metric("Avg Active Users", f"{avg_users:,}", delta="+5%")
col3.metric("Avg Error Rate", f"{avg_error:.2f}%", delta="-0.4%", delta_color="inverse")

st.divider()

# --- CHARTS SECTION ---
chart_col1, chart_col2 = st.columns(2)

with chart_col1:
    st.subheader("📈 Sales Trend Over Time")
    fig_line = px.line(
        filtered_df, 
        x="Date", 
        y="Sales", 
        color="Region", 
        title="Daily Sales by Region"
    )
    st.plotly_chart(fig_line, use_container_width=True)

with chart_col2:
    st.subheader("📊 Sales Distribution by Region")
    fig_bar = px.bar(
        filtered_df.groupby("Region", as_index=False)["Sales"].sum(),
        x="Region",
        y="Sales",
        color="Region",
        title="Total Sales Per Region"
    )
    st.plotly_chart(fig_bar, use_container_width=True)

# --- DATA TABLE SECTION ---
st.divider()
st.subheader("📋 Raw Data Explorer")

# Interactive data table
st.dataframe(filtered_df, use_container_width=True)

# Download CSV button
csv_data = filtered_df.to_csv(index=False).encode('utf-8')
st.download_button(
    label="📥 Download Filtered Data CSV",
    data=csv_data,
    file_name="dashboard_data.csv",
    mime="text/csv"
)