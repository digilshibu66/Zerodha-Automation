import json
import logging
import os
import secrets
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

_oc_bin = None
_configured_model = None
_oc_config_needs_init = True

PROMPTS_DIR = "prompts"
STRATEGY_CONFIG = "config/strategy_prompt.json"
MODEL_CONFIG = "config/openclaw_model.json"
TELEGRAM_CONFIG = "config/telegram.json"
UPSTOX_LOGIN_CONFIG = "config/upstox_login.json"
PROMPT_FILE = os.path.join(PROMPTS_DIR, "strategy_prompt.txt")
OPENCODE_FREE_MODEL = "opencode/deepseek-v4-flash-free"


def _is_linux():
    return sys.platform.startswith("linux")


def _is_windows():
    return os.name == "nt"


class _DryRunProcess:
    def __init__(self, name):
        self.name = name
        self.pid = 0
        self.returncode = 0

    def wait(self, timeout=None):
        self.returncode = 0
        return 0

    def terminate(self):
        self.returncode = 0

    def kill(self):
        self.returncode = 0


def _normalize_model_for_openclaw(provider, model):
    if not model:
        return model

    if provider == "openai" and model.startswith("openai-codex/"):
        return "openai/" + model.split("/", 1)[1]

    if provider == "opencode" and model == "opencode/big-pickle":
        return model

    # Prevent double prefix like openai/openai-codex/gpt-5.5
    if "/" in model:
        return model

    return f"{provider}/{model}"

def _api_key_env_vars(provider):
    """Return provider env vars used by OpenClaw for API-key auth."""
    if provider in ("opencode", "opencode-go"):
        return ["OPENCODE_API_KEY"]
    if provider == "google":
        return ["GEMINI_API_KEY", "GOOGLE_API_KEY"]
    return [f"{provider.upper().replace('-', '_')}_API_KEY"]


def _check_provider_connectivity(provider, api_key):
    """Fail fast when the configured LLM provider cannot be reached."""
    provider = (provider or "").lower()
    checks = {
        "openrouter": (
            "https://openrouter.ai/api/v1/key",
            {"Authorization": f"Bearer {api_key}", "User-Agent": "trading-automation-bot"},
        ),
        "openai": (
            "https://api.openai.com/v1/models",
            {"Authorization": f"Bearer {api_key}"},
        ),
        "anthropic": (
            "https://api.anthropic.com/v1/models",
            {"x-api-key": api_key, "anthropic-version": "2023-06-01"},
        ),
        "opencode": (
            "https://opencode.ai/zen/v1/models",
            {"User-Agent": "trading-automation-bot"},
        ),
        "opencode-go": (
            "https://opencode.ai/zen/v1/models",
            {"User-Agent": "trading-automation-bot"},
        ),
        "google": (
            f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}",
            {"User-Agent": "trading-automation-bot"},
        ),
    }

    if provider not in checks:
        logger.info("No provider preflight configured for %s", provider)
        return True

    url, headers = checks[provider]
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            if 200 <= response.status < 300:
                logger.info("%s provider preflight passed", provider)
                return True
            logger.warning("%s provider preflight failed with HTTP %s", provider, response.status)
            return False
    except urllib.error.HTTPError as e:
        logger.warning("%s provider preflight failed with HTTP %s: %s", provider, e.code, e.reason)
        return False
    except urllib.error.URLError as e:
        logger.warning("%s provider preflight failed: %s", provider, e.reason)
        return False
    except Exception as e:
        logger.warning("%s provider preflight failed: %s", provider, e)
        return False


def _find_openclaw():
    global _oc_bin
    if _oc_bin:
        return _oc_bin
    import shutil
    candidates = ["openclaw", "openclaw.cmd"]
    path_dirs = [
        os.path.expanduser("~/.local/bin"),
        os.path.expanduser("~/.npm-global/bin"),
        os.path.expanduser("~/node_modules/.bin"),
    ]
    appdata = os.environ.get("APPDATA")
    if appdata:
        path_dirs.append(os.path.join(appdata, "npm"))
    localappdata = os.environ.get("LOCALAPPDATA")
    if localappdata:
        path_dirs.extend([
            os.path.join(localappdata, "npm"),
            os.path.join(localappdata, "OpenClaw", "deps", "portable-node"),
        ])

    try:
        npm_prefix = subprocess.run(
            ["npm", "config", "get", "prefix"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        ).stdout.strip()
        if npm_prefix:
            path_dirs.extend([npm_prefix, os.path.join(npm_prefix, "bin")])
    except Exception:
        pass

    candidates = [
        *candidates,
        *[os.path.join(d, name) for d in path_dirs for name in ("openclaw", "openclaw.cmd")],
    ]
    for c in candidates:
        resolved = shutil.which(c) or (c if os.path.isfile(c) else None)
        if resolved:
            _oc_bin = resolved
            return resolved
    return None


def load_strategy():
    with open(STRATEGY_CONFIG, encoding="utf-8-sig") as f:
        return json.load(f)


def load_model_config():
    try:
        with open(MODEL_CONFIG, encoding="utf-8-sig") as f:
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
        with open(identity_md, "w", encoding="utf-8") as f:
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
    model_cfg = load_model_config()
    if not model_cfg:
        return False
    if model_cfg.get("auth_type") == "oauth":
        logger.info("OpenClaw OAuth auth selected; using OpenClaw-managed auth profiles")
        return True
    api_key = model_cfg.get("api_key", "")
    if not api_key or api_key == "YOUR_API_KEY":
        return False
    provider = model_cfg.get("provider", "openai")
    profiles = {
        f"{provider}:default": {
            "type": "api_key",
            "provider": provider,
            "key": api_key,
        }
    }
    if provider in ("opencode", "opencode-go"):
        profiles["opencode:default"] = {
            "type": "api_key",
            "provider": "opencode",
            "key": api_key,
        }
        profiles["opencode-go:default"] = {
            "type": "api_key",
            "provider": "opencode-go",
            "key": api_key,
        }

    profile = {
        "version": 1,
        "profiles": profiles,
    }
    try:
        os.makedirs(os.path.dirname(auth_file), exist_ok=True)
        with open(auth_file, "w", encoding="utf-8") as f:
            json.dump(profile, f, indent=2)
        os.chmod(auth_file, 0o600)
        logger.info("Auth profile written to %s", auth_file)
        return True
    except Exception as e:
        logger.warning("Failed to write auth profile: %s", e)
        return False


def configure_openclaw():
    global _configured_model, _agent_proc
    model_cfg = load_model_config()
    if not model_cfg:
        logger.warning("No model config found at %s", MODEL_CONFIG)
        return False

    provider = model_cfg.get("provider", "openai")
    model = model_cfg.get("model", "gpt-4o")
    api_key = model_cfg.get("api_key", "")
    auth_type = model_cfg.get("auth_type", "api_key")
    model = _normalize_model_for_openclaw(provider, model)

    if auth_type == "oauth":
        logger.info("Using OpenClaw-managed OAuth auth for provider: %s", provider)
    else:
        if api_key and api_key != "YOUR_API_KEY":
            for env_var in _api_key_env_vars(provider):
                os.environ[env_var] = api_key
        else:
            logger.warning("No valid API key in config")
            return False

        if not _check_provider_connectivity(provider, api_key):
            logger.warning("OpenClaw provider preflight failed — update provider/API key or check network access")
            return False

    _configured_model = model
    logger.info("OpenClaw configured with provider: %s, model: %s", provider, model)

    ensure_agent_identity()
    ensure_agent_auth()
    return True


_gateway_proc = None
_agent_proc = None


_gateway_log_file = None


def _ensure_gateway_token():
    token = os.environ.get("OPENCLAW_GATEWAY_TOKEN", "").strip()
    if token:
        return token
    token = secrets.token_urlsafe(32)
    os.environ["OPENCLAW_GATEWAY_TOKEN"] = token
    logger.info("Generated runtime OpenClaw gateway token for this bot session")
    return token


def _build_linux_terminal_command(title, script_path):
    """Return a terminal-emulator command that runs script_path, or None."""
    terminals = [
        ("gnome-terminal", ["gnome-terminal", "--wait", "--title", title, "--", "bash", script_path]),
        ("konsole", ["konsole", "--title", title, "-e", "bash", script_path]),
        ("xfce4-terminal", ["xfce4-terminal", "--title", title, "--command", f"bash {shlex.quote(script_path)}"]),
        ("xterm", ["xterm", "-T", title, "-e", "bash", script_path]),
    ]
    for binary, command in terminals:
        if shutil.which(binary):
            return command
    return None


def _write_linux_terminal_script(command, exit_code_path=None, log_path=None, hold_on_exit=False):
    fd, script_path = tempfile.mkstemp(prefix="openclaw_terminal_", suffix=".sh")
    quoted_command = " ".join(shlex.quote(str(part)) for part in command)
    exit_line = ""
    if exit_code_path:
        exit_line = f"printf '%s\\n' \"$rc\" > {shlex.quote(exit_code_path)}\n"
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("#!/usr/bin/env bash\n")
        f.write(f"cd {shlex.quote(os.getcwd())}\n")
        f.write(f"export OPENCLAW_GATEWAY_TOKEN={shlex.quote(os.environ.get('OPENCLAW_GATEWAY_TOKEN', ''))}\n")
        if log_path:
            f.write(f"log_path={shlex.quote(log_path)}\n")
            f.write("echo \"Logging to: $log_path\"\n")
            f.write(f"{quoted_command} 2>&1 | tee \"$log_path\"\n")
            f.write("rc=${PIPESTATUS[0]}\n")
        else:
            f.write(f"{quoted_command}\n")
            f.write("rc=$?\n")
        f.write(exit_line)
        if hold_on_exit:
            f.write("if [ \"$rc\" -ne 0 ]; then\n")
            f.write("  echo\n")
            f.write("  echo \"OpenClaw command failed with exit code $rc.\"\n")
            if log_path:
                f.write("  echo \"Review log: $log_path\"\n")
            f.write("  read -r -p \"Press Enter to close this terminal...\" _\n")
            f.write("fi\n")
        f.write("exit $rc\n")
    os.chmod(script_path, 0o700)
    return script_path


def _launch_linux_terminal(title, command, exit_code_path=None, log_path=None, hold_on_exit=False):
    script_path = _write_linux_terminal_script(command, exit_code_path, log_path, hold_on_exit)
    terminal_command = _build_linux_terminal_command(title, script_path)
    if not terminal_command:
        logger.warning("No supported Linux terminal emulator found; running in current terminal")
        return None, script_path
    return subprocess.Popen(terminal_command, start_new_session=True), script_path


def _write_windows_console_script(command, exit_code_path=None, log_path=None, hold_on_exit=False):
    fd, script_path = tempfile.mkstemp(prefix="openclaw_console_", suffix=".ps1")
    quoted_command = " ".join(_quote_powershell_arg(str(part)) for part in command)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("$ErrorActionPreference = 'Continue'\n")
        f.write(f"Set-Location -LiteralPath {_quote_powershell_arg(os.getcwd())}\n")
        f.write(f"$env:OPENCLAW_GATEWAY_TOKEN = {_quote_powershell_arg(os.environ.get('OPENCLAW_GATEWAY_TOKEN', ''))}\n")
        if log_path:
            f.write(f"$logPath = {_quote_powershell_arg(log_path)}\n")
            f.write("Write-Host \"Logging to: $logPath\"\n")
            f.write(f"& {quoted_command} 2>&1 | Tee-Object -FilePath $logPath\n")
        else:
            f.write(f"& {quoted_command}\n")
        f.write("$rc = if ($LASTEXITCODE -ne $null) { $LASTEXITCODE } else { 0 }\n")
        if exit_code_path:
            f.write(f"Set-Content -LiteralPath {_quote_powershell_arg(exit_code_path)} -Value $rc -Encoding UTF8\n")
        if hold_on_exit:
            f.write("if ($rc -ne 0) {\n")
            f.write("  Write-Host ''\n")
            f.write("  Write-Host \"OpenClaw command failed with exit code $rc.\" -ForegroundColor Red\n")
            if log_path:
                f.write("  Write-Host \"Review log: $logPath\" -ForegroundColor Yellow\n")
            f.write("  Read-Host 'Press Enter to close this terminal'\n")
            f.write("}\n")
        f.write("exit $rc\n")
    return script_path


def _quote_powershell_arg(value):
    return "'" + value.replace("'", "''") + "'"


def _launch_windows_console(title, command, exit_code_path=None, log_path=None, hold_on_exit=False):
    script_path = _write_windows_console_script(command, exit_code_path, log_path, hold_on_exit)
    if os.environ.get("TRADING_BOT_DRY_RUN_WINDOWS_LAUNCH") == "1":
        logger.info("Windows console dry-run: %s script generated at %s", title, script_path)
        if exit_code_path:
            with open(exit_code_path, "w", encoding="utf-8") as f:
                f.write("0\n")
        return _DryRunProcess(title), script_path
    ps_cmd = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
    ]
    ps_cmd.append(f"$host.UI.RawUI.WindowTitle = {_quote_powershell_arg(title)}; & {_quote_powershell_arg(script_path)}")
    creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    return subprocess.Popen(ps_cmd, creationflags=creationflags), script_path


def _sync_telegram_config_to_workspace():
    ws_config_file = os.path.expanduser("~/.openclaw/workspace/config/telegram.json")
    try:
        if os.path.exists(ws_config_file):
            os.remove(ws_config_file)
            logger.info("Removed OpenClaw workspace Telegram config; Python runtime now sends Telegram messages")
    except Exception as e:
        logger.warning("Could not remove OpenClaw workspace Telegram config: %s", e)


def _sync_upstox_login_config_to_workspace():
    try:
        with open(UPSTOX_LOGIN_CONFIG, encoding="utf-8-sig") as f:
            cfg = json.load(f)
        mobile = str(cfg.get("mobile", "")).strip()
        if not mobile:
            logger.warning("Upstox login config missing mobile; not syncing to OpenClaw workspace")
            return
        ws_config_dir = os.path.expanduser("~/.openclaw/workspace/config")
        os.makedirs(ws_config_dir, exist_ok=True)
        ws_config_file = os.path.join(ws_config_dir, "upstox_login.json")
        with open(ws_config_file, "w", encoding="utf-8") as f:
            json.dump({"mobile": mobile}, f, indent=2)
            f.write("\n")
        os.chmod(ws_config_file, 0o600)
        logger.info("Upstox login config synced to OpenClaw workspace")
    except FileNotFoundError:
        logger.info("No Upstox login config found; OpenClaw will ask for mobile if needed")
    except Exception as e:
        logger.warning("Could not sync Upstox login config to OpenClaw workspace: %s", e)


def _runtime_stop_requested():
    for path in (
        "prompts/runtime_control.json",
        os.path.expanduser("~/.openclaw/workspace/prompts/runtime_control.json"),
    ):
        try:
            with open(path, encoding="utf-8-sig") as f:
                control = json.load(f)
            if control.get("command") == "stop":
                return True
        except (FileNotFoundError, json.JSONDecodeError):
            continue
        except Exception as e:
            logger.warning("Could not read runtime control %s: %s", path, e)
    return False


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

    gateway_token = _ensure_gateway_token()

    # Always stop any existing gateway first so we get a clean start
    _stop_existing_gateway(oc_bin)
    time.sleep(1)

    log_fd, log_path = tempfile.mkstemp(prefix="openclaw_gw_", suffix=".log")
    _gateway_log_file = log_path

    try:
        gateway_cmd = [oc_bin, "gateway", "run", "--port", "18789", "--token", gateway_token]
        if _is_linux():
            _gateway_proc, _ = _launch_linux_terminal("OpenClaw Gateway", gateway_cmd)
            if _gateway_proc:
                os.close(log_fd)
                logger.info("OpenClaw gateway starting in a separate Linux terminal (PID %d)...", _gateway_proc.pid)
                logger.info("Gateway terminal shows live output")
            else:
                log_fh = os.fdopen(log_fd, "w", encoding="utf-8", errors="replace")
                _gateway_proc = subprocess.Popen(gateway_cmd, stdout=log_fh, stderr=log_fh)
                logger.info("OpenClaw gateway starting (PID %d)...", _gateway_proc.pid)
                logger.info("Gateway log: %s", log_path)
        elif _is_windows():
            _gateway_proc, _ = _launch_windows_console("OpenClaw Gateway", gateway_cmd)
            os.close(log_fd)
            logger.info("OpenClaw gateway starting in a separate Windows console (PID %d)...", _gateway_proc.pid)
            logger.info("Gateway console shows live output")
        else:
            log_fh = os.fdopen(log_fd, "w", encoding="utf-8", errors="replace")
            _gateway_proc = subprocess.Popen(gateway_cmd, stdout=log_fh, stderr=log_fh)
            logger.info("OpenClaw gateway starting (PID %d)...", _gateway_proc.pid)
            logger.info("Gateway log: %s", log_path)

        wait_seconds = int(os.environ.get("OPENCLAW_GATEWAY_WAIT_SECONDS", "10"))
        # Keep startup short by default; increase OPENCLAW_GATEWAY_WAIT_SECONDS if a machine needs more browser warmup time.
        logger.info("Waiting %d seconds for browser service to initialise...", wait_seconds)
        for i in range(wait_seconds):
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
    chart_cfg = s.get("chart", {})
    import datetime
    today_idx = datetime.datetime.now().weekday()
    if today_idx in (2, 3):
        dynamic_symbol = "SENSEX"
        dynamic_name = "SENSEX"
    elif today_idx in (0, 1, 4):
        dynamic_symbol = "NIFTY"
        dynamic_name = "NIFTY 50"
    else:
        dynamic_symbol = "MARKET_CLOSED"
        dynamic_name = "Market closed"

    chart_symbol = dynamic_symbol
    index_display_name = dynamic_name
    index_timeframe = str(chart_cfg.get("index_timeframe", s.get("direction", {}).get("timeframe", "15 min"))).strip()
    option_strike = chart_cfg.get("option_strike", "ATM")
    option_timeframe = str(chart_cfg.get("option_timeframe", s.get("entry", {}).get("timeframe", "3 min"))).strip()
    ce_target = f"{chart_symbol} ATM CE"
    pe_target = f"{chart_symbol} ATM PE"

    if platform.lower() == "upstox":
        platform_name = "Upstox"
        login_url = "https://login.upstox.com"
        post_login_url = chart_cfg.get("url", "https://pro.upstox.com/trading-charts")
        initial_url = post_login_url
        success_indicators = "dashboard, holdings, positions, portfolio, funds, or orders"
    else:
        platform_name = "Zerodha"
        login_url = "https://kite.zerodha.com"
        post_login_url = login_url
        initial_url = login_url
        success_indicators = "dashboard, holdings, or positions"

    lines = []
    lines.append("OpenClaw Automated Options Strategy — Final Developer Version")
    lines.append("=" * 70)
    lines.append("")

    lines.append("YOUR ROLE")
    lines.append("-" * 40)
    lines.append(f"You are an automated intraday options trading agent for {platform_name}.")
    lines.append("You are also the project programmer/operator for this bot.")
    lines.append("You run in two sessions per day. All trades are simulated/dummy only.")
    lines.append("You communicate with the user via Telegram for login and status.")
    lines.append("Live Telegram group replies are mirrored into prompts/telegram_inbox.txt by the runtime.")
    lines.append(f"Use OpenClaw's own tool/browser environment to open Chrome and inspect {platform_name}.")
    lines.append("")

    lines.append("DUMMY-ONLY EXECUTION SAFETY")
    lines.append("-" * 40)
    lines.append("This bot is for chart monitoring and dummy Telegram/log messages only.")
    lines.append("Never place, modify, cancel, square off, or confirm a real broker order.")
    lines.append("Never click real Buy, Sell, Order, Basket, Modify, Exit, Square-off, Submit, Confirm, or Place Order controls.")
    lines.append("If a real order window, order ticket, confirmation popup, or position exit screen appears, close/cancel it and send a Telegram safety alert.")
    lines.append("Treat strategy words like buy, sell, entry, exit, square-off, order, and execution as simulated signal events only.")
    lines.append("Use the broker website only to inspect login state, charts, watchlists, prices, indicators, and account-visible data needed for dummy calculations.")
    lines.append("Do not use broker trading APIs or browser actions to submit real trades under any condition.")
    lines.append("")

    lines.append("PROGRAMMER / AUTO-FIX ROLE")
    lines.append("-" * 40)
    lines.append("If a runtime error, command failure, browser automation issue, missing config, or recoverable setup problem occurs, diagnose it and make the smallest safe fix.")
    lines.append("After fixing, rerun the failed command or browser step to verify the fix before continuing.")
    lines.append("Never write real credentials, tokens, or API keys into tracked files; ask the user via Telegram if a secret is required.")
    lines.append("Do not change the trading strategy rules unless the user explicitly asks.")
    lines.append("Do not call curl, Telegram sendMessage, or read Telegram config from any path, including config/telegram.json or ~/.openclaw/workspace/config/telegram.json.")
    lines.append("To request a Telegram status message, append one short line to prompts/openclaw_telegram_outbox.txt; Python will send and dedupe it.")
    lines.append("Request Telegram status messages for market condition, login/user action, dummy trade, and final verification updates only.")
    lines.append("After each successful chart diagnosis, write prompts/chart_signal.json with the latest observed browser-derived signal; Python will not create dummy entries from random data.")
    lines.append("Do not request Telegram messages for transient technical browser/tool retry errors such as browser page reads, Chrome DevTools reads, selector syntax, DOM inspection, cleanup tabs, or retry diagnostics; log/fix them silently and continue.")
    lines.append("")

    lines.append("TELEGRAM GROUP INPUT")
    lines.append("-" * 40)
    lines.append("The Python runtime polls the configured Telegram group every 1 second and appends new messages to prompts/telegram_inbox.txt.")
    lines.append("Check prompts/telegram_inbox.txt whenever waiting for login, chart selection, STOP/WAIT commands, or user assistance.")
    lines.append("Before every browser/chart action, check prompts/telegram_priority_inbox.txt and prompts/runtime_control.json; Telegram user instructions have priority.")
    lines.append("If prompts/runtime_control.json command is stop, stop browser/chart work and exit. If command is pause, block new dummy entries until resume. If command is quiet, keep monitoring and avoid Telegram technical error noise.")
    lines.append("Treat new Telegram group messages as user instructions unless they request unsafe credential handling or unapproved strategy changes.")
    lines.append("")

    lines.append(f"STEP 1 — OPEN CHROME & CHECK {platform_name.upper()} LOGIN")
    lines.append("-" * 40)
    lines.append("CRITICAL: Use the OpenClaw-managed 'openclaw' browser profile, not the external 'user' profile.")
    lines.append("Do not wait on existing-session/user-profile attach; it can time out on Linux.")
    lines.append("1. Open the 'openclaw' browser profile using OpenClaw's browser tool.")
    lines.append(f"2. Reuse the active tab (or navigate the active tab directly) to go to {initial_url}.")
    lines.append(f"   CLI fallback: openclaw browser --browser-profile openclaw open {initial_url}")
    lines.append(f"3. Close any extra tabs (like 'New Tab' or 'about:blank') so only the {platform_name} page is open.")
    lines.append(f"4. Check if already logged in by looking for {success_indicators} content.")
    if platform_name == "Upstox":
        lines.append("5. If Trading Charts shows chart/watchlist/market data, treat Upstox as already logged in.")
        lines.append(f"6. If redirected to login or a login form is visible, navigate to {login_url}.")
        lines.append("7. Read the mobile number from config/upstox_login.json if present, use it only to fill the mobile/phone field, then click Continue/Get OTP/Proceed to request OTP.")
        lines.append("8. Do not store, type, or ask for the 6-digit PIN in chat, logs, files, or Telegram.")
        lines.append("9. After submitting the mobile number, wait for the user to enter OTP manually.")
        lines.append("10. If a PIN screen appears, request Telegram status 'Please enter the Upstox PIN in the opened Chrome window.' through prompts/openclaw_telegram_outbox.txt. Then wait while the user enters it manually.")
        lines.append("11. If the user is clicking, selecting a Chrome profile, or entering login details, wait and do not interrupt.")
        lines.append("12. Recheck the page every 5 seconds until Upstox login is confirmed.")
        lines.append(f"13. Once logged in, request Telegram status '{platform_name} login confirmed!' through prompts/openclaw_telegram_outbox.txt.")
        lines.append(f"14. After login, navigate to {post_login_url}.")
        lines.append(f"15. Ensure the right pane is the {index_display_name} {index_timeframe} chart.")
        lines.append(f"16. Diagnose the crossover strategy on the {index_display_name} {index_timeframe} chart using only fully closed candles: bullish requires previous closed candle 5 EMA <= 20 EMA and latest closed candle 5 EMA > 20 EMA; bearish requires previous closed candle 5 EMA >= 20 EMA and latest closed candle 5 EMA < 20 EMA.")
        lines.append(f"17. In the left side sidebar, find {index_display_name} and click the icon that shows the option chain.")
        lines.append(f"18. In the option chain, locate the nearest ATM strike to the live {index_display_name} spot LTP, using the current/nearest weekly expiry unless the user specifies otherwise. If ATM or expiry is unclear, ask via Telegram before selecting another strike or expiry.")
        lines.append(f"19. If {index_display_name} is bearish based on the crossover, select the ATM contract explicitly labeled PE. If bullish, select the ATM contract explicitly labeled CE. Treat left/right layout as a visual hint only, not the source of truth.")
        lines.append(f"20. Once the call or put chart appears on the left, set it to {option_timeframe} and monitor only fully closed candles for an upward crossover where the previous closed candle has 5 EMA <= 20 EMA and the latest closed candle has 5 EMA > 20 EMA.")
        lines.append(f"21. When this specific upward premium-chart crossover happens according to the strategy, record a simulated/dummy entry only; never click broker order controls.")
        lines.append(f"22. Calculate and report the dummy entry price, ATM strike, selected expiry, 10% hard SL level, dynamic SL 2 to 3 points below entry, and 20% to 50% target level.")
        lines.append(f"23. Also locate both dynamic ATM premium charts for the selected strike: {ce_target} and {pe_target} on {option_timeframe}. After bias is known, actively refresh the eligible premium chart every 5-10 seconds for current premium price, SL, and target checks; refresh the opposite non-eligible side less often, about every 30-60 seconds, only for status.")
        lines.append(f"24. If {chart_symbol}, {ce_target}, {pe_target}, the ATM strike, or expiry cannot be found, ask the user via Telegram before clicking another chart symbol, strike, or expiry.")
    else:
        lines.append(f"5. If login page detected, request Telegram status 'Please log in to the opened Chrome window.' through prompts/openclaw_telegram_outbox.txt.")
        lines.append("6. If the user is clicking, selecting a Chrome profile, or entering login details, wait and do not interrupt.")
        lines.append("7. Recheck the page every 5 seconds until login is confirmed.")
        lines.append(f"8. Once logged in, request Telegram status '{platform_name} login confirmed!' through prompts/openclaw_telegram_outbox.txt.")
    lines.append("")

    lines.append("STEP 2 — REQUEST TELEGRAM MESSAGES")
    lines.append("-" * 40)
    lines.append("Never send Telegram directly from OpenClaw; do not use curl/sendMessage and do not read Telegram config from any path, including config/telegram.json or ~/.openclaw/workspace/config/telegram.json.")
    lines.append("Append one plain-text line per requested alert to prompts/openclaw_telegram_outbox.txt, for example:")
    lines.append("  printf '%s\\n' 'Upstox login confirmed!' >> prompts/openclaw_telegram_outbox.txt")
    lines.append("The Python runtime reads that outbox, sends Telegram, and suppresses repeated browser-read warnings.")
    lines.append("")

    lines.append("STRATEGY TYPE")
    lines.append("-" * 40)
    lines.append(s.get("strategy_type", "N/A"))
    lines.append("")

    if platform_name == "Upstox":
        lines.append("UPSTOX CHART TARGET")
        lines.append("-" * 40)
        lines.append(f"Trading Charts URL: {post_login_url}")
        lines.append(f"Configured chart symbol: {chart_symbol}")
        lines.append(f"Direction chart: {index_display_name} / {chart_symbol} on {index_timeframe}")
        lines.append(f"Premium chart CE target: {ce_target} on {option_timeframe}")
        lines.append(f"Premium chart PE target: {pe_target} on {option_timeframe}")
        lines.append(f"Inspect and diagnose BOTH CE and PE premium charts, but after the {index_display_name} {index_timeframe} bias is known, actively watch only the eligible side every 5-10 seconds for fresh premium price/SL/target updates. Check the opposite side about every 30-60 seconds for status only.")
        lines.append("Write chart diagnosis to prompts/chart_signal.json using JSON fields: timestamp, target_index, spot_ltp, atm_strike, expiry, index_bias, direction, ce_state, pe_state, entry_confirmed, entry_price or premium_price, current_price, dynamic_sl, hard_sl_price, target_price, exit_confirmed, exit_reason, exit_price, lots, lot_size.")
        lines.append("")

        lines.append("FAST BROWSER MODE")
        lines.append("-" * 40)
        lines.append("During active monitoring, minimize browser work so chart_signal.json is updated quickly and accurately.")
        lines.append("Do not reopen the option chain, navigate away from Trading Charts, or switch chart symbols unless ATM/expiry/bias is missing, stale, or changed.")
        lines.append(f"Keep the right pane fixed on the {index_display_name} {index_timeframe} chart and the left pane fixed on the eligible ATM premium {option_timeframe} chart after bias is known.")
        lines.append("For an active dummy trade, prioritize reading only the visible current premium price and immediately write chart_signal.json with current_price, timestamp, direction, SL/target levels, and exit status.")
        lines.append("Run full EMA diagnosis only on closed-candle boundaries or when the visible chart state changes; do not perform heavy full-page/DOM inspection every fast cycle.")
        lines.append("If a browser read fails once, retry once silently. Use full recovery/navigation only after repeated failures or if the required chart is no longer visible.")
        lines.append("Do not send Telegram messages for routine fast-cycle reads; only request Telegram for market condition changes, login/user action, dummy entries/exits, and final verification.")
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
    if "strike" in s["strike_selection"]:
        lines.append(f"Strike: {s['strike_selection']['strike']}")
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
    lines.append("  - Dummy-only guard: block all real broker order placement/modify/cancel actions")
    lines.append("")

    lines.append("ALERT SYSTEM (Telegram)")
    lines.append("-" * 40)
    for alert in s['alerts']:
        lines.append(f"  - {alert}")
    lines.append("")

    lines.append("LOGGING SYSTEM")
    lines.append("-" * 40)
    for field in s.get('logging', []):
        lines.append(f"  - {field}")
    lines.append("")

    lines.append("STRATEGY FLOW")
    lines.append("-" * 40)
    for step in s.get('flow', []):
        lines.append(f"  - {step}")
    lines.append("")

    lines.append("INSTRUCTIONS")
    lines.append("-" * 40)
    lines.append("1. Open Chrome using OpenClaw's own browser/tool capability.")
    lines.append(f"2. Navigate to {initial_url} and check login state.")
    if platform_name == "Upstox":
        lines.append("3. If Trading Charts already has chart/watchlist/market data, treat login as confirmed.")
        lines.append(f"4. If not logged in, go to {login_url}, fill the mobile field from config/upstox_login.json when available, and click Continue/Get OTP/Proceed to request OTP.")
        lines.append("5. Wait for the user to enter OTP manually after OTP is requested.")
        lines.append("6. If a PIN screen appears, request a Telegram message through prompts/openclaw_telegram_outbox.txt and wait for the user to enter the PIN manually. Do not store or type the PIN.")
        lines.append("7. If the user is interacting with Chrome, wait without interrupting.")
        lines.append(f"8. Recheck every 5 seconds until {platform_name.lower()} dashboard/holdings/trading chart data is detected.")
        lines.append("9. Once logged in, request Telegram confirmation through prompts/openclaw_telegram_outbox.txt.")
        lines.append(f"10. Navigate to {post_login_url} and open Trading Charts.")
        lines.append(f"11. Select the {index_display_name} / {chart_symbol} index chart on {index_timeframe} and diagnose 5 EMA vs 20 EMA direction first using fully closed candles only.")
        lines.append(f"12. Locate nearest ATM strike to live {index_display_name} spot LTP in the option chain, use current/nearest weekly expiry unless user specifies otherwise, then open/locate and diagnose BOTH premium charts: {ce_target} on {option_timeframe} and {pe_target} on {option_timeframe}. After bias is known, keep the eligible side visible and actively refresh only that visible chart every 5-10 seconds for current price/SL/target checks; refresh the non-eligible side about every 30-60 seconds for status only.")
        lines.append(f"13. Report the current {index_display_name} {index_timeframe} bias, selected ATM strike/expiry, and both CE/PE premium-chart states through prompts/openclaw_telegram_outbox.txt only when genuinely observed from the browser.")
        lines.append(f"14. Write prompts/chart_signal.json after every diagnosis. Use entry_confirmed true only when the {index_display_name} {index_timeframe} bias and the matching premium chart closed-candle EMA crossover are both confirmed from the browser.")
        lines.append(f"15. If the {index_display_name} {index_timeframe} bias is bullish, only the CE premium chart can produce a dummy entry; if bearish, only the PE premium chart can produce a dummy entry. Still diagnose the opposite side and report it as not eligible.")
        lines.append("16. Ask the user via Telegram if any required chart symbol, ATM strike, or expiry cannot be found; do not substitute a different strike, expiry, or symbol without confirmation.")
        next_step = 17
    else:
        lines.append("3. If not logged in, request a Telegram login message through prompts/openclaw_telegram_outbox.txt.")
        lines.append("4. If the user is interacting with Chrome, wait without interrupting.")
        lines.append(f"5. Recheck every 5 seconds until {platform_name.lower()} dashboard/holdings is detected.")
        lines.append("6. Once logged in, request Telegram confirmation through prompts/openclaw_telegram_outbox.txt.")
        next_step = 7
    lines.append(f"{next_step}. All trades are simulated/dummy only. Monitor EMA crossover strategy and send dummy Telegram/log events only.")
    session_text = "; ".join(
        f"{session['start']}-{session['end']} (max {session['max_trades']})"
        for session in s['sessions']
    )
    lines.append(f"{next_step + 1}. Sessions: {session_text}.")
    lines.append(f"{next_step + 2}. By 15:15, close any dummy active position in logs/Telegram only; do not square off real broker positions.")
    lines.append(f"{next_step + 3}. Request Telegram alerts for every event (entry, exit, SL, target) through prompts/openclaw_telegram_outbox.txt.")
    lines.append(f"{next_step + 4}. Use OpenClaw for browser operations and shell only for local file checks or writing prompts/openclaw_telegram_outbox.txt.")
    lines.append(f"{next_step + 5}. If errors occur, act as programmer/operator: fix safely, rerun, verify, and request status through prompts/openclaw_telegram_outbox.txt.")
    lines.append(f"{next_step + 6}. Read prompts/telegram_priority_inbox.txt first, then prompts/telegram_inbox.txt, while waiting or before each browser/chart action.")

    if arch_doc_content:
        lines.append("")
        lines.append("ARCHITECTURE REFERENCE")
        lines.append("=" * 70)
        lines.append(arch_doc_content)

    content = "\n".join(lines)
    with open(PROMPT_FILE, "w", encoding="utf-8") as f:
        f.write(content)
    logger.info("Prompt saved to %s (%d lines)", PROMPT_FILE, len(lines))

    # Also copy to the OpenClaw agent workspace so its tools can find it
    ws_dir = os.path.expanduser("~/.openclaw/workspace/prompts")
    ws_file = os.path.join(ws_dir, "strategy_prompt.txt")
    try:
        os.makedirs(ws_dir, exist_ok=True)
        with open(ws_file, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info("Prompt also written to %s", ws_file)
        _sync_telegram_config_to_workspace()
        if platform.lower() == "upstox":
            _sync_upstox_login_config_to_workspace()
    except Exception as e:
        logger.warning("Could not write prompt to workspace: %s", e)

    return PROMPT_FILE


def run_openclaw_agent(task_message, timeout_seconds=None, platform="Zerodha"):
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
        logger.info("OpenClaw will open Chrome, navigate to %s, and wait for your login.", platform)
        logger.info("Please log in when Chrome opens. OpenClaw detects login automatically.")
        print("\n" + "=" * 60)
        print(" OpenClaw Trading Agent starting — Chrome will open shortly")
        print(" Log in to Zerodha/Upstox when prompted.")
        if _is_linux():
            print(" OpenClaw TUI will run in a separate terminal on Linux.")
        elif _is_windows():
            print(" OpenClaw TUI will run in a separate Windows console.")
        else:
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

        if _is_linux():
            exit_fd, exit_code_path = tempfile.mkstemp(prefix="openclaw_agent_exit_", suffix=".txt")
            os.close(exit_fd)
            log_fd, log_path = tempfile.mkstemp(prefix="openclaw_agent_", suffix=".log")
            os.close(log_fd)
            proc, _ = _launch_linux_terminal(
                "OpenClaw TUI",
                cmd,
                exit_code_path=exit_code_path,
                log_path=log_path,
                hold_on_exit=True,
            )
            if proc:
                logger.info("OpenClaw TUI launched in a separate Linux terminal (PID %d)", proc.pid)
                logger.info("OpenClaw TUI log: %s", log_path)
            else:
                proc = subprocess.Popen(cmd, start_new_session=True)  # no PIPE — inherits TTY
        elif _is_windows():
            exit_fd, exit_code_path = tempfile.mkstemp(prefix="openclaw_agent_exit_", suffix=".txt")
            os.close(exit_fd)
            log_fd, log_path = tempfile.mkstemp(prefix="openclaw_agent_", suffix=".log")
            os.close(log_fd)
            proc, _ = _launch_windows_console(
                "OpenClaw TUI",
                cmd,
                exit_code_path=exit_code_path,
                log_path=log_path,
                hold_on_exit=True,
            )
            logger.info("OpenClaw TUI launched in a separate Windows console (PID %d)", proc.pid)
            logger.info("OpenClaw TUI log: %s", log_path)
        else:
            exit_code_path = None
            # Inherit the full terminal (stdin/stdout/stderr) so the TUI renders properly
            proc = subprocess.Popen(cmd, start_new_session=True)  # no PIPE — inherits TTY

        _agent_proc = proc

        # Wait until the agent finishes or Telegram STOP is written to runtime_control.json.
        while proc.poll() is None:
            if _runtime_stop_requested():
                logger.info("Telegram STOP detected; terminating OpenClaw agent process")
                _terminate_process(proc)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    _kill_process(proc)
                break
            time.sleep(1)
        rc = proc.returncode
        if exit_code_path and os.path.isfile(exit_code_path):
            try:
                with open(exit_code_path, encoding="utf-8") as f:
                    rc = int(f.read().strip())
            except Exception:
                pass

        if rc == 0:
            logger.info("OpenClaw agent completed successfully")
        else:
            logger.warning("OpenClaw agent exit code %d", rc)

        _agent_proc = None
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
    global _gateway_proc, _agent_proc
    if _agent_proc:
        logger.info("Stopping OpenClaw agent process")
        _terminate_process(_agent_proc)
        try:
            _agent_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _kill_process(_agent_proc)
        _agent_proc = None

    _stop_stray_openclaw_agent_processes()

    if _gateway_proc:
        _terminate_process(_gateway_proc)
        try:
            _gateway_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _kill_process(_gateway_proc)
        _gateway_proc = None
        logger.info("OpenClaw gateway stopped")


def _terminate_process(proc):
    try:
        if os.name != "nt":
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        else:
            proc.terminate()
    except Exception:
        try:
            proc.terminate()
        except Exception:
            pass


def _kill_process(proc):
    try:
        if os.name != "nt":
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        else:
            proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _stop_stray_openclaw_agent_processes():
    if os.name == "nt":
        return
    patterns = (
        "openclaw agent --local --agent main",
        "openclaw gateway run --port 18789",
    )
    for pattern in patterns:
        try:
            subprocess.run(["pkill", "-TERM", "-f", pattern], capture_output=True, timeout=5)
        except Exception as e:
            logger.debug("Could not stop stray OpenClaw process %s: %s", pattern, e)
