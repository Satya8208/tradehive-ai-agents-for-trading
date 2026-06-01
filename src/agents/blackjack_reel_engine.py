"""
Blackjack God reel machine helper.
"""

from __future__ import annotations

import json
import math
import random
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from termcolor import cprint

from src.prompts.blackjack.reels import (
    BLACKJACK_REEL_CONSTITUTION,
    CONTENT_PILLARS,
    REEL_CONCEPT_GENERATOR_PROMPT,
    REEL_CONCEPT_OUTPUT_SCHEMA,
    REEL_PACKET_GENERATOR_PROMPT,
    REEL_PACKET_OUTPUT_SCHEMA,
    REEL_SCORER_PROMPT,
    REEL_SERIES,
    SOURCE_LANES,
)


class BlackjackReelEngine:
    """Production-oriented reel generation for Blackjack God."""

    def __init__(self, model, data_dir: Path):
        self.model = model
        self.data_dir = data_dir
        self.concept_bank_dir = data_dir / "concept_bank"
        self.approved_packets_dir = data_dir / "approved_reel_packets"
        self.rejected_packets_dir = data_dir / "rejected_reel_packets"
        self.calendars_dir = data_dir / "weekly_content_calendars"

        for directory in [
            self.concept_bank_dir,
            self.approved_packets_dir,
            self.rejected_packets_dir,
            self.calendars_dir,
        ]:
            directory.mkdir(parents=True, exist_ok=True)

    def generate_reel_concepts(
        self,
        count: int = 10,
        focus_mode: str = "mixed",
        topic: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate JSON-first reel concepts."""
        count = max(1, count)
        focus_mode = (focus_mode or "mixed").lower()
        seed_bundle = self._select_seed_bundle(count, focus_mode, topic)

        prompt = REEL_CONCEPT_GENERATOR_PROMPT.format(
            constitution=BLACKJACK_REEL_CONSTITUTION,
            pillar_library=self._render_library(CONTENT_PILLARS),
            series_library=self._render_library(REEL_SERIES),
            source_lane_library=self._render_source_lanes(),
            focus_mode=focus_mode,
            topic=topic or "None",
            count=count,
            selected_seeds=self._render_selected_seeds(seed_bundle),
            output_schema=REEL_CONCEPT_OUTPUT_SCHEMA,
        )

        concepts = self._generate_json(
            system_prompt="You are generating structured reel concepts. Return only valid JSON.",
            user_content=prompt,
            temperature=0.9,
            max_tokens=3000,
            expect="list",
        )

        normalized = []
        for index, concept in enumerate(concepts[:count], start=1):
            normalized.append(
                self._normalize_concept(
                    concept=concept,
                    index=index,
                    focus_mode=focus_mode,
                    topic=topic,
                )
            )

        payload = {
            "generated_at": datetime.now().isoformat(),
            "focus_mode": focus_mode,
            "topic": topic,
            "count": len(normalized),
            "selected_seeds": seed_bundle,
            "concepts": normalized,
        }

        self._save_json(
            self.concept_bank_dir / f"concepts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            payload,
        )
        self._print_concept_summary(normalized, focus_mode)
        return payload

    def generate_reel_packet(
        self,
        concept_input: Any,
        series_name: Optional[str] = None,
        pillar: Optional[str] = None,
        duration_seconds: int = 35,
        auto_score: bool = True,
    ) -> Dict[str, Any]:
        """Generate a production-ready reel packet and route it through the quality gate."""
        concept = self._coerce_concept_input(concept_input, series_name, pillar)
        duration_seconds = max(20, min(duration_seconds, 60))

        prompt = REEL_PACKET_GENERATOR_PROMPT.format(
            constitution=BLACKJACK_REEL_CONSTITUTION,
            pillar_library=self._render_library(CONTENT_PILLARS),
            series_library=self._render_library(REEL_SERIES),
            concept_json=json.dumps(concept, indent=2),
            duration_seconds=duration_seconds,
            output_schema=REEL_PACKET_OUTPUT_SCHEMA,
        )

        packet = self._generate_json(
            system_prompt="You are generating a reel packet. Return only valid JSON.",
            user_content=prompt,
            temperature=0.82,
            max_tokens=3200,
            expect="dict",
        )
        packet = self._normalize_packet(packet, concept, duration_seconds)

        score = self.score_reel_packet(packet) if auto_score else None
        bundle = {
            "generated_at": datetime.now().isoformat(),
            "concept": concept,
            "packet": packet,
            "quality_gate": score,
        }

        packet_slug = self._slugify(
            packet.get("thumbnail_line") or packet.get("core_thesis") or concept.get("title", "reel")
        )
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        approved = score.get("approved", False) if score else True
        destination = self.approved_packets_dir if approved else self.rejected_packets_dir
        path = destination / f"reel_packet_{timestamp}_{packet_slug}.json"
        self._save_json(path, bundle)

        cprint(
            f"\n🎬 Reel packet {'approved' if approved else 'rejected'} and saved to: {path}",
            "green" if approved else "yellow",
        )
        if score:
            cprint(
                f"   Quality gate: {score.get('overall_score', 0)}/100 | {score.get('verdict', 'no verdict')}",
                "cyan",
            )
        return bundle

    def score_reel_packet(self, packet: Dict[str, Any]) -> Dict[str, Any]:
        """Run the anti-slop quality gate."""
        prompt = REEL_SCORER_PROMPT.format(
            constitution=BLACKJACK_REEL_CONSTITUTION,
            packet_json=json.dumps(packet, indent=2),
        )
        score = self._generate_json(
            system_prompt="You are scoring a reel packet. Return only valid JSON.",
            user_content=prompt,
            temperature=0.25,
            max_tokens=1800,
            expect="dict",
        )

        component_scores = score.get("component_scores", {})
        normalized_components = {}
        for key in [
            "bookmark_test",
            "quote_test",
            "visual_test",
            "specificity_test",
            "persona_test",
            "repetition_test",
        ]:
            raw_value = component_scores.get(key, 0)
            normalized_components[key] = self._clamp_score(raw_value)

        if normalized_components:
            average_score = sum(normalized_components.values()) / len(normalized_components)
            overall_score = int(round(score.get("overall_score", average_score * 10)))
        else:
            overall_score = int(round(score.get("overall_score", 0)))

        hard_fail = (
            normalized_components.get("specificity_test", 10) < 6
            or normalized_components.get("persona_test", 10) < 6
            or normalized_components.get("visual_test", 10) < 5
        )

        approved = bool(score.get("approved", False))
        approved = approved and overall_score >= 78 and not hard_fail

        result = {
            "approved": approved,
            "overall_score": overall_score,
            "component_scores": normalized_components,
            "standout_line": score.get("standout_line", ""),
            "slop_risks": self._normalize_list(score.get("slop_risks", [])),
            "fixes": self._normalize_list(score.get("fixes", [])),
            "verdict": score.get("verdict", "no verdict returned"),
        }
        return result

    def generate_batch_calendar(
        self,
        week_start: Optional[str] = None,
        mix: str = "mixed",
    ) -> Dict[str, Any]:
        """Generate a weekly concept calendar using the requested content mix."""
        mix = (mix or "mixed").lower()
        start_date = self._parse_week_start(week_start)
        concepts = self._build_calendar_concepts(mix)
        slots = self._build_calendar_slots(start_date, len(concepts), mix)

        calendar_entries = []
        for slot, concept in zip(slots, concepts):
            calendar_entries.append(
                {
                    "date": slot["date"],
                    "publish_time": slot["publish_time"],
                    "slot_label": slot["slot_label"],
                    "focus": slot["focus"],
                    "concept_id": concept["concept_id"],
                    "title": concept["title"],
                    "pillar": concept["pillar"],
                    "series_name": concept["series_name"],
                    "core_thesis": concept["core_thesis"],
                    "mood": concept["mood"],
                }
            )

        payload = {
            "generated_at": datetime.now().isoformat(),
            "week_start": start_date.isoformat(),
            "mix": mix,
            "item_count": len(calendar_entries),
            "calendar": calendar_entries,
        }

        path = self.calendars_dir / f"week_{start_date.strftime('%Y%m%d')}_{mix}.json"
        self._save_json(path, payload)
        cprint(f"\n🗓️ Saved weekly content calendar to: {path}", "green")
        return payload

    def _build_calendar_concepts(self, mix: str) -> List[Dict[str, Any]]:
        if mix == "evergreen":
            plan = {"evergreen": 10}
        elif mix == "reactive":
            plan = {"reactive": 8, "evergreen": 4, "literal": 2}
        elif mix == "literal":
            plan = {"literal": 8, "evergreen": 4}
        else:
            plan = {"evergreen": 10, "reactive": 3, "literal": 2}

        concepts: List[Dict[str, Any]] = []
        for focus_mode, count in plan.items():
            concepts.extend(self.generate_reel_concepts(count=count, focus_mode=focus_mode)["concepts"])

        if mix == "mixed":
            return self._arrange_mixed_calendar_concepts(concepts)
        return concepts

    def _arrange_mixed_calendar_concepts(self, concepts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        evergreen = [c for c in concepts if c.get("focus_mode") == "evergreen"]
        reactive = [c for c in concepts if c.get("focus_mode") == "reactive"]
        literal = [c for c in concepts if c.get("focus_mode") == "literal"]

        ordered = []
        template = [
            "evergreen", "evergreen",
            "evergreen", "reactive",
            "evergreen", "literal",
            "evergreen", "reactive",
            "evergreen", "evergreen",
            "evergreen", "literal",
            "evergreen", "reactive", "evergreen",
        ]

        buckets = {"evergreen": evergreen, "reactive": reactive, "literal": literal}
        for bucket_name in template:
            bucket = buckets[bucket_name]
            if bucket:
                ordered.append(bucket.pop(0))

        for leftovers in buckets.values():
            ordered.extend(leftovers)
        return ordered

    def _build_calendar_slots(self, start_date: date, total: int, mix: str) -> List[Dict[str, str]]:
        if mix == "mixed" and total >= 15:
            template = [
                (0, "09:30", "open", "evergreen"),
                (0, "18:30", "close", "evergreen"),
                (1, "09:30", "open", "evergreen"),
                (1, "18:30", "close", "reactive"),
                (2, "09:30", "open", "evergreen"),
                (2, "18:30", "close", "literal"),
                (3, "09:30", "open", "evergreen"),
                (3, "18:30", "close", "reactive"),
                (4, "09:30", "open", "evergreen"),
                (4, "18:30", "close", "evergreen"),
                (5, "10:00", "open", "evergreen"),
                (5, "19:00", "close", "literal"),
                (6, "10:00", "open", "evergreen"),
                (6, "14:00", "mid", "reactive"),
                (6, "19:00", "close", "evergreen"),
            ]
            return [
                {
                    "date": (start_date + timedelta(days=day_offset)).isoformat(),
                    "publish_time": publish_time,
                    "slot_label": slot_label,
                    "focus": focus,
                }
                for day_offset, publish_time, slot_label, focus in template[:total]
            ]

        slots = []
        windows = ["09:30", "13:00", "18:30"]
        for index in range(total):
            day_offset = index % 7
            slot_number = (index // 7) % len(windows)
            slots.append(
                {
                    "date": (start_date + timedelta(days=day_offset)).isoformat(),
                    "publish_time": windows[slot_number],
                    "slot_label": f"slot_{index + 1}",
                    "focus": mix,
                }
            )
        return slots

    def _coerce_concept_input(
        self,
        concept_input: Any,
        series_name: Optional[str],
        pillar: Optional[str],
    ) -> Dict[str, Any]:
        if isinstance(concept_input, dict):
            return self._normalize_concept(concept_input, 1, concept_input.get("focus_mode", "manual"), None)

        raw_text = str(concept_input).strip()
        series = series_name if series_name in REEL_SERIES else "Hidden Bet"
        chosen_pillar = pillar if pillar in CONTENT_PILLARS else REEL_SERIES[series]["pillar_fit"][0]
        return self._normalize_concept(
            {
                "title": raw_text,
                "pillar": chosen_pillar,
                "series_name": series,
                "source_lane": "manual_input",
                "core_thesis": raw_text,
                "hidden_bet": "",
                "asymmetry": "",
                "why_it_hits": "Manual idea expanded into a reel packet.",
                "mood": REEL_SERIES[series]["tone"].split(",")[0],
                "visual_angle": "cold casino lighting, trading screens, high-stakes restraint",
                "literal_blackjack_flavor": "Use only enough blackjack texture to sharpen the metaphor.",
                "novelty_score": 7,
                "slop_risks": [],
            },
            index=1,
            focus_mode="manual",
            topic=raw_text,
        )

    def _normalize_concept(
        self,
        concept: Dict[str, Any],
        index: int,
        focus_mode: str,
        topic: Optional[str],
    ) -> Dict[str, Any]:
        series_name = concept.get("series_name")
        if series_name not in REEL_SERIES:
            series_name = "Hidden Bet"

        pillar = concept.get("pillar")
        if pillar not in CONTENT_PILLARS:
            pillar = REEL_SERIES[series_name]["pillar_fit"][0]

        title = self._clean_text(concept.get("title")) or f"{series_name} concept {index}"
        normalized = {
            "concept_id": f"{focus_mode}_{index:02d}_{self._slugify(title)[:32]}",
            "focus_mode": focus_mode,
            "topic": topic,
            "title": title,
            "pillar": pillar,
            "series_name": series_name,
            "source_lane": concept.get("source_lane", self._default_source_lane_for_focus(focus_mode)),
            "core_thesis": self._clean_text(concept.get("core_thesis")) or title,
            "hidden_bet": self._clean_text(concept.get("hidden_bet")),
            "asymmetry": self._clean_text(concept.get("asymmetry")),
            "why_it_hits": self._clean_text(concept.get("why_it_hits")),
            "mood": self._clean_text(concept.get("mood")) or REEL_SERIES[series_name]["tone"].split(",")[0],
            "visual_angle": self._clean_text(concept.get("visual_angle")),
            "literal_blackjack_flavor": self._clean_text(concept.get("literal_blackjack_flavor")),
            "novelty_score": self._clamp_score(concept.get("novelty_score", 7)),
            "slop_risks": self._normalize_list(concept.get("slop_risks", [])),
        }
        return normalized

    def _normalize_packet(
        self,
        packet: Dict[str, Any],
        concept: Dict[str, Any],
        duration_seconds: int,
    ) -> Dict[str, Any]:
        series_name = packet.get("series_name")
        if series_name not in REEL_SERIES:
            series_name = concept["series_name"]

        pillar = packet.get("pillar")
        if pillar not in CONTENT_PILLARS:
            pillar = concept["pillar"]

        return {
            "series_name": series_name,
            "pillar": pillar,
            "core_thesis": self._clean_text(packet.get("core_thesis")) or concept["core_thesis"],
            "hook_1": self._clean_text(packet.get("hook_1")),
            "hook_2": self._clean_text(packet.get("hook_2")),
            "voiceover_script": self._clean_text(packet.get("voiceover_script")),
            "beat_sheet": self._normalize_list(packet.get("beat_sheet", []), limit=8),
            "broll_prompts": self._normalize_list(packet.get("broll_prompts", []), limit=8),
            "on_screen_text": self._normalize_list(packet.get("on_screen_text", []), limit=8),
            "caption": self._clean_text(packet.get("caption")),
            "thumbnail_line": self._clean_text(packet.get("thumbnail_line")),
            "cta_style": self._clean_text(packet.get("cta_style")),
            "mood": self._clean_text(packet.get("mood")) or concept["mood"],
            "novelty_score": self._clamp_score(packet.get("novelty_score", concept["novelty_score"])),
            "slop_risks": self._normalize_list(packet.get("slop_risks", [])),
            "target_duration_seconds": duration_seconds,
        }

    def _select_seed_bundle(
        self,
        count: int,
        focus_mode: str,
        topic: Optional[str],
    ) -> List[Dict[str, str]]:
        lane_counts = self._lane_counts_for_focus(count, focus_mode)
        bundle: List[Dict[str, str]] = []

        for lane_name, lane_count in lane_counts.items():
            pool = SOURCE_LANES[lane_name]
            for seed in self._sample_items(pool, lane_count):
                bundle.append({"source_lane": lane_name, "seed": seed})

        if topic:
            bundle.insert(0, {"source_lane": "topic_override", "seed": topic})

        random.shuffle(bundle)
        return bundle[: max(count * 2, count)]

    def _lane_counts_for_focus(self, count: int, focus_mode: str) -> Dict[str, int]:
        if focus_mode == "evergreen":
            return {"evergreen_thesis_bank": count}
        if focus_mode == "reactive":
            market = math.ceil(count * 0.6)
            return {
                "market_behavior_inputs": market,
                "cultural_behavior_inputs": count - market,
            }
        if focus_mode == "literal":
            return {"gambling_casino_inputs": count}

        evergreen = max(1, round(count * 0.7))
        reactive_total = max(1, round(count * 0.2))
        literal = max(1, count - evergreen - reactive_total)
        market = max(1, math.ceil(reactive_total * 0.6))
        culture = max(0, reactive_total - market)

        counts = {
            "evergreen_thesis_bank": evergreen,
            "market_behavior_inputs": market,
            "gambling_casino_inputs": literal,
        }
        if culture:
            counts["cultural_behavior_inputs"] = culture
        return counts

    def _default_source_lane_for_focus(self, focus_mode: str) -> str:
        return {
            "evergreen": "evergreen_thesis_bank",
            "reactive": "market_behavior_inputs",
            "literal": "gambling_casino_inputs",
        }.get(focus_mode, "evergreen_thesis_bank")

    def _render_library(self, library: Dict[str, Dict[str, Any]]) -> str:
        lines = []
        for name, payload in library.items():
            lines.append(f"- {name}")
            for key, value in payload.items():
                if isinstance(value, list):
                    lines.append(f"  {key}: {', '.join(str(item) for item in value)}")
                else:
                    lines.append(f"  {key}: {value}")
        return "\n".join(lines)

    def _render_source_lanes(self) -> str:
        lines = []
        for lane, items in SOURCE_LANES.items():
            lines.append(f"- {lane}: {', '.join(items[:4])}")
        return "\n".join(lines)

    def _render_selected_seeds(self, bundle: List[Dict[str, str]]) -> str:
        return "\n".join(
            f"- [{item['source_lane']}] {item['seed']}"
            for item in bundle
        )

    def _print_concept_summary(self, concepts: List[Dict[str, Any]], focus_mode: str) -> None:
        cprint(f"\n🎥 Generated {len(concepts)} Blackjack God reel concepts [{focus_mode}]", "cyan")
        for concept in concepts[:5]:
            cprint(
                f"   [{concept['series_name']}] {concept['title']} | {concept['pillar']}",
                "white",
            )
        if len(concepts) > 5:
            cprint(f"   ...and {len(concepts) - 5} more", "grey")

    def _generate_json(
        self,
        system_prompt: str,
        user_content: str,
        temperature: float,
        max_tokens: int,
        expect: str,
    ) -> Any:
        response = self.model.generate_response(
            system_prompt=system_prompt,
            user_content=user_content,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if response and hasattr(response, "content"):
            raw_text = response.content
        else:
            raw_text = str(response) if response else ""

        data = self._extract_json(raw_text, expect)
        if expect == "list" and not isinstance(data, list):
            raise ValueError("Expected JSON array from model.")
        if expect == "dict" and not isinstance(data, dict):
            raise ValueError("Expected JSON object from model.")
        return data

    def _extract_json(self, raw_text: str, expect: str) -> Any:
        text = raw_text.strip()
        if text.startswith("```"):
            parts = text.split("```")
            if len(parts) >= 2:
                text = parts[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()

        direct = self._safe_json_load(text)
        if direct is not None:
            return direct

        if expect == "list":
            match = re.search(r"\[\s*{.*}\s*\]", text, re.DOTALL)
            if match:
                data = self._safe_json_load(match.group(0))
                if data is not None:
                    return data
        else:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                data = self._safe_json_load(match.group(0))
                if data is not None:
                    return data

        raise ValueError(f"Could not extract JSON from model response:\n{text[:500]}")

    def _safe_json_load(self, value: str) -> Optional[Any]:
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None

    def _parse_week_start(self, value: Optional[str]) -> date:
        if not value:
            today = date.today()
            return today - timedelta(days=today.weekday())
        return date.fromisoformat(value)

    def _sample_items(self, pool: List[str], count: int) -> List[str]:
        if count <= len(pool):
            return random.sample(pool, count)
        items = pool[:]
        while len(items) < count:
            items.extend(random.sample(pool, min(len(pool), count - len(items))))
        return items[:count]

    def _clean_text(self, value: Any) -> str:
        text = str(value or "").strip()
        text = re.sub(r"\s+", " ", text)
        return text

    def _normalize_list(self, value: Any, limit: Optional[int] = None) -> List[str]:
        if isinstance(value, list):
            items = [self._clean_text(item) for item in value if self._clean_text(item)]
        else:
            text = self._clean_text(value)
            if not text:
                items = []
            else:
                items = [line.strip(" -") for line in re.split(r"[\n\r]+", text) if line.strip()]

        deduped: List[str] = []
        for item in items:
            if item and item not in deduped:
                deduped.append(item)
        if limit:
            return deduped[:limit]
        return deduped

    def _clamp_score(self, value: Any) -> int:
        try:
            score = int(round(float(value)))
        except (TypeError, ValueError):
            score = 0
        return max(0, min(score, 10))

    def _slugify(self, value: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower())
        return slug.strip("_") or "blackjack"

    def _save_json(self, path: Path, payload: Dict[str, Any]) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
