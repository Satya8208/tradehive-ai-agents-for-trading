'''
🌙 TradeHive's Feedback Connector v1.0
Bridges backtest results → scalping agent learning

This module connects the RBI backtesting agent results back to the scalping agent,
enabling adaptive learning about which techniques and strategies perform best.

Features:
- Parse backtest_stats.csv results
- Match strategies back to techniques via scalping_ideas.csv  
- Update technique performance tracking
- Generate insights for prompt injection
- Dashboard data generation

Created with love by TradeHive 🚀
'''

import os
import sys
import json
import re
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import pandas as pd
from termcolor import cprint

# ============================================
# 📁 PATH CONFIGURATION
# ============================================

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "src" / "data"

# RBI PP Multi data paths (where backtest results are stored)
RBI_PP_MULTI_DIR = DATA_DIR / "rbi_pp_multi"
BACKTEST_STATS_CSV = RBI_PP_MULTI_DIR / "backtest_stats.csv"

# Scalping strategies data paths
SCALPING_DIR = DATA_DIR / "scalping_strategies"
SCALPING_IDEAS_CSV = SCALPING_DIR / "scalping_ideas.csv"
TECHNIQUE_PERFORMANCE_FILE = SCALPING_DIR / "technique_performance.json"
FEEDBACK_CONFIG_FILE = SCALPING_DIR / "feedback_config.json"
FEEDBACK_HISTORY_FILE = SCALPING_DIR / "feedback_history.json"

# v6.5 - New dedicated feedback results CSV (logged by RBI agent)
FEEDBACK_RESULTS_CSV = SCALPING_DIR / "feedback_results.csv"

# Dashboard data output
DASHBOARD_DATA_FILE = SCALPING_DIR / "dashboard_data.json"

# ============================================
# ⚙️ DEFAULT CONFIGURATION
# ============================================

DEFAULT_FEEDBACK_CONFIG = {
    "sync_on_startup": True,
    "min_trades_for_significance": 3,
    "lookback_days": 30,
    "weight_adjustments": {
        "win_rate_weight": 0.4,
        "sharpe_weight": 0.3,
        "recent_performance_weight": 0.2,
        "diversity_weight": 0.1
    },
    "underperformer_threshold": 0.35,  # Win rate below this = underperformer
    "top_performer_threshold": 0.55,   # Win rate above this = top performer
    "max_results_per_sync": 100,       # Limit results to process per sync
    "keep_underperformers": True       # User preference: keep them with lower weight
}


def load_feedback_config() -> dict:
    """Load feedback configuration from file or use defaults"""
    if FEEDBACK_CONFIG_FILE.exists():
        try:
            with open(FEEDBACK_CONFIG_FILE, 'r') as f:
                config = json.load(f)
                # Merge with defaults to handle missing keys
                return {**DEFAULT_FEEDBACK_CONFIG, **config}
        except Exception as e:
            cprint(f"⚠️ Error loading feedback config: {e}", "yellow")
    return DEFAULT_FEEDBACK_CONFIG


def save_feedback_config(config: dict) -> None:
    """Save feedback configuration to file"""
    try:
        FEEDBACK_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(FEEDBACK_CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
        cprint("💾 Feedback config saved", "green")
    except Exception as e:
        cprint(f"❌ Error saving feedback config: {e}", "red")


# ============================================
# 📊 CSV PARSING FUNCTIONS
# ============================================

def parse_backtest_stats(lookback_days: int = 30) -> pd.DataFrame:
    """
    Parse backtest_stats.csv and return results from the last N days.
    
    Returns DataFrame with columns:
    - strategy_name, return_pct, sharpe, sortino, trades, max_drawdown, timestamp
    """
    if not BACKTEST_STATS_CSV.exists():
        cprint(f"⚠️ Backtest stats CSV not found: {BACKTEST_STATS_CSV}", "yellow")
        return pd.DataFrame()
    
    try:
        df = pd.read_csv(BACKTEST_STATS_CSV)
        
        # Expected columns from RBI agent
        # Strategy Name, Thread ID, Return %, Buy & Hold %, Max Drawdown %, 
        # Sharpe Ratio, Sortino Ratio, Exposure %, EV %, Trades, File Path, Data, Time
        
        if df.empty:
            cprint("📭 Backtest stats CSV is empty", "yellow")
            return pd.DataFrame()
        
        # Rename columns for easier access
        column_map = {
            'Strategy Name': 'strategy_name',
            'Return %': 'return_pct',
            'Sharpe Ratio': 'sharpe',
            'Sortino Ratio': 'sortino',
            'Max Drawdown %': 'max_drawdown',
            'Trades': 'trades',
            'EV %': 'expectancy',
            'Exposure %': 'exposure',
            'Time': 'timestamp',
            'Data': 'data_source'
        }
        
        df = df.rename(columns=column_map)
        
        # Convert numeric columns
        numeric_cols = ['return_pct', 'sharpe', 'sortino', 'max_drawdown', 'trades', 'expectancy', 'exposure']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # Filter by lookback period if timestamp column exists
        if 'timestamp' in df.columns:
            try:
                # Parse timestamp format "MM/DD HH:MM"
                current_year = datetime.now().year
                df['parsed_time'] = df['timestamp'].apply(
                    lambda x: datetime.strptime(f"{current_year}/{x}", "%Y/%m/%d %H:%M") 
                    if pd.notna(x) and '/' in str(x) else None
                )
                cutoff = datetime.now() - timedelta(days=lookback_days)
                df = df[df['parsed_time'].notna() & (df['parsed_time'] >= cutoff)]
            except Exception as e:
                cprint(f"⚠️ Could not filter by date: {e}", "yellow")
        
        cprint(f"📊 Loaded {len(df)} backtest results from CSV", "cyan")
        return df
        
    except Exception as e:
        cprint(f"❌ Error parsing backtest stats: {e}", "red")
        return pd.DataFrame()


def parse_feedback_results(lookback_days: int = 30) -> pd.DataFrame:
    """
    v6.5 - Parse the new feedback_results.csv (logged by RBI agent).
    
    This is the PRIMARY data source for technique learning.
    Columns: timestamp, strategy_name, technique, return_pct, sharpe, trades, success
    """
    if not FEEDBACK_RESULTS_CSV.exists():
        cprint(f"⚠️ Feedback results CSV not found: {FEEDBACK_RESULTS_CSV}", "yellow")
        return pd.DataFrame()
    
    try:
        df = pd.read_csv(FEEDBACK_RESULTS_CSV)
        
        if df.empty:
            cprint("📭 Feedback results CSV is empty", "yellow")
            return pd.DataFrame()
        
        # Convert numeric columns
        numeric_cols = ['return_pct', 'sharpe', 'trades']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # Filter by lookback period
        if 'timestamp' in df.columns:
            try:
                df['parsed_time'] = pd.to_datetime(df['timestamp'], errors='coerce')
                cutoff = datetime.now() - timedelta(days=lookback_days)
                df = df[df['parsed_time'].notna() & (df['parsed_time'] >= cutoff)]
            except Exception as e:
                cprint(f"⚠️ Could not filter by date: {e}", "yellow")
        
        cprint(f"📊 Loaded {len(df)} feedback results from CSV", "cyan")
        return df
        
    except Exception as e:
        cprint(f"❌ Error parsing feedback results: {e}", "red")
        return pd.DataFrame()


def cleanup_old_feedback_results(days_to_keep: int = 30) -> int:
    """
    v6.5 - Remove feedback results older than N days to keep CSV from growing too large.
    Returns number of rows removed.
    """
    if not FEEDBACK_RESULTS_CSV.exists():
        return 0
    
    try:
        df = pd.read_csv(FEEDBACK_RESULTS_CSV)
        original_len = len(df)
        
        if 'timestamp' in df.columns:
            df['parsed_time'] = pd.to_datetime(df['timestamp'], errors='coerce')
            cutoff = datetime.now() - timedelta(days=days_to_keep)
            df = df[df['parsed_time'].notna() & (df['parsed_time'] >= cutoff)]
            df = df.drop(columns=['parsed_time'], errors='ignore')
            
            # Save cleaned data
            df.to_csv(FEEDBACK_RESULTS_CSV, index=False)
            
            removed = original_len - len(df)
            if removed > 0:
                cprint(f"🧹 Cleaned up {removed} old feedback results", "yellow")
            return removed
    except Exception as e:
        cprint(f"⚠️ Cleanup error: {e}", "yellow")
    return 0


def load_scalping_ideas() -> pd.DataFrame:
    """
    Load scalping_ideas.csv to map strategies to techniques.
    
    Columns: timestamp, model, idea, consensus_score, status, novelty_score, technique
    """
    if not SCALPING_IDEAS_CSV.exists():
        cprint(f"⚠️ Scalping ideas CSV not found: {SCALPING_IDEAS_CSV}", "yellow")
        return pd.DataFrame()
    
    try:
        df = pd.read_csv(SCALPING_IDEAS_CSV)
        cprint(f"📋 Loaded {len(df)} scalping ideas", "cyan")
        return df
    except Exception as e:
        cprint(f"❌ Error loading scalping ideas: {e}", "red")
        return pd.DataFrame()


# ============================================
# 🔗 TECHNIQUE MATCHING
# ============================================

def match_strategy_to_technique(strategy_name: str, ideas_df: pd.DataFrame) -> Optional[str]:
    """
    Match a strategy name from backtest results to its technique.
    
    Strategy names in backtest results are derived from the idea text.
    We try to find the matching row in scalping_ideas.csv by:
    1. Direct match on idea text containing the strategy name
    2. Fuzzy matching on key terms
    """
    if ideas_df.empty or 'idea' not in ideas_df.columns or 'technique' not in ideas_df.columns:
        return None
    
    # Clean strategy name for matching
    clean_name = strategy_name.lower().strip()
    
    # Try to find matching idea
    for idx, row in ideas_df.iterrows():
        idea = str(row.get('idea', '')).lower()
        
        # Direct substring match
        if clean_name in idea or idea in clean_name:
            technique = row.get('technique')
            if pd.notna(technique):
                return technique
    
    # Try fuzzy match - extract key terms from strategy name
    # E.g., "VWAPBounce" → look for ideas with "VWAP" and "Bounce"
    name_parts = re.findall(r'[A-Z][a-z]+|[a-z]+', strategy_name)
    if name_parts:
        for idx, row in ideas_df.iterrows():
            idea = str(row.get('idea', '')).lower()
            matches = sum(1 for part in name_parts if part.lower() in idea)
            if matches >= len(name_parts) * 0.6:  # 60% match threshold
                technique = row.get('technique')
                if pd.notna(technique):
                    return technique
    
    return None


def build_strategy_technique_map(backtest_df: pd.DataFrame, ideas_df: pd.DataFrame) -> Dict[str, str]:
    """
    Build a mapping of strategy names to techniques.
    
    Returns dict: {strategy_name: technique_name}
    """
    mapping = {}
    
    if backtest_df.empty or ideas_df.empty:
        return mapping
    
    unique_strategies = backtest_df['strategy_name'].unique()
    
    for strategy in unique_strategies:
        if pd.isna(strategy):
            continue
        technique = match_strategy_to_technique(str(strategy), ideas_df)
        if technique:
            mapping[str(strategy)] = technique
    
    cprint(f"🔗 Matched {len(mapping)}/{len(unique_strategies)} strategies to techniques", "cyan")
    return mapping


# ============================================
# 📈 PERFORMANCE TRACKING
# ============================================

def load_technique_performance() -> dict:
    """Load existing technique performance data"""
    if TECHNIQUE_PERFORMANCE_FILE.exists():
        try:
            with open(TECHNIQUE_PERFORMANCE_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            cprint(f"⚠️ Error loading technique performance: {e}", "yellow")
    return {}


def save_technique_performance(performance: dict) -> None:
    """Save technique performance data"""
    try:
        TECHNIQUE_PERFORMANCE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(TECHNIQUE_PERFORMANCE_FILE, 'w') as f:
            json.dump(performance, f, indent=2)
        cprint("💾 Technique performance saved", "green")
    except Exception as e:
        cprint(f"❌ Error saving technique performance: {e}", "red")


def update_technique_performance(technique_name: str, return_pct: float, 
                                  sharpe: Optional[float] = None,
                                  trades: Optional[int] = None) -> dict:
    """
    Update performance metrics for a technique after receiving backtest results.
    
    Args:
        technique_name: Name of the technique
        return_pct: Return percentage from backtest
        sharpe: Sharpe ratio (optional)
        trades: Number of trades (optional)
    
    Returns:
        Updated performance dict for this technique
    """
    perf = load_technique_performance()
    
    if technique_name not in perf:
        perf[technique_name] = {
            'attempts': 0,
            'successes': 0,
            'total_return': 0.0,
            'returns': [],
            'sharpes': [],
            'avg_return': 0.0,
            'avg_sharpe': 1.0,
            'win_rate': 0.5,
            'last_updated': None
        }
    
    tech_perf = perf[technique_name]
    tech_perf['attempts'] += 1
    tech_perf['returns'].append(return_pct)
    tech_perf['total_return'] += return_pct
    
    if return_pct > 0:
        tech_perf['successes'] += 1
    
    if sharpe is not None and not pd.isna(sharpe):
        tech_perf['sharpes'].append(sharpe)
    
    # Keep only last 20 results for recency
    tech_perf['returns'] = tech_perf['returns'][-20:]
    tech_perf['sharpes'] = tech_perf['sharpes'][-20:]
    
    # Calculate rolling averages
    if tech_perf['returns']:
        tech_perf['avg_return'] = sum(tech_perf['returns']) / len(tech_perf['returns'])
    tech_perf['win_rate'] = tech_perf['successes'] / tech_perf['attempts'] if tech_perf['attempts'] > 0 else 0.5
    
    if tech_perf['sharpes']:
        tech_perf['avg_sharpe'] = sum(tech_perf['sharpes']) / len(tech_perf['sharpes'])
    
    tech_perf['last_updated'] = datetime.now().isoformat()
    
    save_technique_performance(perf)
    return tech_perf


# ============================================
# 🔄 MAIN SYNC FUNCTION
# ============================================

def get_last_sync_time() -> Optional[datetime]:
    """Get the timestamp of the last successful sync"""
    if FEEDBACK_HISTORY_FILE.exists():
        try:
            with open(FEEDBACK_HISTORY_FILE, 'r') as f:
                history = json.load(f)
                if history.get('last_sync'):
                    return datetime.fromisoformat(history['last_sync'])
        except:
            pass
    return None


def save_sync_history(results_processed: int, techniques_updated: int) -> None:
    """Save sync history for tracking"""
    history = {
        'last_sync': datetime.now().isoformat(),
        'results_processed': results_processed,
        'techniques_updated': techniques_updated
    }
    
    try:
        FEEDBACK_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(FEEDBACK_HISTORY_FILE, 'w') as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        cprint(f"⚠️ Error saving sync history: {e}", "yellow")


def process_new_results() -> Dict[str, any]:
    """
    Main entry point: Process new backtest results and update technique performance.
    
    v6.5 - Now reads from feedback_results.csv (already has technique column)
    
    Returns:
        Summary dict with stats about what was processed
    """
    cprint("\n" + "=" * 60, "cyan")
    cprint("🌙 TradeHive's Feedback Loop - Processing Results", "white", "on_blue")
    cprint("=" * 60, "cyan")
    
    config = load_feedback_config()
    
    # Cleanup old results first
    cleanup_old_feedback_results(config['lookback_days'])
    
    # Load feedback results (v6.5 - primary source with technique column)
    feedback_df = parse_feedback_results(config['lookback_days'])
    
    if feedback_df.empty:
        cprint("📭 No feedback results to process", "yellow")
        return {'status': 'no_data', 'results_processed': 0}
    
    # Track updates
    results_processed = 0
    techniques_updated = set()
    technique_results = {}  # {technique: [list of results]}
    
    # Process each feedback result (already has technique!)
    for idx, row in feedback_df.iterrows():
        strategy_name = str(row.get('strategy_name', ''))
        technique = str(row.get('technique', ''))
        return_pct = row.get('return_pct', 0)
        sharpe = row.get('sharpe')
        trades = row.get('trades')
        
        if not technique or technique == 'unknown' or pd.isna(technique):
            continue
        
        if pd.isna(return_pct):
            continue
        
        # Update technique performance
        update_technique_performance(technique, return_pct, sharpe, trades)
        techniques_updated.add(technique)
        
        # Track for summary
        if technique not in technique_results:
            technique_results[technique] = []
        technique_results[technique].append({
            'return': return_pct,
            'sharpe': sharpe,
            'trades': trades
        })
        
        results_processed += 1
        
        if results_processed >= config['max_results_per_sync']:
            cprint(f"⚠️ Reached max results limit ({config['max_results_per_sync']})", "yellow")
            break
    
    # Save sync history
    save_sync_history(results_processed, len(techniques_updated))
    
    # Generate summary
    summary = {
        'status': 'success',
        'results_processed': results_processed,
        'techniques_updated': len(techniques_updated),
        'technique_list': list(techniques_updated),
        'timestamp': datetime.now().isoformat()
    }
    
    cprint(f"\n✅ Processed {results_processed} results, updated {len(techniques_updated)} techniques", "green")
    
    return summary


# ============================================
# 📊 INSIGHTS GENERATION
# ============================================

def generate_performance_insights() -> Dict[str, any]:
    """
    Generate insights about technique performance for prompt injection.
    
    Returns dict with:
    - top_performers: List of (technique, win_rate, avg_return)
    - underperformers: List of (technique, win_rate, avg_return)
    - recommendations: List of strings
    """
    config = load_feedback_config()
    perf = load_technique_performance()
    
    if not perf:
        return {
            'top_performers': [],
            'underperformers': [],
            'recommendations': ["No performance data yet - keep generating strategies!"]
        }
    
    # Analyze each technique
    analyzed = []
    for technique, data in perf.items():
        if data.get('attempts', 0) >= config['min_trades_for_significance']:
            analyzed.append({
                'technique': technique,
                'win_rate': data.get('win_rate', 0.5),
                'avg_return': data.get('avg_return', 0),
                'avg_sharpe': data.get('avg_sharpe', 1.0),
                'attempts': data.get('attempts', 0)
            })
    
    # Sort by win rate
    analyzed.sort(key=lambda x: x['win_rate'], reverse=True)
    
    # Get top and bottom performers
    top_performers = [t for t in analyzed if t['win_rate'] >= config['top_performer_threshold']][:5]
    underperformers = [t for t in analyzed if t['win_rate'] < config['underperformer_threshold']][:5]
    
    # Generate recommendations
    recommendations = []
    if top_performers:
        best = top_performers[0]
        recommendations.append(f"🏆 {best['technique']} is your top performer ({best['win_rate']*100:.0f}% win rate)")
    
    if underperformers:
        worst = underperformers[-1]
        recommendations.append(f"⚠️ {worst['technique']} needs refinement ({worst['win_rate']*100:.0f}% win rate)")
    
    return {
        'top_performers': top_performers,
        'underperformers': underperformers,
        'recommendations': recommendations,
        'total_techniques_tracked': len(perf),
        'techniques_with_data': len(analyzed)
    }


def format_insights_for_prompt() -> str:
    """
    Format performance insights as a string to inject into strategy generation prompts.
    """
    insights = generate_performance_insights()
    
    if not insights['top_performers'] and not insights['underperformers']:
        return ""
    
    lines = ["\n📊 PERFORMANCE FEEDBACK FROM BACKTESTS:"]
    
    if insights['top_performers']:
        lines.append("\n🏆 TOP PERFORMERS (generate more of these!):")
        for t in insights['top_performers'][:3]:
            lines.append(f"  • {t['technique']}: {t['win_rate']*100:.0f}% win rate, avg +{t['avg_return']:.1f}%")
    
    if insights['underperformers']:
        lines.append("\n📉 UNDERPERFORMERS (try different parameters):")
        for t in insights['underperformers'][:3]:
            lines.append(f"  • {t['technique']}: {t['win_rate']*100:.0f}% win rate, avg {t['avg_return']:.1f}%")
    
    lines.append("")
    return "\n".join(lines)


# ============================================
# 📈 DASHBOARD DATA GENERATION
# ============================================

def generate_dashboard_data() -> dict:
    """
    Generate data for the feedback dashboard.
    
    Returns comprehensive data structure for visualization.
    """
    perf = load_technique_performance()
    config = load_feedback_config()
    insights = generate_performance_insights()
    
    # Build technique list with all stats
    techniques = []
    for technique, data in perf.items():
        techniques.append({
            'name': technique,
            'win_rate': round(data.get('win_rate', 0.5) * 100, 1),
            'avg_return': round(data.get('avg_return', 0), 2),
            'avg_sharpe': round(data.get('avg_sharpe', 1.0), 2),
            'attempts': data.get('attempts', 0),
            'successes': data.get('successes', 0),
            'recent_returns': data.get('returns', [])[-10:],  # Last 10 returns
            'last_updated': data.get('last_updated'),
            'status': 'top' if data.get('win_rate', 0.5) >= config['top_performer_threshold'] 
                     else ('under' if data.get('win_rate', 0.5) < config['underperformer_threshold'] else 'normal')
        })
    
    # Sort by attempts (most tested first)
    techniques.sort(key=lambda x: x['attempts'], reverse=True)
    
    # Calculate summary stats
    total_attempts = sum(t['attempts'] for t in techniques)
    total_successes = sum(t['successes'] for t in techniques)
    overall_win_rate = (total_successes / total_attempts * 100) if total_attempts > 0 else 50
    
    dashboard_data = {
        'generated_at': datetime.now().isoformat(),
        'summary': {
            'total_techniques': len(techniques),
            'total_backtests': total_attempts,
            'overall_win_rate': round(overall_win_rate, 1),
            'top_performers_count': len(insights['top_performers']),
            'underperformers_count': len(insights['underperformers'])
        },
        'techniques': techniques,
        'top_performers': insights['top_performers'],
        'underperformers': insights['underperformers'],
        'recommendations': insights['recommendations'],
        'config': config
    }
    
    # Save dashboard data
    try:
        DASHBOARD_DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(DASHBOARD_DATA_FILE, 'w') as f:
            json.dump(dashboard_data, f, indent=2)
        cprint(f"📊 Dashboard data saved to {DASHBOARD_DATA_FILE}", "green")
    except Exception as e:
        cprint(f"❌ Error saving dashboard data: {e}", "red")
    
    return dashboard_data


# ============================================
# 🚀 CLI INTERFACE
# ============================================

def main():
    """Command-line interface for the feedback connector"""
    import argparse
    
    parser = argparse.ArgumentParser(description="TradeHive's Feedback Connector 🌙")
    parser.add_argument('--sync', action='store_true', help='Process new backtest results')
    parser.add_argument('--insights', action='store_true', help='Show performance insights')
    parser.add_argument('--dashboard', action='store_true', help='Generate dashboard data')
    parser.add_argument('--all', action='store_true', help='Run sync + insights + dashboard')
    
    args = parser.parse_args()
    
    if args.all or (not any([args.sync, args.insights, args.dashboard])):
        # Default: run everything
        process_new_results()
        insights = generate_performance_insights()
        print("\n📊 Performance Insights:")
        print(format_insights_for_prompt())
        generate_dashboard_data()
    else:
        if args.sync:
            process_new_results()
        if args.insights:
            print(format_insights_for_prompt())
        if args.dashboard:
            generate_dashboard_data()


if __name__ == "__main__":
    main()
