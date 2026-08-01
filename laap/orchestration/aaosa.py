"""LAAP Aether — AAOSA coordinator for task claiming and delegation."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from laap.agi.multi_agent import TaskBoard, TaskItem
from laap.orchestration.actor import ActorSystem, AgentCell, Capability
from laap.orchestration.primitives import AetherAddress, AetherMessage, MessageType

logger = logging.getLogger("laap.orchestration.aaosa")


class _ClaimRecord:
    """Internal record of a claim response from an actor."""

    def __init__(
        self,
        claimer: AetherAddress,
        confidence: float,
        estimated_cost: float,
        can_handle: bool,
        reason: str,
        received_at: float,
    ):
        self.claimer = claimer
        self.confidence = confidence
        self.estimated_cost = estimated_cost
        self.can_handle = can_handle
        self.reason = reason
        self.received_at = received_at


class AAOSACoordinator:
    """Coordinate AAOSA claims: broadcast tasks, collect claims, delegate."""

    COORDINATOR_ACTOR_ID = "__aaosa_coordinator__"

    def __init__(
        self,
        actor_system: ActorSystem,
        taskboard: Optional[TaskBoard] = None,
    ):
        self.actor_system = actor_system
        self.taskboard = taskboard
        self._tasks: Dict[str, TaskItem] = {}
        self._claims: Dict[str, List[_ClaimRecord]] = {}
        self._lock = asyncio.Lock()

        # Spawn a dedicated actor for receiving claim responses.
        if self.COORDINATOR_ACTOR_ID in self.actor_system.actors:
            self._coordinator_actor = self.actor_system.actors[self.COORDINATOR_ACTOR_ID]
        else:
            self._coordinator_actor = self.actor_system.spawn(
                self.COORDINATOR_ACTOR_ID, capabilities=[]
            )
        self._coordinator_actor.on(MessageType.CLAIM, self._claim_response_handler)

    async def _claim_response_handler(self, msg: AetherMessage) -> None:
        """Handle incoming CLAIM response messages directed at the coordinator."""
        payload = msg.payload
        # Broadcast task messages do not contain a ``can_handle`` field; ignore them
        # here because the coordinator should not claim tasks itself.
        if "can_handle" not in payload:
            return

        task_id = payload.get("task_id")
        if task_id is None or msg.sender is None:
            logger.warning(
                "[AAOSA] Discarding malformed CLAIM response: missing task_id or sender"
            )
            return

        received_at = time.monotonic()
        confidence = float(payload.get("confidence", 0.0))
        estimated_cost = float(payload.get("estimated_cost", 0.0))
        can_handle = bool(payload.get("can_handle", False))
        reason = str(payload.get("reason", ""))
        logger.debug(
            "[AAOSA] Received CLAIM response for task_id=%s from actor=%s "
            "can_handle=%s confidence=%.4f estimated_cost=%.4f reason=%r "
            "received_at=%.6f",
            task_id,
            msg.sender.actor_id,
            can_handle,
            confidence,
            estimated_cost,
            reason,
            received_at,
        )

        async with self._lock:
            self._claims.setdefault(task_id, []).append(
                _ClaimRecord(
                    claimer=msg.sender,
                    confidence=confidence,
                    estimated_cost=estimated_cost,
                    can_handle=can_handle,
                    reason=reason,
                    received_at=received_at,
                )
            )

    @staticmethod
    def _matching_capability(
        actor: AgentCell, requirement: str
    ) -> Optional[Capability]:
        """Return the actor's best capability that can handle *requirement*."""
        best: Optional[Capability] = None
        for capability in actor.capabilities:
            if capability.can_handle(requirement):
                if best is None or capability.confidence > best.confidence:
                    best = capability
        return best

    def _make_default_claim_handler(self, actor: AgentCell):
        """Create a default CLAIM handler bound to *actor*."""

        async def handler(msg: AetherMessage) -> None:
            payload = msg.payload
            task_id = payload.get("task_id")
            requirement = payload.get("requirement", "")
            affected_files = payload.get("affected_files", []) or []

            if task_id is None:
                logger.warning(f"[{actor.actor_id}] CLAIM message missing task_id")
                return

            capability = self._matching_capability(actor, requirement)
            can_handle = capability is not None

            # Actors may refuse to claim if they detect a file lock they do not own.
            if can_handle and self.taskboard is not None:
                for file_path in affected_files:
                    locker = self.taskboard.get_file_locker(file_path)
                    if locker is not None and locker != actor.actor_id:
                        can_handle = False
                        break

            confidence = capability.confidence if capability else 0.0
            estimated_cost = capability.cost_estimate if capability else 0.0
            if capability is None:
                reason = "no matching capability"
            elif not can_handle:
                reason = "detected file lock conflict"
            else:
                reason = f"matched capability {capability.name}"

            reply = AetherMessage(
                msg_type=MessageType.CLAIM,
                sender=actor.address,
                recipient=msg.sender,
                payload={
                    "task_id": task_id,
                    "can_handle": can_handle,
                    "confidence": confidence,
                    "estimated_cost": estimated_cost,
                    "reason": reason,
                },
            )
            await self.actor_system.send(reply)

        return handler

    async def broadcast_task(self, task_item: TaskItem) -> None:
        """Broadcast a CLAIM message to all actors for *task_item*."""
        start = time.monotonic()
        self._tasks[task_item.task_id] = task_item
        self._claims[task_item.task_id] = []

        # Use the task description as the capability requirement.
        requirement = task_item.description

        target_actors = [
            actor
            for actor in self.actor_system.actors.values()
            if actor is not self._coordinator_actor
        ]
        target_addresses = [actor.address.actor_id for actor in target_actors]
        logger.info(
            "[AAOSA] Broadcasting task_id=%s requirement=%r affected_files=%s "
            "priority=%.4f target_actor_count=%d target_actors=%s",
            task_item.task_id,
            requirement,
            list(task_item.affected_files),
            task_item.priority,
            len(target_actors),
            target_addresses,
        )

        # Ensure every actor (except the coordinator) has a default CLAIM handler.
        for actor in target_actors:
            if MessageType.CLAIM not in actor._handlers:
                actor.on(MessageType.CLAIM, self._make_default_claim_handler(actor))

        broadcast_msg = AetherMessage(
            msg_type=MessageType.CLAIM,
            sender=self._coordinator_actor.address,
            recipient=None,
            payload={
                "task_id": task_item.task_id,
                "requirement": requirement,
                "affected_files": list(task_item.affected_files),
                "priority": task_item.priority,
            },
        )

        # Send to each actor individually so the coordinator actor is excluded.
        sent = 0
        for actor in target_actors:
            copy = AetherMessage(
                msg_id=broadcast_msg.msg_id,
                msg_type=broadcast_msg.msg_type,
                sender=broadcast_msg.sender,
                recipient=actor.address,
                payload=broadcast_msg.payload.copy(),
                vector_clock=broadcast_msg.vector_clock.copy(),
                timestamp=broadcast_msg.timestamp,
                priority=broadcast_msg.priority,
                ttl=broadcast_msg.ttl,
            )
            await self.actor_system.send(copy)
            sent += 1

        elapsed = time.monotonic() - start
        logger.info(
            "[AAOSA] Broadcast complete for task_id=%s sent=%d elapsed_ms=%.3f",
            task_item.task_id,
            sent,
            elapsed * 1000.0,
        )

    async def collect_claims(
        self, timeout_sec: float = 2.0
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Wait for actors to respond to CLAIM broadcasts and return responses."""
        start = time.monotonic()
        logger.info("[AAOSA] Collecting claims timeout_sec=%.3f", timeout_sec)
        await asyncio.sleep(timeout_sec)

        async with self._lock:
            elapsed = time.monotonic() - start
            result: Dict[str, List[Dict[str, Any]]] = {}
            for task_id, records in self._claims.items():
                result[task_id] = []
                for record in records:
                    result[task_id].append(
                        {
                            "claimer": record.claimer,
                            "confidence": record.confidence,
                            "estimated_cost": record.estimated_cost,
                            "can_handle": record.can_handle,
                            "reason": record.reason,
                        }
                    )
                    logger.debug(
                        "[AAOSA] Collected CLAIM for task_id=%s actor=%s "
                        "can_handle=%s confidence=%.4f estimated_cost=%.4f "
                        "reason=%r received_at=%.6f",
                        task_id,
                        record.claimer.actor_id,
                        record.can_handle,
                        record.confidence,
                        record.estimated_cost,
                        record.reason,
                        record.received_at,
                    )
            logger.info(
                "[AAOSA] Claims collection complete elapsed_ms=%.3f task_count=%d",
                elapsed * 1000.0,
                len(result),
            )
            return result

    async def resolve_claims(self, task_id: str) -> Optional[str]:
        """Select the best claimant and delegate. Return winner actor_id or None."""
        start = time.monotonic()
        async with self._lock:
            records = list(self._claims.get(task_id, []))

        if not records:
            logger.info("[AAOSA] No claims collected for task_id=%s", task_id)
            return None

        logger.info(
            "[AAOSA] Resolving claims for task_id=%s total_responses=%d",
            task_id,
            len(records),
        )

        # Prefer actors that reported they can handle the task, then sort by
        # confidence descending.
        candidates = [r for r in records if r.can_handle]
        logger.debug(
            "[AAOSA] task_id=%s raw_candidates=%d can_handle_candidates=%d",
            task_id,
            len(records),
            len(candidates),
        )
        candidates.sort(key=lambda r: r.confidence, reverse=True)
        logger.debug(
            "[AAOSA] task_id=%s sorted_candidates=%s",
            task_id,
            [
                (r.claimer.actor_id, r.confidence, r.estimated_cost)
                for r in candidates
            ],
        )

        for candidate in candidates:
            winner_id = candidate.claimer.actor_id
            if self.taskboard is not None:
                ok, reason = self.taskboard.claim_task(task_id, winner_id)
                logger.info(
                    "[AAOSA] TaskBoard.claim_task task_id=%s agent_id=%s ok=%s reason=%r",
                    task_id,
                    winner_id,
                    ok,
                    reason,
                )
                if not ok:
                    logger.warning(
                        "[AAOSA] Fallback required for task_id=%s: %s rejected, reason=%r",
                        task_id,
                        winner_id,
                        reason,
                    )
                    continue
            await self.delegate(task_id, candidate.claimer)
            elapsed = time.monotonic() - start
            logger.info(
                "[AAOSA] Resolved winner for task_id=%s winner=%s elapsed_ms=%.3f",
                task_id,
                winner_id,
                elapsed * 1000.0,
            )
            return winner_id

        elapsed = time.monotonic() - start
        logger.warning(
            "[AAOSA] No conflict-free claimant found for task_id=%s elapsed_ms=%.3f",
            task_id,
            elapsed * 1000.0,
        )
        return None

    async def delegate(self, task_id: str, agent_address: AetherAddress) -> None:
        """Send a DELEGATE message to the winning actor."""
        task = self._tasks.get(task_id)
        payload: Dict[str, Any] = {"task_id": task_id}
        if task is not None:
            payload["affected_files"] = list(task.affected_files)
            payload["priority"] = task.priority
            payload["description"] = task.description

        logger.info(
            "[AAOSA] Delegating task_id=%s to actor=%s payload=%r",
            task_id,
            agent_address.actor_id,
            payload,
        )

        delegate_msg = AetherMessage(
            msg_type=MessageType.DELEGATE,
            sender=self._coordinator_actor.address,
            recipient=agent_address,
            payload=payload,
        )
        await self.actor_system.send(delegate_msg)
