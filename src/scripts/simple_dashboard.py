"""
🌙 TradeHive's Simple Backtest Dashboard
Streamlit-based dashboard for viewing RBI agent backtest results
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from pathlib import Path
import sys

# Configuration
BASE_DIR = Path(__file__).parent.parent.parent
STATS_CSV = BASE_DIR / "src/data/rbi_pp_multi/backtest_stats.csv"
BACKTESTS_DIR = BASE_DIR / "src/data/rbi_pp_multi/10_30_2025/backtests_working"

# Page config
st.set_page_config(
    page_title="Backtest Results Dashboard",
    page_icon="🚀",
    layout="wide"
)

# Title
st.title("🌙 TradeHive's Backtest Dashboard")
st.markdown("### AI-Generated Trading Strategy Results")

# Load data
@st.cache_data
def load_data():
    if STATS_CSV.exists():
        df = pd.read_csv(STATS_CSV)
        return df
    return None

df = load_data()

if df is None or df.empty:
    st.error("⚠️ No backtest results found!")
    st.info(f"Looking for: {STATS_CSV}")
    st.info("Run the RBI agent first: `python -m src.agents.rbi_agent_pp_multi`")
else:
    # Sidebar filters
    st.sidebar.header("Filters")

    # Refresh button
    if st.sidebar.button("🔄 Refresh Data"):
        st.cache_data.clear()
        st.rerun()

    # Main metrics
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Total Strategies", len(df))

    with col2:
        avg_return = df['Return %'].mean()
        st.metric("Avg Return", f"{avg_return:.2f}%")

    with col3:
        best_return = df['Return %'].max()
        st.metric("Best Return", f"{best_return:.2f}%")

    with col4:
        profitable = len(df[df['Return %'] > 0])
        st.metric("Profitable", f"{profitable}/{len(df)}")

    st.markdown("---")

    # Results table
    st.subheader("📊 Backtest Results")

    # Format the dataframe for display
    display_df = df.copy()
    display_df['Return %'] = display_df['Return %'].round(2)
    display_df['Buy & Hold %'] = display_df['Buy & Hold %'].round(2)
    display_df['Max Drawdown %'] = display_df['Max Drawdown %'].round(2)
    display_df['Sharpe Ratio'] = display_df['Sharpe Ratio'].round(2)
    display_df['Sortino Ratio'] = display_df['Sortino Ratio'].round(2)

    # Color code returns
    def color_returns(val):
        if isinstance(val, (int, float)):
            color = 'green' if val > 0 else 'red'
            return f'color: {color}'
        return ''

    styled_df = display_df.style.applymap(
        color_returns,
        subset=['Return %', 'Buy & Hold %']
    )

    st.dataframe(
        styled_df,
        use_container_width=True,
        hide_index=True
    )

    st.markdown("---")

    # Charts
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("📈 Returns Distribution")
        fig = px.bar(
            df,
            x='Strategy Name',
            y='Return %',
            color='Return %',
            color_continuous_scale=['red', 'yellow', 'green'],
            title="Strategy Returns"
        )
        fig.update_layout(showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.subheader("📉 Risk Metrics")
        fig = go.Figure()
        fig.add_trace(go.Bar(
            name='Sharpe Ratio',
            x=df['Strategy Name'],
            y=df['Sharpe Ratio'],
            marker_color='lightblue'
        ))
        fig.add_trace(go.Bar(
            name='Sortino Ratio',
            x=df['Strategy Name'],
            y=df['Sortino Ratio'],
            marker_color='lightgreen'
        ))
        fig.update_layout(barmode='group', title="Risk-Adjusted Returns")
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")

    # Strategy details
    st.subheader("🔍 Strategy Details")

    selected_strategy = st.selectbox(
        "Select a strategy to view details:",
        df['Strategy Name'].tolist()
    )

    if selected_strategy:
        strategy_data = df[df['Strategy Name'] == selected_strategy].iloc[0]

        col1, col2, col3 = st.columns(3)

        with col1:
            st.metric("Return", f"{strategy_data['Return %']:.2f}%")
            st.metric("Sharpe Ratio", f"{strategy_data['Sharpe Ratio']:.2f}")
            st.metric("Trades", int(strategy_data['Trades']))

        with col2:
            st.metric("Buy & Hold", f"{strategy_data['Buy & Hold %']:.2f}%")
            st.metric("Sortino Ratio", f"{strategy_data['Sortino Ratio']:.2f}")
            st.metric("Exposure", f"{strategy_data['Exposure %']:.2f}%")

        with col3:
            st.metric("Max Drawdown", f"{strategy_data['Max Drawdown %']:.2f}%")
            st.metric("Data Source", strategy_data['Data'])
            st.metric("Thread", strategy_data['Thread ID'])

        # Show code file path
        st.info(f"📁 Code: `{strategy_data['File Path']}`")

        # Try to load and display the code
        code_path = Path(strategy_data['File Path'])
        if code_path.exists():
            with st.expander("🐍 View Generated Code"):
                with open(code_path, 'r') as f:
                    code = f.read()
                st.code(code, language='python')
        else:
            st.warning("Code file not found at the specified path")

# Footer
st.markdown("---")
st.markdown("Built with ❤️ by TradeHive | Powered by AI")
