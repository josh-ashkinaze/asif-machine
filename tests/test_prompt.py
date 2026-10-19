#!/usr/bin/env python3
"""
Interactive CLI tool for testing and iterating on event prompts.
Usage: python tests/test_prompt.py

Global commands (available at ANY prompt):
  help / h      Show help
  reload / r    Reload config.yaml & prompts.yaml
  back / b      Cancel current action, return to main menu
  quit / q      Exit the tool
"""

import json
import os
import random
import readline
import yaml
from dotenv import load_dotenv
import litellm
from litellm import completion

litellm.drop_params = True

load_dotenv()

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

GLOBAL_COMMANDS = {"help", "h", "reload", "r", "back", "b", "quit", "q"}

# ── exceptions for flow control ──────────────────────────────────────────

class UserBack(Exception):
    """User wants to go back to main menu."""

class UserQuit(Exception):
    """User wants to exit."""

# ── smart input ──────────────────────────────────────────────────────────

class State:
    """Mutable shared state passed around so reload/help work everywhere."""
    def __init__(self):
        self.config, self.prompts = load_configs()
        self.pipeline_result = None
        self.verbose = True
        self.last_event_key = None
        self.last_char_key = None
        self.prompt_log = []

    def reload(self):
        self.config, self.prompts = load_configs()
        print("  >> Reloaded config.yaml & prompts.yaml")

    def log_prompt(self, label, yaml_source, system, user):
        idx = len(self.prompt_log)
        self.prompt_log.append({
            "label": label,
            "yaml_source": yaml_source,
            "system": system,
            "user": user,
        })
        return idx

    def clear_log(self):
        self.prompt_log = []


def load_configs():
    with open(os.path.join(PROJECT_ROOT, "config.yaml")) as f:
        config = yaml.safe_load(f)
    with open(os.path.join(PROJECT_ROOT, "prompts.yaml")) as f:
        prompts = yaml.safe_load(f)
    return config, prompts


def smart_input(prompt_text, state):
    """input() wrapper that intercepts global commands at any prompt."""
    try:
        raw = input(prompt_text).strip()
    except (EOFError, KeyboardInterrupt):
        raise UserQuit()

    cmd = raw.lower()
    if cmd in ("quit", "q"):
        raise UserQuit()
    if cmd in ("back", "b"):
        raise UserBack()
    if cmd in ("reload", "r"):
        state.reload()
        raise UserBack()
    if cmd in ("help", "h"):
        print_help()
        raise UserBack()
    return raw

# ── helpers ──────────────────────────────────────────────────────────────

def print_help():
    print()
    print("  ┌─────────────────────────────────────────────────────┐")
    print("  │  COMMANDS (main menu)                               │")
    print("  │    run       Pick event + character, run pipeline   │")
    print("  │    rerun/rr  Re-run last selection (auto-reloads)   │")
    print("  │    ac        Test autocomplete with custom text     │")
    print("  │    show <n>  Show full prompt #n from last run      │")
    print("  │    prompts   List all saved prompts from last run   │")
    print("  │    events    List all events                        │")
    print("  │    chars     List all characters                    │")
    print("  │    verbose/v Toggle prompt debug output             │")
    print("  ├─────────────────────────────────────────────────────┤")
    print("  │  GLOBAL (works at any prompt)                       │")
    print("  │    help/h    Show this help                         │")
    print("  │    reload/r  Reload yaml files                      │")
    print("  │    back/b    Cancel & return to main menu           │")
    print("  │    quit/q    Exit                                   │")
    print("  └─────────────────────────────────────────────────────┘")
    print()


def list_events(config):
    events = config["event"]
    keys = [k for k in events if k.startswith("event_")]
    for i, k in enumerate(keys):
        name = events[k].get("name", "")
        preview = (name[:80] + "...") if len(name) > 80 else name
        print(f"  {i:3d}  {k:25s}  {preview}")
    return keys


def list_characters(config):
    chars = config["characters"]
    keys = list(chars.keys())
    for i, k in enumerate(keys):
        c = chars[k]
        print(f"  {i:3d}  {k:25s}  {c.get('name', '?')}, {c.get('occupation', '?')}")
    return keys


def build_character_description(char):
    base = f"I am {char['age']} years old from {char['location']}, working as a {char['occupation']}. "
    extras = ". ".join(
        f"My {k.replace('_', ' ')} is {v}"
        for k, v in char.items()
        if k not in ("age", "gender", "occupation", "location")
    )
    return f"{base} {extras}." if extras else base


def call_llm(model, system, user, temperature=0.6, max_tokens=1000):
    resp = completion(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content


def print_section(title, content):
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}")
    print(content)
    print()


def print_prompt_debug(idx, label, system, user, yaml_source):
    truncated = len(system) > 200 or len(user) > 200
    marker = " *" if truncated else ""
    print(f"\n  ┌─ [{idx}] {label} PROMPT{marker} ─────────────────────")
    print(f"  │ [system] {system[:200]}{'...' if len(system)>200 else ''}")
    print(f"  │ [user]   {user[:200]}{'...' if len(user)>200 else ''}")
    print(f"  │ source:  prompts.yaml -> {yaml_source}")
    if truncated:
        print(f"  │ (truncated — type 'show {idx}' to see full prompt)")
    print(f"  └─────────────────────────────────────")


def show_prompt(state, idx):
    if idx < 0 or idx >= len(state.prompt_log):
        print(f"  Invalid index. Available: 0-{len(state.prompt_log)-1}")
        return
    entry = state.prompt_log[idx]
    print(f"\n{'═'*60}")
    print(f"  [{idx}] {entry['label']}  (source: prompts.yaml -> {entry['yaml_source']})")
    print(f"{'═'*60}")
    print(f"\n  ── SYSTEM ──")
    print(entry["system"])
    print(f"\n  ── USER ──")
    print(entry["user"])
    print(f"{'═'*60}\n")


def pick_index(items, prompt_text, state):
    """Pick from a numbered list. Supports index, key name, or global commands."""
    hint = f"  (0-{len(items)-1}, or name. 'back' to cancel, 'help' for help)"
    print(hint)
    while True:
        raw = smart_input(prompt_text, state)
        if raw.isdigit() and 0 <= int(raw) < len(items):
            return int(raw)
        for i, k in enumerate(items):
            if raw == k:
                return i
        print(f"  Invalid. Enter 0-{len(items)-1} or key name.")


# ── pipeline ─────────────────────────────────────────────────────────────

def run_pipeline(state, event_key, char_key):
    config, prompts, verbose = state.config, state.prompts, state.verbose
    state.clear_log()
    event = config["event"][event_key]
    char = config["characters"][char_key]
    model = config["event"].get("effects_generator_model", "gpt-4o")
    char_desc = build_character_description(char)
    event_name = event["name"]

    print_section("CHARACTER", char_desc)
    print_section("EVENT", event_name)

    steps = [
        ("start_of_event", "start_of_event", {
            "event_name": event_name, "character_description": char_desc,
        }),
        ("dynamic_effects", "dynamic_effects", {
            "event_name": event_name, "character_description": char_desc,
        }),
    ]

    results = {}
    for label, yaml_key, fmt_args in steps:
        sys_msg = prompts[yaml_key]["system"]
        usr_msg = prompts[yaml_key]["user"].format(**fmt_args)
        idx = state.log_prompt(label, yaml_key, sys_msg, usr_msg)
        if verbose:
            print_prompt_debug(idx, label, sys_msg, usr_msg, yaml_key)
        results[label] = call_llm(model, sys_msg, usr_msg)
        print_section(label.upper().replace("_", " "), results[label])

    # event_plot depends on start_of_event
    sys_msg = prompts["event_plot"]["system"]
    usr_msg = prompts["event_plot"]["user"].format(
        character_description=char_desc, event_name=event_name,
        event_start=results["start_of_event"],
    )
    idx = state.log_prompt("event_plot", "event_plot", sys_msg, usr_msg)
    if verbose:
        print_prompt_debug(idx, "event_plot", sys_msg, usr_msg, "event_plot")
    results["event_plot"] = call_llm(model, sys_msg, usr_msg)
    print_section("EVENT PLOT", results["event_plot"])

    # event_plot_from_effects depends on start + effects
    sys_msg = prompts["event_plot_from_effects"]["system"]
    usr_msg = prompts["event_plot_from_effects"]["user"].format(
        character_description=char_desc, event_name=event_name,
        event_effects=results["dynamic_effects"],
        event_start=results["start_of_event"],
    )
    idx = state.log_prompt("event_plot_from_effects", "event_plot_from_effects", sys_msg, usr_msg)
    if verbose:
        print_prompt_debug(idx, "event_plot_from_effects", sys_msg, usr_msg, "event_plot_from_effects")
    results["event_plot_from_effects"] = call_llm(model, sys_msg, usr_msg)
    print_section("EVENT PLOT (from effects)", results["event_plot_from_effects"])

    if verbose:
        print("  Prompts saved. Type 'show <n>' to view full prompt (0-3).")

    return {
        "char_desc": char_desc,
        "event": event,
        "event_name": event_name,
        "start": results["start_of_event"],
        "effects": results["dynamic_effects"],
        "plot": results["event_plot"],
        "plot_from_effects": results["event_plot_from_effects"],
    }


def run_autocomplete(state, context, incomplete):
    config, prompts, verbose = state.config, state.prompts, state.verbose
    pipeline_result = state.pipeline_result
    model = config["llm"]["model"]
    temp = random.uniform(config["llm"]["temperature_min"], config["llm"]["temperature_max"])
    max_tokens = random.randint(config["llm"]["max_tokens_min"], config["llm"]["max_tokens_max"])

    autocomplete_ctx = config["autocomplete"]["autocomplete_context"]
    ctx_map = {
        "plot": pipeline_result["plot"],
        "effects": pipeline_result["effects"],
        "start": pipeline_result["start"],
        "plot_from_effects": pipeline_result["plot_from_effects"],
    }
    event_content = ctx_map.get(autocomplete_ctx, pipeline_result["plot_from_effects"])

    constraints = "\n- " + "\n- ".join(prompts["constraints"])

    sys_msg = prompts["chat_completion"]["event"]["system"].format(
        event=event_content,
        character_description=pipeline_result["char_desc"],
        event_effects=pipeline_result["effects"],
        event_constraints=constraints,
    )
    usr_msg = prompts["chat_completion"]["event"]["user"].format(
        context=context, incomplete_sentence=incomplete
    )

    yaml_source = "chat_completion.event"
    idx = state.log_prompt("chat_completion", yaml_source, sys_msg, usr_msg)
    if verbose:
        print_prompt_debug(idx, "chat_completion", sys_msg, usr_msg, yaml_source)
    print(f"  (model={model}, temp={temp:.2f}, max_tokens={max_tokens})")

    result = call_llm(model, sys_msg, usr_msg, temperature=temp, max_tokens=max_tokens)
    print_section("AUTOCOMPLETE", result)
    return result


# ── main loop ────────────────────────────────────────────────────────────

def main():
    state = State()

    print("\n╔══════════════════════════════════════════╗")
    print("║   Prompt Testing Tool                    ║")
    print("╚══════════════════════════════════════════╝")
    print_help()

    while True:
        try:
            cmd = smart_input("prompt> ", state).lower()
        except UserBack:
            continue
        except UserQuit:
            print("Bye!")
            break

        try:
            if cmd == "events":
                list_events(state.config)

            elif cmd == "chars":
                list_characters(state.config)

            elif cmd in ("verbose", "v"):
                state.verbose = not state.verbose
                print(f"  Verbose mode: {'ON' if state.verbose else 'OFF'}")

            elif cmd == "run":
                print("\n── Events ──")
                event_keys = list_events(state.config)
                idx = pick_index(event_keys, "  Select event: ", state)
                state.last_event_key = event_keys[idx]

                print("\n── Characters ──")
                char_keys = list_characters(state.config)
                idx = pick_index(char_keys, "  Select character: ", state)
                state.last_char_key = char_keys[idx]

                state.pipeline_result = run_pipeline(
                    state, state.last_event_key, state.last_char_key
                )

            elif cmd in ("rerun", "rr"):
                if state.last_event_key and state.last_char_key:
                    state.reload()
                    state.pipeline_result = run_pipeline(
                        state, state.last_event_key, state.last_char_key
                    )
                else:
                    print("  No previous run. Use 'run' first.")

            elif cmd == "ac":
                if not state.pipeline_result:
                    print("  Run the pipeline first ('run').")
                    continue
                context = smart_input("  Context (previous sentences): ", state)
                incomplete = smart_input("  Incomplete sentence: ", state)
                run_autocomplete(state, context, incomplete)

            elif cmd.startswith("show"):
                parts = cmd.split()
                if len(parts) == 2 and parts[1].isdigit():
                    show_prompt(state, int(parts[1]))
                elif not state.prompt_log:
                    print("  No prompts yet. Run the pipeline first.")
                else:
                    print(f"  Usage: show <n>  (available: 0-{len(state.prompt_log)-1})")

            elif cmd == "prompts":
                if not state.prompt_log:
                    print("  No prompts yet. Run the pipeline first.")
                else:
                    print()
                    for i, entry in enumerate(state.prompt_log):
                        sys_len = len(entry["system"])
                        usr_len = len(entry["user"])
                        print(f"  [{i}] {entry['label']:30s}  source: {entry['yaml_source']:30s}  sys:{sys_len:>5} chars  usr:{usr_len:>5} chars")
                    print(f"\n  Type 'show <n>' to view full prompt.\n")

            else:
                print("  Unknown command. Type 'help' for options.")

        except UserBack:
            print("  << Back to main menu")
            continue
        except UserQuit:
            print("Bye!")
            break


if __name__ == "__main__":
    main()
