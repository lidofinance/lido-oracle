#!/usr/bin/env python3
"""Glamsterdam devnet calibration + wire-shape preflight gate.

Two jobs, in this order:

1. **Calibrate.** Measure the target devnet and emit a profile: fork phase, chain size, Lido
   footprint, withdrawal demand, missed-slot rate, oracle frames. The test plan references these
   symbolically (`$BUFFER`, `$TAB`, `$N_LIDO`), so nothing in it is hardcoded to one devnet.

2. **Gate.** Prove the beacon-API wire shape matches `src/providers/consensus/types.py` before any
   report number is trusted. Every Gloas field the oracle reads has a default there
   (`GLOAS_FORK_EPOCH = 2**64 - 1`, `payload_expected_withdrawals: list = field(default_factory=list)`)
   and `FromResponse` drops unknown keys, so a renamed or re-nested field does not raise -- it yields
   "no TVL correction, forever pre-fork" and every member computes the same wrong number and reaches
   quorum. No report comparison can detect that.

The gate adapts to the fork phase: before Gloas activation the absence of Gloas fields is *correct*,
so it is reported as such rather than failed. That makes this runnable from a devnet's first day,
through its transition, and after.

Finally it computes a **scenario reachability matrix**: which plan scenarios can actually be proven
on this chain, and for those that cannot, the arithmetic showing why. A scenario that is unreachable
will pass vacuously, which is worse than not running it.

Read-only: GETs plus `eth_call` / `eth_getBlockByHash` / `eth_getBalance`. Never signs.

Usage:
    poetry run python scripts/glamsterdam_preflight.py --cl URL --el URL [--locator 0x...]
                                                       [--ref-slot N] [--json profile.json]
                                                       [--missed-sample 384]

Exit 0 = no FAIL, 1 = at least one FAIL.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import gzip
import json
import sys
import urllib.error
import urllib.request
from typing import Any


TIMEOUT = 180
GWEI = 10**9
WEI = 10**18
BUILDER_INDEX_FLAG = 2**40
FAR_FUTURE_EPOCH = 2**64 - 1

# Values the oracle hardcodes in src/constants.py. A chain whose spec disagrees means the constant is
# wrong *for that chain*, which silently changes churn and sweep arithmetic.
HARDCODED_CONSTANTS = {
    "CHURN_LIMIT_QUOTIENT_GLOAS": 2**15,
    "MAX_WITHDRAWALS_PER_PAYLOAD": 2**4,
    "MIN_PER_EPOCH_CHURN_LIMIT_ELECTRA": 2**7 * GWEI,
    "MAX_PENDING_PARTIALS_PER_WITHDRAWALS_SWEEP": 2**3,
    "MIN_VALIDATOR_WITHDRAWABILITY_DELAY": 2**8,
    "MAX_SEED_LOOKAHEAD": 2**2,
}

# Selectors hardcoded so this script stays stdlib-only (it must run anywhere, including a bare
# devnet jumpbox). Verified against keccak; `_selfcheck_selectors` re-verifies whenever eth_utils
# happens to be importable, so a typo here cannot silently return None for a field.
SEL = {
    "withdrawalQueue()": "0x37d5fe99",
    "lido()": "0x23509a2d",
    "accountingOracle()": "0x5a2031f9",
    "validatorsExitBusOracle()": "0x12f8d4b9",
    "stakingRouter()": "0xef6c064c",
    "withdrawalVault()": "0x69d42148",
    "elRewardsVault()": "0xe441d25f",
    "burner()": "0x27810b6e",
    "unfinalizedStETH()": "0xd0fb84e8",
    "getLastRequestId()": "0x19c2b4c3",
    "getLastFinalizedRequestId()": "0x4f069a13",
    "getBufferedEther()": "0x47b714e0",
    "getWithdrawalsReserve()": "0x8a5e5688",
    "getTotalPooledEther()": "0x37cfdaca",
    "totalSupply()": "0x18160ddd",
    "getStakingModuleIds()": "0xf2aebb65",
    "getLastProcessingRefSlot()": "0x3584d59c",
    "getStakingModuleSummary(uint256)": "0x07e203ac",
}


def _selfcheck_selectors() -> list[str]:
    """Return signatures whose hardcoded selector is wrong. Empty when eth_utils is unavailable."""
    try:
        from eth_utils import keccak
    except ImportError:
        return []
    return [sig for sig, claimed in SEL.items() if "0x" + keccak(text=sig).hex()[:8] != claimed]


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str]] = []

    def add(self, status: str, name: str, detail: str = "") -> None:
        self.rows.append((status, name, detail))
        icon = {
            "PASS": "\033[32mPASS\033[0m",
            "FAIL": "\033[31mFAIL\033[0m",
            "WARN": "\033[33mWARN\033[0m",
            "INFO": "\033[36mINFO\033[0m",
            "N/A ": "\033[90mN/A \033[0m",
        }[status]
        print(f"  [{icon}] {name}")
        for line in detail.splitlines():
            if line:
                print(f"         {line}")

    def failed(self) -> int:
        return sum(1 for s, _, _ in self.rows if s == "FAIL")


# ------------------------------------------------------------------------------------ transport


def _get(url: str) -> Any:
    req = urllib.request.Request(url, headers={"Accept": "application/json", "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    return json.loads(raw)


def _rpc(el: str, method: str, params: list) -> Any:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(el, body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.load(resp).get("result")


def _call_int(el: str, to: str, sig: str) -> int | None:
    try:
        res = _rpc(el, "eth_call", [{"to": to, "data": SEL[sig]}, "latest"])
        return int(res, 16) if res and res != "0x" else None
    except Exception:
        return None


def _call_addr(el: str, to: str, sig: str) -> str | None:
    try:
        res = _rpc(el, "eth_call", [{"to": to, "data": SEL[sig]}, "latest"])
        return "0x" + res[-40:] if res and len(res) >= 42 else None
    except Exception:
        return None


def _header(cl: str, slot: int) -> dict | None:
    try:
        return _get(f"{cl}/eth/v1/beacon/headers/{slot}")["data"]
    except Exception:
        return None


def _next_non_missed(cl: str, slot: int, limit: int = 96) -> int:
    for candidate in range(slot, slot + limit):
        if _header(cl, candidate) is not None:
            return candidate
    raise RuntimeError(f"no non-missed slot in [{slot}, {slot + limit})")


# ------------------------------------------------------------------------------------ calibrate


def calibrate_chain(cl: str, el: str, rep: Report) -> dict:
    """Fork phase, timing and the transition ETA. Everything else keys off this."""
    spec = _get(f"{cl}/eth/v1/config/spec")["data"]
    genesis = _get(f"{cl}/eth/v1/beacon/genesis")["data"]
    head = _get(f"{cl}/eth/v1/beacon/headers/head")["data"]
    finality = _get(f"{cl}/eth/v1/beacon/states/head/finality_checkpoints")["data"]

    slots_per_epoch = int(spec["SLOTS_PER_EPOCH"])
    seconds_per_slot = int(spec.get("SECONDS_PER_SLOT") or int(spec["SLOT_DURATION_MS"]) // 1000)
    head_slot = int(head["header"]["message"]["slot"])
    current_epoch = head_slot // slots_per_epoch
    finalized_epoch = int(finality["finalized"]["epoch"])
    genesis_time = int(genesis["genesis_time"])

    gloas_raw = spec.get("GLOAS_FORK_EPOCH")
    gloas_epoch = int(gloas_raw) if gloas_raw is not None else None

    try:
        chain_id = int(_rpc(el, "eth_chainId", []), 16)
    except Exception:
        chain_id = None

    if gloas_epoch is None:
        phase = "NO_GLOAS_KEY"
    elif gloas_epoch >= FAR_FUTURE_EPOCH:
        phase = "GLOAS_NEVER"
    elif current_epoch < gloas_epoch:
        phase = "PRE_FORK"
    elif current_epoch < gloas_epoch + 2:
        phase = "AT_TRANSITION"
    else:
        phase = "POST_FORK"

    prof = {
        "chain_id": chain_id,
        "cl_version": _get(f"{cl}/eth/v1/node/version")["data"]["version"],
        "slots_per_epoch": slots_per_epoch,
        "seconds_per_slot": seconds_per_slot,
        "genesis_time": genesis_time,
        "head_slot": head_slot,
        "current_epoch": current_epoch,
        "finalized_epoch": finalized_epoch,
        "gloas_fork_epoch": gloas_epoch,
        "fork_phase": phase,
        "spec": {k: spec.get(k) for k in HARDCODED_CONSTANTS},
    }

    detail = (
        f"chain_id={chain_id}  cl={prof['cl_version']}\n"
        f"head slot={head_slot} epoch={current_epoch}  finalized epoch={finalized_epoch}\n"
        f"epoch = {slots_per_epoch} slots x {seconds_per_slot}s = {slots_per_epoch * seconds_per_slot / 60:.1f} min"
    )

    if gloas_epoch is None:
        rep.add(
            "FAIL",
            "GLOAS_FORK_EPOCH present in /eth/v1/config/spec",
            detail + "\nKey ABSENT. types.py defaults it to 2**64-1, so is_gloas() is permanently\n"
            "False and PR 965's churn + sweep changes silently never activate.",
        )
    elif phase == "GLOAS_NEVER":
        rep.add(
            "WARN",
            "GLOAS_FORK_EPOCH present in /eth/v1/config/spec",
            detail + f"\nGLOAS_FORK_EPOCH={gloas_epoch} (far future): this chain never forks.\n"
            "Only pre-fork regression scenarios (AC-00, EJ-00) are meaningful here.",
        )
    else:
        eta = ""
        if phase == "PRE_FORK":
            fork_slot = gloas_epoch * slots_per_epoch
            secs = (fork_slot - head_slot) * seconds_per_slot
            when = dt.datetime.fromtimestamp(genesis_time + fork_slot * seconds_per_slot, dt.UTC)
            epochs_left = gloas_epoch - current_epoch
            eta = (
                f"\n>>> PRE-FORK: {epochs_left} epochs to Gloas (slot {fork_slot})"
                f"\n>>> T-minus {secs / 3600:.1f} h -- activates {when:%Y-%m-%d %H:%M UTC}"
                f"\n>>> The transition is a ONE-SHOT, unrepeatable capture window. See plan Phase 3b."
            )
        elif phase == "AT_TRANSITION":
            eta = f"\n>>> AT TRANSITION (fork epoch {gloas_epoch}, now {current_epoch}). Capture NOW."
        else:
            eta = f"\n>>> POST-FORK by {current_epoch - gloas_epoch} epochs (fork epoch {gloas_epoch})."
        rep.add("PASS", "GLOAS_FORK_EPOCH present in /eth/v1/config/spec", detail + eta)

    mismatched = []
    for key, expected in HARDCODED_CONSTANTS.items():
        actual = spec.get(key)
        if actual is None:
            # Pre-Gloas clients legitimately do not publish the Gloas-only keys yet.
            if "GLOAS" in key and phase in ("PRE_FORK", "NO_GLOAS_KEY", "GLOAS_NEVER"):
                continue
            mismatched.append(f"{key}: ABSENT (oracle hardcodes {expected})")
        elif int(actual) != expected:
            mismatched.append(f"{key}: spec={actual} but src/constants.py hardcodes {expected}")
    if mismatched:
        rep.add("FAIL", "hardcoded src/constants.py values match the chain spec", "\n".join(mismatched))
    else:
        rep.add(
            "PASS",
            "hardcoded src/constants.py values match the chain spec",
            ", ".join(f"{k}={spec[k]}" for k in HARDCODED_CONSTANTS if spec.get(k) is not None),
        )
    return prof


def calibrate_missed_rate(cl: str, prof: dict, sample: int, rep: Report) -> dict:
    """Missed-slot rate drives how often the post-fork forward-walk and missed-child paths occur."""
    spe = prof["slots_per_epoch"]
    hi = (prof["finalized_epoch"] - 1) * spe
    lo = max(0, hi - sample)
    with concurrent.futures.ThreadPoolExecutor(16) as pool:
        present = dict(pool.map(lambda s: (s, _header(cl, s) is not None), range(lo, hi)))
    missed = [s for s, ok in present.items() if not ok]
    rate = len(missed) / max(1, len(present))

    boundaries = []
    for epoch in range(lo // spe + 1, hi // spe):
        ref = epoch * spe + spe - 1
        child = ref + 1
        if ref in present and child in present:
            boundaries.append({"ref_slot": ref, "ref_present": present[ref], "child_present": present[child]})
    missed_children = sum(1 for b in boundaries if not b["child_present"])

    prof["missed_slot_rate"] = round(rate, 4)
    prof["ref_boundaries_sampled"] = len(boundaries)
    prof["ref_boundaries_with_missed_child"] = missed_children
    rep.add(
        "INFO",
        "missed-slot rate (drives forward-walk / missed-child coverage)",
        f"{len(missed)}/{len(present)} slots missed = {rate * 100:.1f}% over [{lo},{hi})\n"
        f"ref-slot boundaries sampled={len(boundaries)}, of which child missed={missed_children}\n"
        + (
            "Forward-walk and missed-child paths occur naturally -- free coverage."
            if missed_children
            else "No missed children in the sample: AC-10 / forward-walk may need forcing."
        ),
    )
    return prof


def calibrate_contracts(el: str, locator: str | None, rep: Report) -> dict:
    """Resolve every address from the locator so no address is hardcoded per devnet."""
    if not locator:
        rep.add("WARN", "Lido contracts resolved from the locator", "--locator not given; protocol checks skipped")
        return {}
    out: dict[str, str] = {"lido_locator": locator}
    for sig, key in [
        ("lido()", "lido"),
        ("withdrawalQueue()", "withdrawal_queue"),
        ("accountingOracle()", "accounting_oracle"),
        ("validatorsExitBusOracle()", "validators_exit_bus_oracle"),
        ("stakingRouter()", "staking_router"),
        ("withdrawalVault()", "withdrawal_vault"),
        ("elRewardsVault()", "el_rewards_vault"),
        ("burner()", "burner"),
    ]:
        addr = _call_addr(el, locator, sig)
        if addr:
            out[key] = addr
    if len(out) < 5:
        rep.add("FAIL", "Lido contracts resolved from the locator", f"only resolved: {sorted(out)}")
    else:
        rep.add(
            "PASS",
            "Lido contracts resolved from the locator",
            "\n".join(f"{k:26} {v}" for k, v in out.items() if k != "lido_locator"),
        )
    return out


def calibrate_protocol(el: str, contracts: dict, rep: Report) -> dict:
    """Buffer, demand and depositable capacity -- the EJ-01 sizing inputs."""
    if not contracts.get("lido"):
        return {}
    lido, wq = contracts["lido"], contracts.get("withdrawal_queue")
    prof = {
        "buffered_ether_wei": _call_int(el, lido, "getBufferedEther()"),
        "withdrawals_reserve_wei": _call_int(el, lido, "getWithdrawalsReserve()"),
        "total_pooled_ether_wei": _call_int(el, lido, "getTotalPooledEther()"),
        "unfinalized_steth_wei": _call_int(el, wq, "unfinalizedStETH()") if wq else None,
        "last_request_id": _call_int(el, wq, "getLastRequestId()") if wq else None,
        "last_finalized_request_id": _call_int(el, wq, "getLastFinalizedRequestId()") if wq else None,
    }
    for key, addr_key in [("withdrawal_vault_wei", "withdrawal_vault"), ("el_rewards_vault_wei", "el_rewards_vault")]:
        if contracts.get(addr_key):
            try:
                prof[key] = int(_rpc(el, "eth_getBalance", [contracts[addr_key], "latest"]), 16)
            except Exception:
                prof[key] = None

    eth = lambda w: "n/a" if w is None else f"{w / WEI:,.6f} ETH"  # noqa: E731
    rep.add(
        "INFO",
        "protocol state (EJ-01 sizing inputs)",
        f"buffered_ether        {eth(prof['buffered_ether_wei'])}\n"
        f"withdrawals_reserve   {eth(prof['withdrawals_reserve_wei'])}   (tracks demand)\n"
        f"unfinalized_steth     {eth(prof['unfinalized_steth_wei'])}   <- ejector demand\n"
        f"withdrawal_vault      {eth(prof.get('withdrawal_vault_wei'))}\n"
        f"el_rewards_vault      {eth(prof.get('el_rewards_vault_wei'))}\n"
        f"requests last/finalized {prof['last_request_id']}/{prof['last_finalized_request_id']}",
    )

    # Depositable capacity per staking module -- gates EJ-01 route B and AC-08.
    sr = contracts.get("staking_router")
    modules: list[dict] = []
    if sr:
        try:
            raw = _rpc(el, "eth_call", [{"to": sr, "data": SEL["getStakingModuleIds()"]}, "latest"])
            words = [int(raw[2:][i : i + 64], 16) for i in range(0, len(raw) - 2, 64)]
            ids = words[2 : 2 + words[1]]
        except Exception:
            ids = []
        for mid in ids:
            # getStakingModuleSummary(uint256) -> (exited, deposited, depositable)
            try:
                res = _rpc(
                    el,
                    "eth_call",
                    [{"to": sr, "data": SEL["getStakingModuleSummary(uint256)"] + f"{mid:064x}"}, "latest"],
                )
                w = [int(res[2:][i : i + 64], 16) for i in range(0, len(res) - 2, 64)]
                modules.append(
                    {"id": mid, "exited": w[0], "deposited": w[1], "depositable": w[2]} if len(w) >= 3 else {"id": mid}
                )
            except Exception:
                modules.append({"id": mid})
    prof["staking_modules"] = modules
    total_depositable = sum(m.get("depositable", 0) or 0 for m in modules)
    prof["total_depositable_keys"] = total_depositable
    rep.add(
        "INFO" if total_depositable else "WARN",
        "depositable keys exist (gates EJ-01 route B and AC-08)",
        "\n".join(
            f"module {m['id']}: exited={m.get('exited')} "
            f"deposited={m.get('deposited')} depositable={m.get('depositable')}"
            for m in modules
        )
        + (
            f"\ntotal depositable = {total_depositable}"
            if total_depositable
            else "\nZERO depositable keys in every module -> `lido deposit` is a no-op.\n"
            "Add and vet keys (lido-core add-keys, then set-staking-limit) to unblock."
        ),
    )

    # Oracle frames -- the cadence the whole plan is scheduled against.
    for name, key in [("accounting", "accounting_oracle"), ("ejector", "validators_exit_bus_oracle")]:
        if contracts.get(key):
            prof[f"{name}_last_processing_ref_slot"] = _call_int(el, contracts[key], "getLastProcessingRefSlot()")
    return prof


def calibrate_cl(cl: str, contracts: dict, prof: dict, ref_slot: int, rep: Report) -> tuple[dict, dict]:
    """Validator-set size, Lido footprint and total active balance, from the child state."""
    child = _next_non_missed(cl, ref_slot + 1)
    state = _get(f"{cl}/eth/v2/debug/beacon/states/{child}")["data"]
    spe = prof["slots_per_epoch"]
    epoch = int(state["slot"]) // spe
    vals = state["validators"]
    balances = [int(b) for b in state["balances"]]

    active = [i for i, v in enumerate(vals) if int(v["activation_epoch"]) <= epoch < int(v["exit_epoch"])]
    tab = sum(int(vals[i]["effective_balance"]) for i in active)

    lido_idx: list[int] = []
    vault = (contracts.get("withdrawal_vault") or "").lower().removeprefix("0x")
    if vault:
        lido_idx = [i for i, v in enumerate(vals) if v["withdrawal_credentials"][-40:].lower() == vault]

    prof.update(
        {
            "ref_slot": ref_slot,
            "child_slot": child,
            "validators_total": len(vals),
            "validators_active": len(active),
            "total_active_balance_gwei": tab,
            "lido_validator_count": len(lido_idx),
            "lido_validator_indices": [min(lido_idx), max(lido_idx)] if lido_idx else None,
            "pending_deposits": len(state.get("pending_deposits") or []),
            "pending_partial_withdrawals": len(state.get("pending_partial_withdrawals") or []),
            "pending_consolidations": len(state.get("pending_consolidations") or []),
            "builders": len(state.get("builders") or []),
            "builder_pending_withdrawals": len(state.get("builder_pending_withdrawals") or []),
        }
    )

    wc_mix: dict[str, int] = {}
    sweepable = 0
    for i in lido_idx:
        pre = vals[i]["withdrawal_credentials"][:4]
        wc_mix[pre] = wc_mix.get(pre, 0) + 1
        cap = 32 * GWEI if pre == "0x01" else 2048 * GWEI
        if balances[i] > cap:
            sweepable += 1
    prof["lido_wc_mix"] = wc_mix
    prof["lido_sweepable_count"] = sweepable

    rep.add(
        "INFO",
        "CL profile (ref slot / child, chain size, Lido footprint)",
        f"ref_slot={ref_slot} -> child_slot={child} (walked {child - ref_slot - 1} missed slot(s))\n"
        f"validators total={len(vals)} active={len(active)}\n"
        f"total_active_balance = {tab / GWEI:,.0f} ETH\n"
        f"Lido validators = {len(lido_idx)} {prof['lido_validator_indices'] or ''} wc mix={wc_mix or 'n/a'}\n"
        f"  of which currently sweepable (balance > cap) = {sweepable}\n"
        f"pending: deposits={prof['pending_deposits']} partials={prof['pending_partial_withdrawals']} "
        f"consolidations={prof['pending_consolidations']}\n"
        f"builders={prof['builders']} builder_pending_withdrawals={prof['builder_pending_withdrawals']}",
    )
    return prof, state


# --------------------------------------------------------------------------------- wire shape


def gate_wire_shape(cl: str, el: str, prof: dict, state: dict, rep: Report) -> None:
    phase = prof["fork_phase"]
    child = prof["child_slot"]
    block = _get(f"{cl}/eth/v2/beacon/blocks/{child}")
    body = block["data"]["message"]["body"]
    version = block.get("version")
    pre_fork_shape = body.get("execution_payload") is not None

    if phase in ("PRE_FORK", "GLOAS_NEVER", "NO_GLOAS_KEY"):
        if pre_fork_shape:
            rep.add(
                "PASS",
                "block shape matches the fork phase",
                f"version={version}: pre-fork block embeds execution_payload, and the chain IS pre-fork.\n"
                "BlockstampBuilder takes the pre-fork branch -- correct. Gloas field checks below are N/A.",
            )
        else:
            rep.add(
                "FAIL",
                "block shape matches the fork phase",
                f"version={version}: block has NO execution_payload but GLOAS_FORK_EPOCH says pre-fork.\n"
                "Spec and block shape disagree -- fork detection will mis-select.",
            )
        for name in (
            "state.latest_block_hash present",
            "state.payload_expected_withdrawals present",
            "INVARIANT state.latest_block_hash == bid.message.parent_block_hash",
            "PR 964 add-back direction verified against EL blocks",
        ):
            rep.add("N/A ", name, "chain is pre-fork; re-run this gate after the transition")
        return

    if pre_fork_shape:
        rep.add(
            "FAIL",
            "block shape matches the fork phase",
            f"version={version}: chain is post-fork but the block still embeds execution_payload.",
        )
        return
    rep.add("PASS", "block shape matches the fork phase", f"version={version}: post-fork, no embedded payload")

    bid = body.get("signed_execution_payload_bid")
    bid_msg = (bid or {}).get("message", {})
    if not bid:
        rep.add(
            "FAIL",
            "body.signed_execution_payload_bid.message.parent_block_hash at the coded path",
            "Absent -> MissingExecutionAnchor on the liveness path kills EVERY daemon cycle.",
        )
    elif "parent_block_hash" not in bid_msg:
        rep.add(
            "FAIL",
            "body.signed_execution_payload_bid.message.parent_block_hash at the coded path",
            f"bid.message keys = {sorted(bid_msg)}",
        )
    else:
        rep.add(
            "PASS",
            "body.signed_execution_payload_bid.message.parent_block_hash at the coded path",
            f"parent_block_hash={bid_msg['parent_block_hash']}",
        )

    anchor = state.get("latest_block_hash")
    if not anchor:
        rep.add("FAIL", "state.latest_block_hash present", "Absent -> every report blockstamp raises.")
    else:
        rep.add("PASS", "state.latest_block_hash present", anchor)

    if "payload_expected_withdrawals" not in state:
        rep.add(
            "FAIL",
            "state.payload_expected_withdrawals present",
            "Absent. types.py defaults it to [], so PR 964's TVL correction is permanently ZERO\n"
            "with no error: TVL is silently understated on every post-fork report.",
        )
        pew = []
    else:
        pew = state["payload_expected_withdrawals"]
        bad = [w for w in pew if "validator_index" not in w or "amount" not in w]
        if bad:
            rep.add("FAIL", "state.payload_expected_withdrawals present", f"entry keys = {sorted(bad[0])}")
        else:
            builders = sum(1 for w in pew if int(w["validator_index"]) >= BUILDER_INDEX_FLAG)
            rep.add(
                "PASS",
                "state.payload_expected_withdrawals present",
                f"n={len(pew)} total={sum(int(w['amount']) for w in pew)} gwei builder-flagged={builders}",
            )

    parent = bid_msg.get("parent_block_hash")
    if anchor and parent:
        ok = anchor == parent
        rep.add(
            "PASS" if ok else "FAIL",
            "INVARIANT state.latest_block_hash == bid.message.parent_block_hash",
            (
                f"both = {anchor}\nIts only test is skip-ped, so this is its sole coverage."
                if ok
                else f"state={anchor}\nbid  ={parent}\nLiveness stamps anchor on the wrong EL block."
            ),
        )

    _gate_correction_sign(el, anchor, bid_msg.get("block_hash"), pew, rep)


def _gate_correction_sign(el: str, anchor: str | None, own: str | None, pew: list, rep: Report) -> None:
    """PR 964 adds payload_expected_withdrawals back onto CL balances. Correct only if the anchor EL
    block has NOT yet credited them. Prove it from the EL side, independent of the oracle."""
    if not (anchor and pew):
        rep.add("N/A ", "PR 964 add-back direction verified against EL blocks", "nothing in flight at this slot")
        return
    anchor_block = _rpc(el, "eth_getBlockByHash", [anchor, False])
    if anchor_block is None:
        rep.add("FAIL", "EL knows the anchor block hash", f"{anchor} -> null (EL behind CL finality?)")
        return
    rep.add("PASS", "EL knows the anchor block hash", f"anchor = block #{int(anchor_block['number'], 16)}")

    expected = sum(int(w["amount"]) for w in pew)
    a_sum = sum(int(w["amount"], 16) for w in (anchor_block.get("withdrawals") or []))
    a_num = int(anchor_block["number"], 16)
    own_block = _rpc(el, "eth_getBlockByHash", [own, False]) if own else None
    if own_block is None:
        rep.add(
            "WARN",
            "PR 964 add-back direction verified against EL blocks",
            f"this slot's own payload is not on the EL (withheld payload) -- the fallback case,\n"
            f"where the anchor legitimately predates ref_slot. anchor#{a_num} sum={a_sum} gwei",
        )
        return
    o_sum = sum(int(w["amount"], 16) for w in (own_block.get("withdrawals") or []))
    o_num = int(own_block["number"], 16)
    if expected == o_sum and expected != a_sum:
        rep.add(
            "PASS",
            "PR 964 add-back direction verified against EL blocks",
            f"payload_expected_withdrawals = {expected} gwei\n"
            f"anchor block #{a_num} withdrawals = {a_sum} gwei  (does NOT include them)\n"
            f"own    block #{o_num} withdrawals = {o_sum} gwei  (credits them)\n"
            "=> vault read before the credit, so adding back is correct, not a double count.",
        )
    elif expected == a_sum:
        rep.add(
            "FAIL",
            "PR 964 add-back direction verified against EL blocks",
            f"anchor #{a_num} ALREADY credits {a_sum} gwei == payload_expected_withdrawals.\n"
            "Adding back DOUBLE-COUNTS and inflates reported TVL.",
        )
    else:
        rep.add(
            "WARN",
            "PR 964 add-back direction verified against EL blocks",
            f"expected={expected} anchor#{a_num}={a_sum} own#{o_num}={o_sum} gwei (no clean match)",
        )


def gate_proposer_duties(cl: str, prof: dict, rep: Report) -> None:
    spe = prof["slots_per_epoch"]
    epoch = prof["ref_slot"] // spe
    if epoch < 2:
        rep.add("N/A ", "proposer-duties dependent_root formula", "epoch < 2; nothing to compare")
        return

    def last_root_of(target: int) -> str | None:
        slot = target * spe + spe - 1
        for _ in range(spe * 2):
            header = _header(cl, slot)
            if header is not None:
                return header["root"]
            slot -= 1
        return None

    r1, r2 = last_root_of(epoch - 1), last_root_of(epoch - 2)
    try:
        v2 = _get(f"{cl}/eth/v2/validator/duties/proposer/{epoch}")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            rep.add(
                "INFO",
                "proposer-duties v2 available (PR 966 primary path)",
                "404 -> oracle falls back to v1 with relaxed validation. Correct, but this node\n"
                "cannot exercise the v2 path. Good node for testing the FALLBACK.",
            )
        else:
            rep.add(
                "FAIL",
                "proposer-duties v2 available (PR 966 primary path)",
                f"HTTP {exc.code}: only 404 triggers the fallback, so this kills every checkpoint.",
            )
        return
    got = v2.get("dependent_root")
    if got == r2:
        rep.add("PASS", "v2 dependent_root == last non-missed slot of epoch-2", f"epoch {epoch}: {got}")
    elif got == r1:
        rep.add(
            "FAIL",
            "v2 dependent_root == last non-missed slot of epoch-2",
            "v2 returned the epoch-1 root. PR 966 validates strictly -> EVERY checkpoint raises.",
        )
    else:
        rep.add("FAIL", "v2 dependent_root == last non-missed slot of epoch-2", f"got={got} e-2={r2} e-1={r1}")


# ------------------------------------------------------------------------------- reachability


def reachability(prof: dict, rep: Report) -> list[dict]:
    """Which plan scenarios can actually be proven here. A vacuous pass is worse than no run."""
    phase = prof["fork_phase"]
    post = phase in ("POST_FORK", "AT_TRANSITION")
    tab = prof.get("total_active_balance_gwei") or 0
    min_electra = HARDCODED_CONSTANTS["MIN_PER_EPOCH_CHURN_LIMIT_ELECTRA"]
    need_floor = min_electra * 2**15
    need_beat_cap = 256 * GWEI * 2**15
    demand = prof.get("unfinalized_steth_wei") or 0
    buffered = prof.get("buffered_ether_wei") or 0

    def q(x: int) -> int:
        return x // GWEI * GWEI

    churn_pre = min(256 * GWEI, max(min_electra, q(tab // 2**16))) if tab else 0
    churn_post = max(min_electra, q(tab // 2**15)) if tab else 0

    rows: list[dict] = [
        {
            "id": "AC-00 / EJ-00 pre-fork baseline",
            "ok": phase in ("PRE_FORK", "GLOAS_NEVER"),
            "why": f"fork_phase={phase}"
            + ("" if phase in ("PRE_FORK", "GLOAS_NEVER") else "; pre-fork states likely pruned -> use a cassette"),
        },
        {
            "id": "AC-01/AC-02 post-fork blockstamp + TVL correction",
            "ok": post,
            "why": f"fork_phase={phase}",
        },
        {
            "id": "AC-10 missed child / forward walk",
            "ok": bool(prof.get("ref_boundaries_with_missed_child")),
            "why": f"{prof.get('ref_boundaries_with_missed_child')}/{prof.get('ref_boundaries_sampled')} "
            f"sampled ref boundaries had a missed child (missed rate {(prof.get('missed_slot_rate') or 0) * 100:.1f}%)",
        },
        {
            "id": "AC-03 / EJ-09 builder entries",
            "ok": bool(prof.get("builders") or prof.get("builder_pending_withdrawals")),
            "why": f"builders={prof.get('builders')} "
            f"builder_pending_withdrawals={prof.get('builder_pending_withdrawals')}"
            + ("" if prof.get("builders") else " -> needs a synthetic overlay"),
        },
        {
            "id": "EJ-01 demand-driven exits",
            "ok": demand > buffered and demand > 0,
            "why": f"unfinalized={demand / WEI:,.2f} ETH vs buffered={buffered / WEI:,.2f} ETH"
            + (
                ""
                if demand > buffered
                else f" -> need > {buffered / WEI:,.0f} ETH of requests, or drain the buffer"
                + (
                    f" (route B blocked: {prof.get('total_depositable_keys')} depositable keys)"
                    if not prof.get("total_depositable_keys")
                    else ""
                )
            ),
        },
        {
            "id": "EJ-03 EIP-8061 churn divergence",
            "ok": bool(tab) and churn_post != churn_pre,
            "why": f"TAB={tab / GWEI:,.0f} ETH -> pre={churn_pre / GWEI:,.0f} post={churn_post / GWEI:,.0f} ETH/epoch"
            + (
                ""
                if churn_post != churn_pre
                else f"; IDENTICAL (both at the {min_electra / GWEI:.0f} ETH floor). "
                f"need > {need_floor / GWEI / 1e6:.2f}M ETH to diverge, "
                f"> {need_beat_cap / GWEI / 1e6:.2f}M to beat the pre-fork cap"
            ),
        },
        {
            "id": "EJ-04 sweep excludes pending partials",
            "ok": bool(prof.get("pending_partial_withdrawals")),
            "why": f"pending_partial_withdrawals={prof.get('pending_partial_withdrawals')}"
            + ("" if prof.get("pending_partial_withdrawals") else " -> inject via el-requests wr"),
        },
        {
            "id": "AC-08 deposit reconciliation",
            "ok": bool(prof.get("total_depositable_keys")),
            "why": f"depositable keys={prof.get('total_depositable_keys')}"
            + ("" if prof.get("total_depositable_keys") else " -> add + vet keys first"),
        },
        {
            "id": "Fork-transition frames (one-shot)",
            "ok": phase in ("PRE_FORK", "AT_TRANSITION"),
            "why": (
                f"PRE-FORK: {(prof['gloas_fork_epoch'] - prof['current_epoch'])} epochs of lead time -- "
                "set up capture NOW, see plan Phase 3b"
                if phase == "PRE_FORK"
                else "AT TRANSITION: capture immediately"
                if phase == "AT_TRANSITION"
                else f"already {prof['current_epoch'] - (prof['gloas_fork_epoch'] or 0)} epochs past the fork; "
                "window has closed on this chain"
            ),
        },
    ]

    print("\n=== SCENARIO REACHABILITY ON THIS CHAIN ===")
    for r in rows:
        mark = "\033[32mREACHABLE  \033[0m" if r["ok"] else "\033[33mUNREACHABLE\033[0m"
        print(f"  [{mark}] {r['id']}")
        print(f"                 {r['why']}")
    unreachable = [r["id"] for r in rows if not r["ok"]]
    if unreachable:
        print(
            "\n  Unreachable scenarios will PASS VACUOUSLY if you run them anyway.\n"
            "  Do not tick them from this chain -- record a synthetic cassette or use a bigger chain."
        )
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cl", required=True)
    ap.add_argument("--el", required=True)
    ap.add_argument("--locator", help="LidoLocator address; all other addresses are derived from it")
    ap.add_argument("--ref-slot", type=int, help="default: last slot of (finalized_epoch - 2)")
    ap.add_argument("--json", help="write the calibration profile here")
    ap.add_argument("--missed-sample", type=int, default=384, help="slots to sample for the missed rate")
    args = ap.parse_args()

    cl, el = args.cl.rstrip("/"), args.el.rstrip("/")
    rep = Report()

    bad_selectors = _selfcheck_selectors()
    if bad_selectors:
        print(f"\nBUG: hardcoded selectors are wrong for: {', '.join(bad_selectors)}")
        return 1

    print("\n=== A. chain calibration ========================================================")
    prof = calibrate_chain(cl, el, rep)
    spe = prof["slots_per_epoch"]
    ref_slot = args.ref_slot if args.ref_slot is not None else (prof["finalized_epoch"] - 2) * spe + spe - 1
    calibrate_missed_rate(cl, prof, args.missed_sample, rep)

    print("\n=== B. protocol calibration =====================================================")
    contracts = calibrate_contracts(el, args.locator, rep)
    prof["contracts"] = contracts
    prof.update(calibrate_protocol(el, contracts, rep))

    print("\n=== C. consensus-layer calibration ==============================================")
    prof, state = calibrate_cl(cl, contracts, prof, ref_slot, rep)

    print("\n=== D. wire-shape gate =========================================================")
    gate_wire_shape(cl, el, prof, state, rep)

    print("\n=== E. proposer duties (PR 966) =================================================")
    gate_proposer_duties(cl, prof, rep)

    prof["reachability"] = reachability(prof, rep)

    counts = {s: sum(1 for x, _, _ in rep.rows if x == s) for s in ("PASS", "WARN", "FAIL", "N/A ", "INFO")}
    print(
        f"\n=== SUMMARY: {counts['PASS']} pass, {counts['WARN']} warn, {counts['FAIL']} fail, {counts['N/A ']} n/a ==="
    )
    print(f"fork_phase={prof['fork_phase']} ref_slot={prof['ref_slot']} child_slot={prof['child_slot']}")
    if counts["FAIL"]:
        print("\nFAIL = a field the oracle reads is not where the code looks. Fix before trusting any")
        print("report number: every member would compute the same wrong value and reach quorum.")

    if args.json:
        with open(args.json, "w") as fh:
            json.dump(prof, fh, indent=2, sort_keys=True)
        print(f"\nprofile written to {args.json}")
    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
