import json
import logging
import os
import subprocess
import time

logger = logging.getLogger(__name__)

_oc_bin = None
_configured_model = None
_oc_config_needs_init = True

PROMPTS_DIR = "prompts"
STRATEGY_CONFIG = "config/strategy_prompt.json"
MODEL_CONFIG = "config/openclaw_model.json"
PROMPT_FILE = os.path.join(PROMPTS_DIR, "strategy_prompt.txt")


def _find_openclaw():
    global _oc_bin
    if _oc_bin:
        return _oc_bin
    import shutil
    candidates = [
        "openclaw",
        os.path.expanduser("~/.npm-global/bin/openclaw"),
    ]
    npm_prefix = os.popen("npm config get prefix 2>/dev/null").read().strip()
    if npm_prefix:
        candidates.append(os.path.join(npm_prefix, "bin", "openclaw"))
    for c in candidates:
        resolved = shutil.which(c) or (c if os.path.isfile(c) else None)
        if resolved:
            _oc_bin = resolved
            return resolved
    return None


def load_strategy():
    with open(STRATEGY_CONFIG) as f:
        return json.load(f)


def load_model_config():
    try:
        with open(MODEL_CONFIG) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _agent_exists(oc_bin, agent_id):
    try:
        r = subprocess.run(
            [oc_bin, "agents", "list", "--json"],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode != 0:
            return False
        data = json.loads(r.stdout)
        agents = data if isinstance(data, list) else data.get("agents", [])
        return any(a.get("id") == agent_id for a in agents)
    except Exception:
        return False


def ensure_agent_identity():
    oc_bin = _find_openclaw()
    if not oc_bin:
        logger.warning("OpenClaw binary not found — cannot set agent identity")
        return False

    if not _agent_exists(oc_bin, "main"):
        logger.info("Creating 'main' agent...")
        try:
            ws = os.path.expanduser("~/.openclaw/workspace")
            r = subprocess.run(
                [oc_bin, "agents", "add", "main",
                 "--non-interactive", "--workspace", ws],
                capture_output=True, text=True, timeout=15,
            )
            if r.returncode != 0:
                logger.warning("Failed to create 'main' agent: %s", r.stderr[:200])
                return False
            logger.info("'main' agent created")
        except Exception as e:
            logger.warning("Error creating 'main' agent: %s", e)
            return False

    try:
        r = subprocess.run(
            [oc_bin, "agents", "set-identity", "--agent", "main",
             "--name", "Trading Bot", "--emoji", "\U0001f916", "--theme", "professional"],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode != 0:
            logger.warning("Agent identity set failed: %s", r.stderr[:200])
            return False
        logger.info("Agent identity set: Trading Bot")
    except Exception as e:
        logger.warning("Agent identity set error: %s", e)
        return False

    # Write IDENTITY.md so new sessions don't trigger the onboarding wizard
    identity_md = os.path.expanduser("~/.openclaw/workspace/IDENTITY.md")
    identity_content = (
        "# IDENTITY.md - Who Am I?\n"
        "\n"
        "- **Name:** Trading Bot\n"
        "- **Creature:** Automated trading AI\n"
        "- **Vibe:** Professional, precise, efficient\n"
        "- **Emoji:** \U0001f916\n"
        "- **Role:** Intraday options trading agent for Zerodha (simulated)\n"
    )
    try:
        os.makedirs(os.path.dirname(identity_md), exist_ok=True)
        with open(identity_md, "w") as f:
            f.write(identity_content)
        logger.info("IDENTITY.md written to workspace")
    except Exception as e:
        logger.warning("Failed to write IDENTITY.md: %s", e)

    return True


def ensure_agent_auth():
    oc_bin = _find_openclaw()
    if not oc_bin:
        return False
    auth_file = os.path.expanduser(
        "~/.openclaw/agents/main/agent/auth-profiles.json"
    )
    if os.path.isfile(auth_file):
        return True
    model_cfg = load_model_config()
    if not model_cfg:
        return False
    api_key = model_cfg.get("api_key", "")
    if not api_key or api_key == "YOUR_API_KEY":
        return False
    provider = model_cfg.get("provider", "openai")
    profile = {
        "profiles": [
            {
                "name": "default",
                "provider": provider,
                "apiKey": api_key,
            }
        ]
    }
    try:
        os.makedirs(os.path.dirname(auth_file), exist_ok=True)
        with open(auth_file, "w") as f:
            json.dump(profile, f, indent=2)
        os.chmod(auth_file, 0o600)
        logger.info("Auth profile written to %s", auth_file)
        return True
    except Exception as e:
        logger.warning("Failed to write auth profile: %s", e)
        return False


def configure_openclaw():
    global _configured_model
    model_cfg = load_model_config()
    if not model_cfg:
        logger.warning("No model config found at %s", MODEL_CONFIG)
        return False

    provider = model_cfg.get("provider", "openai")
    model = model_cfg.get("model", "gpt-4o")
    api_key = model_cfg.get("api_key", "")

    if api_key and api_key != "YOUR_API_KEY":
        env_var = f"{provider.upper()}_API_KEY"
        os.environ[env_var] = api_key
    else:
        logger.warning("No valid API key in config")
        return False

    _configured_model = model
    logger.info("OpenClaw configured with model: %s", model)

    ensure_agent_identity()
    ensure_agent_auth()
    return True


_gateway_proc = None


_gateway_log_file = None


def _stop_existing_gateway(oc_bin):
    """Stop any existing openclaw gateway so port 18789 is free."""
    import socket

    # First try openclaw's own stop command
    try:
        subprocess.run(
            [oc_bin, "gateway", "stop"],
            capture_output=True, timeout=10,
        )
    except Exception:
        pass

    # Try using psutil first as it is cross-platform
    try:
        import psutil
        killed = False
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                for conn in proc.connections(kind='inet'):
                    if conn.laddr.port == 18789:
                        logger.info("Killing process %s (PID %d) using port 18789", proc.info['name'], proc.info['pid'])
                        proc.kill()
                        killed = True
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        if killed:
            time.sleep(1)
    except Exception:
        pass

    # Platform-specific fallback cleanups
    if os.name == 'nt':
        # Windows fallback using netstat + taskkill
        try:
            out = subprocess.check_output("netstat -ano | findstr :18789", shell=True).decode()
            for line in out.strip().split('\n'):
                parts = line.strip().split()
                if len(parts) >= 5 and parts[1].endswith(':18789'):
                    pid = parts[-1]
                    logger.info("Killing port 18789 process on Windows: PID %s", pid)
                    subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True, timeout=5)
        except Exception:
            pass
    else:
        # Linux fallback
        try:
            subprocess.run(["fuser", "-k", "18789/tcp"], capture_output=True, timeout=5)
        except Exception:
            pass
        try:
            subprocess.run(["pkill", "-f", "openclaw gateway"], capture_output=True, timeout=5)
        except Exception:
            pass

    # Wait until port 18789 is actually free (up to 10s)
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", 18789), timeout=0.5):
                time.sleep(0.5)  # still in use, wait
        except OSError:
            break  # port is free
    logger.info("Port 18789 is free — starting fresh gateway")


def start_gateway():
    global _gateway_proc, _gateway_log_file
    oc_bin = _find_openclaw()
    if not oc_bin:
        logger.warning("OpenClaw not found — cannot start gateway")
        return False

    import tempfile

    # Always stop any existing gateway first so we get a clean start
    _stop_existing_gateway(oc_bin)
    time.sleep(1)

    log_fd, log_path = tempfile.mkstemp(prefix="openclaw_gw_", suffix=".log")
    _gateway_log_file = log_path

    try:
        log_fh = os.fdopen(log_fd, "w")
        _gateway_proc = subprocess.Popen(
            [oc_bin, "gateway", "run", "--port", "18789"],
            stdout=log_fh,
            stderr=log_fh,
        )
        logger.info("OpenClaw gateway starting (PID %d)...", _gateway_proc.pid)
        logger.info("Gateway log: %s", log_path)

        # The gateway's browser service takes ~50-60s to fully initialise.
        # We wait 65s to be safe before launching the agent.
        logger.info("Waiting 65 seconds for browser service to initialise...")
        for i in range(65):
            time.sleep(1)
            if (i + 1) % 10 == 0:
                logger.info("  ... %ds elapsed", i + 1)
        logger.info("Gateway ready — launching OpenClaw agent")
        return True
    except Exception as e:
        logger.warning("Failed to start gateway: %s", e)
        return False


def prepare_prompt(platform="Zerodha", arch_doc_content=None):
    os.makedirs(PROMPTS_DIR, exist_ok=True)
    s = load_strategy()

    if platform.lower() == "upstox":
        platform_name = "Upstox"
        login_url = "https://login.upstox.com"
        success_indicators = "dashboard, holdings, positions, portfolio, funds, or orders"
    else:
        platform_name = "Zerodha"
        login_url = "https://kite.zerodha.com"
        success_indicators = "dashboard, holdings, or positions"

    lines = []
    lines.append("OpenClaw Automated Options Strategy — Final Developer Version")
    lines.append("=" * 70)
    lines.append("")

    lines.append("YOUR ROLE")
    lines.append("-" * 40)
    lines.append(f"You are an automated intraday options trading agent for {platform_name}.")
    lines.append("You run in two sessions per day. All trades are simulated.")
    lines.append("You communicate with the user via Telegram for login and status.")
    lines.append(f"Use OpenClaw's own tool/browser environment to open Chrome and inspect {platform_name}.")
    lines.append("")

    lines.append(f"STEP 1 — OPEN CHROME & CHECK {platform_name.upper()} LOGIN")
    lines.append("-" * 40)
    lines.append("CRITICAL: Always use the 'openclaw' managed browser profile.")
    lines.append("Do NOT use the 'user' profile — it requires remote debugging and will fail.")
    lines.append("1. Open the 'openclaw' managed Chrome profile using OpenClaw's browser tool.")
    lines.append(f"2. Reuse the active tab (or navigate the active tab directly) to go to {login_url}.")
    lines.append(f"3. Close any extra tabs (like 'New Tab' or 'about:blank') so only the {platform_name} page is open.")
    lines.append(f"4. Check if already logged in by looking for {success_indicators} content.")
    lines.append(f"5. If login page detected, send Telegram: 'Please log in to the opened Chrome window.'")
    lines.append("6. Wait and retry until login is confirmed.")
    lines.append(f"7. Once logged in, send Telegram: '{platform_name} login confirmed!'")
    lines.append("")

    lines.append("STEP 2 — SEND TELEGRAM MESSAGES")
    lines.append("-" * 40)
    lines.append("Use curl to send Telegram messages:")
    lines.append("  curl -s -X POST https://api.telegram.org/bot<TOKEN>/sendMessage")
    lines.append('    -d "chat_id=<CHAT_ID>" -d "text=<MESSAGE>"')
    lines.append("Read the token and chat_id from config/telegram.json")
    lines.append("")

    lines.append("STRATEGY TYPE")
    lines.append("-" * 40)
    lines.append(s.get("strategy_type", "N/A"))
    lines.append("")

    lines.append("DIRECTION LOGIC (Higher Timeframe Filter)")
    lines.append("-" * 40)
    lines.append(f"Timeframe: {s['direction']['timeframe']}")
    lines.append(f"Indicators: {', '.join(s['direction']['indicators'])}")
    lines.append(f"CE Rule: {s['direction']['rules']['CE']}")
    lines.append(f"PE Rule: {s['direction']['rules']['PE']}")
    lines.append("")

    lines.append("STRIKE SELECTION")
    lines.append("-" * 40)
    lines.append(f"Type: {s['strike_selection']['type']}")
    lines.append(f"Rule: {s['strike_selection']['rule']}")
    lines.append(f"Note: {s['strike_selection']['note']}")
    lines.append("")

    lines.append("ENTRY LOGIC (3m Premium Chart)")
    lines.append("-" * 40)
    lines.append(f"Entry Timeframe: {s['entry']['timeframe']}")
    lines.append(f"Indicators: {', '.join(s['entry']['indicators'])}")
    lines.append("")
    lines.append("CE Entry Conditions (ALL must be true):")
    for c in s['entry']['conditions']['CE']:
        lines.append(f"  - {c}")
    lines.append("")
    lines.append("PE Entry Conditions (ALL must be true):")
    for c in s['entry']['conditions']['PE']:
        lines.append(f"  - {c}")
    lines.append("")

    lines.append("CAPITAL DEPLOYMENT")
    lines.append("-" * 40)
    lines.append(f"Usage: {s['capital']['usage']}")
    lines.append(f"Quantity: {s['capital']['quantity']}")
    lines.append("")

    lines.append("RISK MANAGEMENT")
    lines.append("-" * 40)
    lines.append(f"Max Loss Per Trade: {s['risk_management']['max_loss_per_trade']}")
    lines.append(f"Example: {s['risk_management']['example']}")
    lines.append("")

    lines.append("REWARD TARGET")
    lines.append("-" * 40)
    lines.append(f"Min Target: {s['reward_target']['min']}")
    lines.append(f"Max Target: {s['reward_target']['max']}")
    lines.append(f"Configurable: {s['reward_target']['configurable']}")
    lines.append("")

    lines.append("STOP LOSS")
    lines.append("-" * 40)
    lines.append(f"Type: {s['stop_loss']['type']}")
    lines.append(f"Indicator: {s['stop_loss']['indicator']}")
    lines.append(f"Condition: {s['stop_loss']['condition']}")
    lines.append("")

    lines.append("TRADING SESSIONS")
    lines.append("-" * 40)
    for session in s['sessions']:
        lines.append(f"{session['name']}: {session['start']} - {session['end']} (Max {session['max_trades']} trades)")
    lines.append(f"Daily Limit: {s['daily_limit']['max_trades']} trades max")
    lines.append(f"Rule: {s['daily_limit']['rule']}")
    lines.append("")

    lines.append("EXIT CONDITIONS (Exit immediately if ANY is true)")
    lines.append("-" * 40)
    for i, cond in enumerate(s['exit_conditions'], 1):
        lines.append(f"{i}. {cond}")
    lines.append("")

    lines.append("POSITION MANAGEMENT")
    lines.append("-" * 40)
    lines.append(f"Max Active Trades: {s['position_management']['max_active']}")
    for r in s['position_management']['rules']:
        lines.append(f"  - {r}")
    lines.append("")

    lines.append("AUTO SQUARE-OFF")
    lines.append("-" * 40)
    lines.append(f"Time: {s['auto_square_off']['time']}")
    lines.append(f"Rule: {s['auto_square_off']['rule']}")
    lines.append("")

    lines.append("FAIL-SAFE & SAFETY FEATURES")
    lines.append("-" * 40)
    for item in s['safety']:
        lines.append(f"  - {item}")
    lines.append("")

    lines.append("ALERT SYSTEM (Telegram)")
    lines.append("-" * 40)
    for alert in s['alerts']:
        lines.append(f"  - {alert}")
    lines.append("")

    lines.append("INSTRUCTIONS")
    lines.append("-" * 40)
    lines.append("1. Open Chrome using OpenClaw's own browser/tool capability.")
    lines.append(f"2. Navigate to {login_url} and check login state.")
    lines.append("3. If not logged in, send Telegram asking user to login.")
    lines.append(f"4. Wait and retry until {platform_name.lower()} dashboard/holdings is detected.")
    lines.append("5. Once logged in, send Telegram confirmation.")
    lines.append("6. All trades are simulated. Monitor EMA crossover strategy.")
    lines.append("7. Sessions: 09:30-11:30 (max 2), 13:00-15:00 (max 2).")
    lines.append("8. Stop by 15:15 auto square-off.")
    lines.append("9. Send Telegram alerts for every event (entry, exit, SL, target).")
    lines.append("10. Use OpenClaw for browser operations and curl/bash only for Telegram or file checks when needed.")

    if arch_doc_content:
        lines.append("")
        lines.append("ARCHITECTURE REFERENCE")
        lines.append("=" * 70)
        lines.append(arch_doc_content)

    content = "\n".join(lines)
    with open(PROMPT_FILE, "w") as f:
        f.write(content)
    logger.info("Prompt saved to %s (%d lines)", PROMPT_FILE, len(lines))

    # Also copy to the OpenClaw agent workspace so its tools can find it
    ws_dir = os.path.expanduser("~/.openclaw/workspace/prompts")
    ws_file = os.path.join(ws_dir, "strategy_prompt.txt")
    try:
        os.makedirs(ws_dir, exist_ok=True)
        with open(ws_file, "w") as f:
            f.write(content)
        logger.info("Prompt also written to %s", ws_file)
    except Exception as e:
        logger.warning("Could not write prompt to workspace: %s", e)

    return PROMPT_FILE


def run_openclaw_agent(task_message, timeout_seconds=None):
    """Launch the OpenClaw TUI agent in the current terminal with the given task.

    The agent inherits stdin/stdout/stderr so the full OpenClaw TUI is visible.
    The -m flag pre-fills and auto-submits the strategy message so the agent
    starts executing immediately without manual user input.
    --timeout is intentionally omitted — it is not a valid openclaw agent flag.
    """
    global _configured_model
    oc_bin = _find_openclaw()
    if not oc_bin:
        logger.warning("OpenClaw executable not found")
        return None

    model = _configured_model or "openrouter/auto"

    try:
        session_key = f"agent:main:trading-bot-{int(time.time())}"
        logger.info("Launching OpenClaw agent (session: %s)...", session_key)
        logger.info("OpenClaw will open Chrome, navigate to Zerodha, and wait for your login.")
        logger.info("Please log in when Chrome opens. OpenClaw detects login automatically.")
        print("\n" + "=" * 60)
        print(" OpenClaw Trading Agent starting — Chrome will open shortly")
        print(" Log in to Zerodha/Upstox when prompted.")
        print(" Press Ctrl+C here to stop the bot at any time.")
        print("=" * 60 + "\n")

        # Build command — NO --timeout flag (not a valid openclaw agent flag)
        cmd = [
            oc_bin, "agent", "--local",
            "--agent", "main",
            "--model", model,
            "--session-key", session_key,
            "-m", task_message,
        ]

        # Inherit the full terminal (stdin/stdout/stderr) so the TUI renders properly
        proc = subprocess.Popen(cmd)  # no PIPE — inherits TTY

        # Wait freely — agent runs until it finishes the login+strategy cycle
        proc.wait()
        rc = proc.returncode

        if rc == 0:
            logger.info("OpenClaw agent completed successfully")
        else:
            logger.warning("OpenClaw agent exit code %d", rc)

        return "", "", rc

    except FileNotFoundError:
        logger.warning("OpenClaw executable not found")
        return None
    except KeyboardInterrupt:
        logger.info("OpenClaw agent interrupted by user (Ctrl+C)")
        return "", "", 130
    except Exception as e:
        logger.warning("OpenClaw agent error: %s", e)
        return None


def stop_openclaw():
    global _gateway_proc
    if _gateway_proc:
        _gateway_proc.terminate()
        try:
            _gateway_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _gateway_proc.kill()
        _gateway_proc = None
        logger.info("OpenClaw gateway stopped")
