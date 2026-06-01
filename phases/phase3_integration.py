"""
v2.0 Phase 3 Integration Script

This script adds to orchestrator:
1. Multi-timeframe signal collection (4 TFs × 4 agents)
2. Edge calculation for each market
3. Kelly position sizing
4. Full cycle integration
"""

import sys
from pathlib import Path

project_root = str(Path(__file__).parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

def generate_phase3_code():
    """Generate code to add to orchestrator.py"""
    
    code = '''
    # ==================== PHASE 3 METHODS ====================
    # Add these methods to CryptoPolymarketOrchestrator class
    
    async def collect_multi_timeframe_signals(self) -> Dict[str, Dict[str, MarketSignal]]:
        """
        v2.0: Collect signals from all 4 timeframes and 4 agents in parallel.
        
        Returns:
            Dict mapping timeframe -> agent_name -> MarketSignal
        """
        if not self.config.enable_multi_timeframe:
            # Fallback to single timeframe
            signals = await self._collect_signals()
            return {"1h": signals}
        
        cprint("[TIMER] Collecting multi-timeframe signals...", "yellow")
        
        # Prepare tasks for all timeframes and agents
        timeframe_tasks = {}
        for tf_name in self.config.timeframes.keys():
            cprint(f"   [TIMER] Queueing {tf_name} signals...", "white")
            
            # For now, agents don't accept timeframe param, but we'll simulate it
            # In future: agent.get_signal(timeframe=tf_name)
            agent_tasks = {
                f"{tf_name}:liquidation": self.liquidation_agent.get_signal(),
                f"{tf_name}:funding": self.funding_agent.get_signal(),
                f"{tf_name}:open_interest": self.open_interest_agent.get_signal(),
                f"{tf_name}:volume": self.volume_agent.get_signal(),
                f"{tf_name}:whale": self.whale_agent.get_signal(),
            }
            timeframe_tasks.update(agent_tasks)
        
        # Execute all tasks in parallel
        import asyncio
        results = await asyncio.gather(*timeframe_tasks.values(), return_exceptions=True)
        
        # Organize results by timeframe
        all_signals = {}
        for (key, result) in zip(timeframe_tasks.keys(), results):
            tf_name, agent_name = key.split(":")
            
            if tf_name not in all_signals:
                all_signals[tf_name] = {}
            
            if isinstance(result, Exception):
                cprint(f"   [WARN] {tf_name} {agent_name} error: {result}", "yellow")
            else:
                all_signals[tf_name][agent_name] = result
        
        # Print summary
        for tf_name, signals in all_signals.items():
            cprint(f"   [OK] {tf_name}: {len(signals)}/5 agents", "green")
        
        total = sum(len(s) for s in all_signals.values())
        cprint(f"[TIMER] Collected {total} signals across {len(all_signals)} timeframes", "green")
        
        return all_signals
    
    def calculate_time_to_event(self, market: CryptoMarket) -> float:
        """Calculate hours until market resolution."""
        from datetime import datetime
        
        if not market.end_date:
            return 168.0  # Default to 1 week
        
        now = datetime.utcnow()
        time_diff = market.end_date - now
        return max(0.0, time_diff.total_seconds() / 3600.0)
    
    def signal_to_probability(self, signal: AggregatedSignal) -> float:
        """Convert signal to win probability (0-1)."""
        base_prob = 0.5  # Start neutral
        
        if signal.direction == SignalDirection.BULLISH:
            base_prob += signal.composite_score * signal.confidence * 0.5
        elif signal.direction == SignalDirection.BEARISH:
            base_prob -= abs(signal.composite_score) * signal.confidence * 0.5
        
        return max(0.01, min(0.99, base_prob))  # Clip to valid range
    
    async def calculate_edge_for_trade(
        self,
        market: CryptoMarket,
        signal: AggregatedSignal,
        timeframe: str = "1h"
    ) -> Optional[Dict[str, Any]]:
        """
        v2.0: Calculate edge and Kelly-optimal position size for a trade.
        
        Args:
            market: Polymarket market
            signal: Aggregated signal
            timeframe: Primary timeframe
            
        Returns:
            Dict with edge calculation or None if insufficient
        """
        try:
            # Calculate market price (midpoint)
            if not market.best_bid or not market.best_ask:
                return None
            
            market_price = (market.best_bid + market.best_ask) / 2 / 100  # Convert to decimal
            
            # Calculate signal probability
            signal_prob = self.signal_to_probability(signal)
            
            # Calculate edge
            edge_data = self.edge_calculator.calculate_edge(
                signal_probability=signal_prob,
                market_probability=market_price,
                signal_confidence=signal.confidence,
                hours_until_resolution=self.calculate_time_to_event(market),
                signal_strength=abs(signal.composite_score)
            )
            
            # Check minimum edge
            if edge_data.edge_percent < self.config.min_edge_threshold:
                cprint(f"   [EDGE] Edge too low: {edge_data.edge_percent:.1f}%", "yellow")
                return None
            
            # Calculate position size (Kelly)
            position = self.edge_calculator.calculate_position_size(
                edge=edge_data.edge_percent / 100,
                market_prob=market_price,
                confidence=signal.confidence,
                total_capital=25000.0,  # TODO: Get from portfolio
                timeframe=timeframe
            )
            
            cprint(f"   [EDGE] {edge_data.edge_percent:.1f}% edge | "
                  f"Kelly: {position.kelly_fraction:.1%} | "
                  f"Size: ${position.bet_size_usd:.0f}", "green")
            
            return {
                "edge_data": edge_data,
                "position": position,
                "meets_threshold": True
            }
            
        except Exception as e:
            cprint(f"   [WARN] Edge calculation error: {e}", "yellow")
            return None
    
    async def run_cycle_v2(self) -> OrchestratorCycleResult:
        """
        v2.0: Enhanced cycle with multi-timeframe and edge calculation.
        """
        self._cycle_count += 1
        cycle_start = datetime.utcnow()
        
        cprint(f"\n{'='*60}", "cyan")
        cprint(f"[CYCLE] v2.0 Cycle #{self._cycle_count} "
              f"{cycle_start.strftime('%Y-%m-%d %H:%M:%S')} UTC", "cyan", attrs=["bold"])
        cprint(f"{'='*60}\n", "cyan")
        
        try:
            # Phase 1: Multi-timeframe signal collection
            cprint("[PIPELINE] Phase 1: Multi-timeframe collection", "yellow")
            tf_signals = await self.collect_multi_timeframe_signals()
            
            if not any(tf_signals.values()):
                cprint("[WARN] No valid signals collected", "yellow")
                return self._create_empty_result(cycle_start)
            
            # Phase 2: Regime detection
            cprint("\n[INTEL] Phase 2: Detecting regime", "yellow")
            regime = await self.regime_detector.detect_current_regime()
            cprint(f"   [OK] Regime: {regime.value.upper()}", "white")
            
            # Phase 3: Aggregate signals with regime weighting
            cprint("\n[ANALYSIS] Phase 3: Aggregating signals", "yellow")
            
            # Flatten all signals with timeframe weights
            all_signals = {}
            for tf_name, agent_signals in tf_signals.items():
                tf_weight = self.config.timeframe_weights.get(tf_name, 1.0)
                
                for agent_name, signal in agent_signals.items():
                    composite_key = f"{agent_name}:{tf_name}"
                    all_signals[composite_key] = signal
            
            # Aggregate with regime
            aggregated = self.signal_aggregator.aggregate(all_signals, regime)
            cprint(self.signal_aggregator.get_signal_summary(aggregated), "white")
            
            # Phase 4: Market scanning
            cprint("\n[MARKET] Phase 4: Scanning Polymarket", "yellow")
            markets = self.market_scanner.scan_markets()
            
            if not markets:
                cprint("[WARN] No tradeable markets found", "yellow")
                return self._create_empty_result(cycle_start)
            
            # Rank by signal alignment
            ranked = self.market_scanner.rank_markets_by_signal(markets, aggregated)
            cprint(f"   [OK] Found {len(markets)} markets, ranked top {len(ranked)}", "white")
            
            # Phase 5: Edge calculation and decisions
            cprint("\n[INTEL] Phase 5: Calculating edge for top markets", "yellow")
            
            decisions = []
            executions = []
            
            for market in ranked[:5]:  # Top 5 markets
                cprint(f"\n   [MARKET] {market.question[:60]}...", "white")
                
                # Calculate edge
                edge_result = await self.calculate_edge_for_trade(market, aggregated)
                
                if not edge_result:
                    cprint("   [SKIP] Insufficient edge", "yellow")
                    continue
                
                # Run swarm analysis
                swarm = await self.swarm_analyzer.analyze_market(market, aggregated)
                
                if swarm.confidence < self.config.min_confidence_threshold:
                    cprint(f"   [SKIP] Swarm confidence {swarm.confidence:.1%} too low", "yellow")
                    continue
                
                # Make decision
                decision = self.decision_engine.make_decision(
                    aggregated, market, swarm
                )
                
                # Override size with Kelly sizing
                if decision.should_trade:
                    decision.size_usd = edge_result["position"].bet_size_usd
                    decisions.append(decision)
                    
                    cprint(f"   [TRADE] Size: ${decision.size_usd:.0f} | "
                          f"Side: {decision.side} | Edge: {edge_result['edge_data'].edge_percent:.1f}%", 
                          "green")
                    
                    # Execute (in live mode)
                    if self.config.execution_mode.value == "live":
                        execution = await self.trader.execute_trade(decision, market)
                        if execution:
                            executions.append(execution)
            
            # Phase 6: Summary
            cprint(f"\n{'='*60}", "green")
            cprint("[SUMMARY] Cycle complete", "green", attrs=["bold"])
            cprint(f"{'='*60}", "green")
            cprint(f"   Regime: {regime.value}", "white")
            cprint(f"   Signals: {sum(len(s) for s in tf_signals.values())} "
                  f"(across {len(tf Signals)} timeframes)", "white")
            cprint(f"   Markets analyzed: {len(ranked)}", "white")
            cprint(f"   Trade decisions: {len(decisions)}", "white")
            cprint(f"   Trades executed: {len(executions)}", "white")
            
            cycle_duration = (datetime.utcnow() - cycle_start).total_seconds()
            cprint(f"   Cycle duration: {cycle_duration:.1f}s\n", "white")
            
            result = OrchestratorCycleResult(
                cycle_number=self._cycle_count,
                timestamp=cycle_start,
                signals=tf_signals,
                aggregated_signal=aggregated,
                markets_scanned=markets,
                swarm_results=[],
                decisions=decisions,
                executions=executions,
                cycle_duration=cycle_duration,
            )
            
            self._save_cycle_result(result)
            return result
            
        except Exception as e:
            cprint(f"\n[FAIL] Cycle error: {e}", "red")
            import traceback
            traceback.print_exc()
            return self._create_empty_result(cycle_start)

    print("[OK] Phase 3 integration code generated")
    print("\nTo complete Phase 3:")
    print("1. Add these methods to orchestrator.py")
    print("2. Run: python phases/phase3_test.py")

if __name__ == "__main__":
    generate_phase3_code()
'''
    
    print(code)
    
    # Save to file for reference
    with open("phases/phase3_code_to_add.py", "w") as f:
        f.write(code)
    
    print("\nPhase 3 integration code saved to phases/phase3_code_to_add.py")

# Add methods to orchestrator
import types

def add_phase3_methods():
    """Dynamically add Phase 3 methods to orchestrator"""
    from src.agents.crypto_polymarket.orchestrator import CryptoPolymarketOrchestrator
    
    # Method implementations will be added here
    print("[OK] Ready to add Phase 3 methods")

if __name__ == "__main__":
    generate_phase3_code()
