import contextlib
import ctypes
import itertools
import json
import os
import select
import shutil
import subprocess
import sys
import time
import shlex
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, time as dt_time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

LOG_TIMESTAMP_FORMAT = "%H:%M:%S"
ANSI_RESET = "\033[0m"
ANSI_GREEN = "\033[32m"
ANSI_ORANGE = "\033[38;5;208m"
ANSI_GREY = "\033[90m"
NEW_YORK_TZ = ZoneInfo("America/New_York")
AEST_TZ = ZoneInfo("Australia/Sydney")
SESSION_PRESETS: Dict[str, Tuple[str, str]] = {
    "ny": ("09:25", "10:00"),
    "lon": ("03:00", "11:30"),
    "asia": ("19:00", "03:00"),
}


def resolve_config_path() -> Path:
    if getattr(sys, "frozen", False):
        exe_path = Path(sys.executable).resolve()
        candidate = exe_path.with_name(f"{exe_path.stem}.json")
        if candidate.exists():
            return candidate
        fallback = exe_path.parent / "tv_downloader.json"
        if fallback.exists():
            return fallback

    script_path = Path(__file__).resolve()
    candidate = script_path.with_suffix(".json")
    if candidate.exists():
        return candidate

    return Path.cwd() / "tv_downloader.json"



from helium import set_driver
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException, WebDriverException

CONFIG_PATH = resolve_config_path()
DOWNLOADS_DIR = Path.home() / "Downloads"
REMOTE_DEBUG_ADDRESS = os.getenv("REMOTE_DEBUG_ADDRESS", "127.0.0.1:9222")
REMOTE_DEBUG_PROFILE_DIR = Path.home() / "Library" / "Application Support" / "Google" / "RemoteDebugProfile"
SAVE_MENU_SELECTOR = "[data-name='save-load-menu']"
SAVE_MENU_XPATH = (
    "/html/body/div[2]/div/div[3]/div/div/div[3]/div[1]/div/div/div/div/div[14]"
    "/div/div/div/button"
)
EXPORT_MENU_CSS = "#overlap-manager-root div.menu-yyMUOAN9 div div div:nth-child(6)"
EXPORT_MENU_XPATH = (
    "//div[@data-role='menuitem' and .//span[contains(normalize-space(.), 'Export chart data')]]"
)
EXPORT_CONFIRM_SELECTOR = "[data-name='submit-button']"
EXPORT_DIALOG_SELECTOR = "[data-dialog-name='Export chart data']"
UI_READY_TIMEOUT = 10


#
# before launching this app, run this in the terminal in order for it to work...
#
# brew reinstall --cask chromedriver --no-quarantine
#
# CHROMEDRIVER_PATH=$(which chromedriver) 
# export CHROMEDRIVER_PATH="/opt/homebrew/bin/chromedriver"
# export PATH="/opt/homebrew/bin:$PATH"



#guy@Mac ~ % open -na "Google Chrome" --args \      
#  --remote-debugging-port=9222 \
#  --user-data-dir="$HOME/Library/Application Support/Google/RemoteDebugProfile"
#
#guy@Mac ~ % curl http://127.0.0.1:9222/json/version
#


@dataclass
class ChartConfig:
    name: str
    export_prefix: str
    save_paths: List[Path]
    url: str


def load_chart_configs(path: Path) -> List[ChartConfig]:
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")

    with path.open("r", encoding="utf-8") as config_file:
        raw_configs = json.load(config_file)

    charts: List[ChartConfig] = []
    for raw in raw_configs:
        charts.append(
            ChartConfig(
                name=raw["name"],
                export_prefix=raw["export_prefix"],
                save_paths=_parse_save_paths(raw),
                url=raw["url"],
            )
        )
    return charts


def log_stage(prefix: str, message: str) -> None:
    timestamp = datetime.now().strftime(LOG_TIMESTAMP_FORMAT)
    print(f"[{timestamp}] {prefix} {message}")


def enable_virtual_terminal_processing() -> bool:
    if not sys.stdout.isatty():
        return False
    if os.name != "nt":
        return True

    try:
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        if handle in (0, -1):
            return False
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        enable_virtual_terminal = 0x0004  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        disable_auto_return = 0x0008  # DISABLE_NEWLINE_AUTO_RETURN
        new_mode = mode.value | enable_virtual_terminal | disable_auto_return
        if not kernel32.SetConsoleMode(handle, new_mode):
            return False
        return True
    except Exception as exc:  # pragma: no cover - best effort for Windows console
        log_stage("console", f"ANSI enable failed: {exc}")
        return False


def run_osascript(commands: List[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["osascript", *itertools.chain.from_iterable(("-e", cmd) for cmd in commands)],
        check=True,
        text=True,
        capture_output=True,
    )


def get_frontmost_app() -> Optional[str]:
    try:
        result = run_osascript(
            [
                'tell application "System Events" to get name of first application process whose frontmost is true'
            ]
        )
        app_name = result.stdout.strip()
        return app_name or None
    except subprocess.CalledProcessError as exc:
        log_stage("focus", f"Failed to determine frontmost application: {exc.stderr.strip()}")
    except Exception as exc:  # pragma: no cover - defensive
        log_stage("focus", f"Unexpected error determining frontmost application: {exc}")
    return None


def activate_app(app_name: str) -> bool:
    if not app_name:
        return False
    escaped = app_name.replace('"', '\\"')
    try:
        run_osascript([f'tell application "{escaped}" to activate'])
        log_stage("focus", f"Activated '{app_name}'.")
        return True
    except subprocess.CalledProcessError as exc:
        log_stage("focus", f"Failed to activate '{app_name}': {exc.stderr.strip()}")
        return False
    except Exception as exc:  # pragma: no cover - defensive
        log_stage("focus", f"Unexpected error activating '{app_name}': {exc}")
        return False


def get_remote_browser_version(address: str) -> Optional[str]:
    host, _, port = address.partition(":")
    if not host or not port:
        return None

    url = f"http://{host}:{port}/json/version"
    try:
        with contextlib.closing(urllib.request.urlopen(url, timeout=2)) as response:
            payload = json.load(response)
    except OSError:
        return None

    browser = payload.get("Browser") or payload.get("browser")
    if isinstance(browser, str) and "/" in browser:
        return browser.split("/", 1)[1]
    return None


def build_service(browser_version: Optional[str] = None, force_download: bool = False) -> Service:
    env_path = os.getenv("CHROMEDRIVER_PATH")
    if env_path:
        if not Path(env_path).exists():
            raise RuntimeError(f"CHROMEDRIVER_PATH is set but file does not exist: {env_path}")
        return Service(executable_path=env_path)

    chromedriver_path = shutil.which("chromedriver")
    if chromedriver_path:
        return Service(executable_path=chromedriver_path)

    try:
        from webdriver_manager.chrome import ChromeDriverManager  # type: ignore
    except ImportError:
        raise RuntimeError(
            "Chromedriver not found. Install webdriver-manager or set CHROMEDRIVER_PATH."
        )

    manager_kwargs = {}
    if browser_version:
        manager_kwargs["driver_version"] = browser_version

    try:
        if force_download:
            driver_manager = ChromeDriverManager()
            driver_path = driver_manager.install()
        else:
            driver_path = ChromeDriverManager(**manager_kwargs).install()
    except ValueError:
        driver_path = ChromeDriverManager().install()
    try:
        Path(driver_path).chmod(0o755)
    except OSError:
        pass

    return Service(executable_path=driver_path)


def is_debugger_available(address: str, timeout_seconds: float = 1.0) -> bool:
    host, _, port = address.partition(":")
    if not host or not port:
        return False

    url = f"http://{host}:{port}/json/version"
    try:
        with contextlib.closing(urllib.request.urlopen(url, timeout=timeout_seconds)):
            return True
    except OSError:
        return False


def wait_for_debugger(address: str, timeout_seconds: int = 15) -> None:
    host, _, port = address.partition(":")
    if not host or not port:
        raise ValueError(f"REMOTE_DEBUG_ADDRESS '{address}' must be in host:port format.")

    url = f"http://{host}:{port}/json/version"
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with contextlib.closing(urllib.request.urlopen(url, timeout=2)):
                log_stage("driver", f"Debugger reachable at {address}.")
                return
        except OSError:
            time.sleep(0.5)
            log_stage("driver", f"Waiting for debugger at {address} ...")

    message = (
        f"Chrome debugger not reachable at {address}. "
        "Start Chrome with --remote-debugging-port and ensure the port matches."
    )
    log_stage("driver", message)
    raise RuntimeError(message)


def launch_remote_debug_chrome() -> None:
    if is_debugger_available(REMOTE_DEBUG_ADDRESS):
        print("Chrome remote-debugger already running.")
        return

    host, _, port = REMOTE_DEBUG_ADDRESS.partition(":")
    if not host or not port:
        raise ValueError(
            f"REMOTE_DEBUG_ADDRESS '{REMOTE_DEBUG_ADDRESS}' must be in host:port format."
        )

    REMOTE_DEBUG_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    chrome_command = [
        "open",
        "-na",
        "Google Chrome",
        "--args",
        f"--remote-debugging-port={port}",
        f"--user-data-dir={REMOTE_DEBUG_PROFILE_DIR}",
    ]
    try:
        subprocess.run(chrome_command, check=True)
    except FileNotFoundError as exc:
        raise RuntimeError("macOS 'open' command not found while launching Chrome.") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError("Failed to launch Google Chrome with remote debugging enabled.") from exc

    print("Launching Chrome with remote debugging (this can take a moment)...")
    time.sleep(1.5)
    wait_for_debugger(REMOTE_DEBUG_ADDRESS, timeout_seconds=25)
    print("Chrome remote-debugger ready.")


def attach_driver() -> webdriver.Chrome:
    log_stage("driver", f"Waiting for debugger at {REMOTE_DEBUG_ADDRESS}.")
    wait_for_debugger(REMOTE_DEBUG_ADDRESS)
    log_stage("driver", "Debugger ready. Fetching remote browser version.")
    browser_version = get_remote_browser_version(REMOTE_DEBUG_ADDRESS)
    if browser_version:
        log_stage("driver", f"Remote browser version reported as {browser_version}.")
    else:
        log_stage("driver", "Remote browser version unavailable; using default driver resolution.")
    options = Options()
    options.add_experimental_option("debuggerAddress", REMOTE_DEBUG_ADDRESS)

    last_error: Optional[Exception] = None
    for force_download in (False, True):
        service = None
        try:
            action = "existing driver" if not force_download else "fresh download"
            log_stage("driver", f"Attempting to start ChromeDriver using {action}.")
            service = build_service(
                browser_version=browser_version, force_download=force_download
            )
            driver = webdriver.Chrome(service=service, options=options)
            ensure_window_geometry(driver)
            log_stage("driver", "ChromeDriver session established.")
            return driver
        except WebDriverException as exc:
            last_error = exc
            log_stage("driver", f"Driver start failed ({exc}).")
            if service is not None:
                with contextlib.suppress(Exception):
                    service.stop()
            if "Can not connect to the Service" in str(exc) and not force_download:
                log_stage("driver", "Retrying ChromeDriver setup with fresh download due to connection failure.")
                continue
            raise
        except Exception as exc:  # pragma: no cover - defensive
            last_error = exc
            log_stage("driver", f"Unexpected driver error ({exc}).")
            if service is not None:
                with contextlib.suppress(Exception):
                    service.stop()
            if not force_download:
                continue
            raise

    if last_error is not None:
        log_stage("driver", f"Failed to attach driver: {last_error}")
        raise last_error
    raise RuntimeError("Failed to attach driver for unknown reasons.")


def ensure_window_geometry(driver: webdriver.Chrome, *, x: int = 0, y: int = 0, width: int = 1920, height: int = 1080) -> None:
    try:
        driver.set_window_position(x, y)
    except Exception as exc:
        log_stage("window", f"Failed to set window position: {exc}")
    try:
        driver.set_window_size(width, height)
    except Exception as exc:
        log_stage("window", f"Failed to set window size: {exc}")


def wait_for_page_ready(driver: webdriver.Chrome, timeout_seconds: int = 20) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if driver.execute_script("return document.readyState") == "complete":
            return
        time.sleep(0.2)
    raise RuntimeError("TradingView page did not finish loading in time.")


def wait_for_menu_ready(driver: webdriver.Chrome) -> None:
    wait = WebDriverWait(driver, UI_READY_TIMEOUT)

    def menu_present(_driver: webdriver.Chrome) -> bool:
        try:
            _driver.switch_to.default_content()
        except Exception:
            pass
        return bool(_driver.find_elements(By.CSS_SELECTOR, SAVE_MENU_SELECTOR))

    wait.until(menu_present)


def canonicalize_url(url: str) -> str:
    parsed = urlsplit(url)
    normalized_path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme, parsed.netloc, normalized_path, parsed.query, ""))


def switch_to_existing_tab(driver: webdriver.Chrome, target_url: str) -> bool:
    target = canonicalize_url(target_url)
    current_handle = driver.current_window_handle if driver.window_handles else None

    for handle in driver.window_handles:
        try:
            driver.switch_to.window(handle)
        except Exception:
            continue
        try:
            current_url = canonicalize_url(driver.current_url)
        except Exception:
            continue
        if current_url == target:
            try:
                driver.execute_script("window.focus();")
            except Exception:
                pass
            return True

    if current_handle:
        try:
            driver.switch_to.window(current_handle)
        except Exception:
            pass
    return False


def ensure_chart_tab(
    driver: webdriver.Chrome, target_url: str, log_prefix: Optional[str] = None
) -> bool:
    if switch_to_existing_tab(driver, target_url):
        if log_prefix:
            log_stage(log_prefix, "Reusing existing chart tab.")
        return True

    if log_prefix:
        log_stage(log_prefix, "Opening new tab for chart.")

    try:
        driver.switch_to.new_window("tab")
    except Exception:
        driver.execute_script("window.open('about:blank','_blank');")
        driver.switch_to.window(driver.window_handles[-1])

    driver.get(target_url)
    return False


def _minutes_since_midnight(value: dt_time) -> int:
    return value.hour * 60 + value.minute


def _within_window(candidate: dt_time, start_time: Optional[dt_time], end_time: Optional[dt_time]) -> bool:
    if start_time is None and end_time is None:
        return True

    candidate_minutes = _minutes_since_midnight(candidate)
    start_minutes = _minutes_since_midnight(start_time) if start_time else None
    end_minutes = _minutes_since_midnight(end_time) if end_time else None

    if start_minutes is not None and end_minutes is not None:
        if start_minutes == end_minutes:
            return True
        if start_minutes < end_minutes:
            return start_minutes <= candidate_minutes <= end_minutes
        return candidate_minutes >= start_minutes or candidate_minutes <= end_minutes

    if start_minutes is not None:
        return candidate_minutes >= start_minutes
    if end_minutes is not None:
        return candidate_minutes <= end_minutes
    return True


def next_loop_timestamp(
    now: datetime,
    start_time: Optional[dt_time] = None,
    end_time: Optional[dt_time] = None,
    tz: Optional[ZoneInfo] = None,
) -> datetime:
    tz = tz or now.tzinfo or NEW_YORK_TZ
    if now.tzinfo is None:
        now = now.replace(tzinfo=tz)
    else:
        now = now.astimezone(tz)

    candidate = now.replace(second=50, microsecond=0)
    if candidate <= now:
        candidate = (candidate + timedelta(minutes=1)).replace(second=50, microsecond=0)

    for _ in range(2 * 24 * 60):
        if _within_window(candidate.time(), start_time, end_time):
            return candidate
        candidate = (candidate + timedelta(minutes=1)).replace(second=50, microsecond=0)

    raise RuntimeError("Unable to find the next loop timestamp within the configured window.")


def parse_time_of_day(value: str) -> dt_time:
    text = value.strip().lower()
    if not text:
        raise ValueError("Time value is empty.")

    # Allow optional trailing timezone hint like "ny" or "et"
    for suffix in ("ny", "et", "est", "edt"):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
            break

    text = text.replace(" ", "")

    patterns = ("%I:%M%p", "%I%p", "%H:%M", "%H")
    for pattern in patterns:
        try:
            parsed = datetime.strptime(text, pattern)
            return parsed.time().replace(second=0, microsecond=0)
        except ValueError:
            continue

    raise ValueError(f"Unable to parse time value '{value}'. Expected formats like 09:55 or 9:55am.")


def find_clickable_element(
    driver: webdriver.Chrome,
    locator: Tuple[str, str],
    main_timeout: int = 10,
    frame_timeout: int = 5,
) -> WebElement:
    driver.switch_to.default_content()
    try:
        return WebDriverWait(driver, main_timeout).until(EC.element_to_be_clickable(locator))
    except TimeoutException:
        frames = driver.find_elements(By.TAG_NAME, "iframe")
        for frame in frames:
            driver.switch_to.default_content()
            driver.switch_to.frame(frame)
            try:
                return WebDriverWait(driver, frame_timeout).until(
                    EC.element_to_be_clickable(locator)
                )
            except TimeoutException:
                continue
    driver.switch_to.default_content()
    raise TimeoutException(f"Element {locator} not clickable in current context.")


def find_save_menu_button(driver: webdriver.Chrome) -> WebElement:
    locators = [
        (By.CSS_SELECTOR, SAVE_MENU_SELECTOR),
        (By.XPATH, SAVE_MENU_XPATH),
    ]

    for locator in locators:
        try:
            return find_clickable_element(driver, locator, main_timeout=15)
        except TimeoutException:
            continue

    driver.switch_to.default_content()
    raise TimeoutException("Save/load menu button not found in page or iframes.")


def click_export_chart_data(driver: webdriver.Chrome) -> None:
    locators = [
        (By.CSS_SELECTOR, EXPORT_MENU_CSS),
        (By.XPATH, EXPORT_MENU_XPATH),
    ]

    for locator in locators:
        try:
            menu_item = find_clickable_element(driver, locator, main_timeout=10)
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", menu_item)
            driver.execute_script("arguments[0].click();", menu_item)
            return
        except TimeoutException:
            continue

    driver.switch_to.default_content()
    raise TimeoutException("Export chart data menu item not found.")


def click_export_confirm(driver: webdriver.Chrome) -> None:
    try:
        driver.switch_to.default_content()
    except Exception:
        pass

    WebDriverWait(driver, 12).until(
        EC.visibility_of_element_located((By.CSS_SELECTOR, EXPORT_DIALOG_SELECTOR))
    )

    try:
        button = find_clickable_element(
            driver,
            (By.CSS_SELECTOR, EXPORT_CONFIRM_SELECTOR),
            main_timeout=12,
            frame_timeout=6,
        )
    except TimeoutException as exc:
        driver.switch_to.default_content()
        raise TimeoutException("Export confirmation button not found or not clickable.") from exc

    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)

    def button_ready(_: webdriver.Chrome) -> bool:
        try:
            if not button.is_displayed():
                return False
            if not button.is_enabled():
                return False
            aria_disabled = button.get_attribute("aria-disabled")
            return aria_disabled not in ("true", "1")
        except StaleElementReferenceException:
            return False

    WebDriverWait(driver, 5).until(button_ready)
    time.sleep(0.2)
    attempts = []

    def record_failure(name: str, error: Exception) -> None:
        attempts.append(f"{name}: {error}")

    def try_click_sequence() -> bool:
        nonlocal button
        for name, action in (
            ("direct click", lambda: button.click()),
            ("js click", lambda: driver.execute_script("arguments[0].click();", button)),
        ):
            try:
                action()
                driver.switch_to.default_content()
                return True
            except Exception as err:  # noqa: PERF203 - debugging fallback
                record_failure(name, err)
        return False

    try:
        driver.execute_script("arguments[0].focus();", button)
    except Exception as err:
        record_failure("focus", err)

    for delay in (0.0, 0.25, 0.5):
        if delay:
            time.sleep(delay)
            try:
                WebDriverWait(driver, 3).until(button_ready)
            except TimeoutException:
                pass
        if try_click_sequence():
            return

    for delay, (name, action) in (
        (0.0, ("enter on button", lambda: button.send_keys(Keys.ENTER))),
        (
            0.2,
            (
                "enter on active element",
                lambda: driver.switch_to.active_element.send_keys(Keys.ENTER),
            ),
        ),
    ):
        if delay:
            time.sleep(delay)
        try:
            action()
            driver.switch_to.default_content()
            return
        except Exception as err:
            record_failure(name, err)

    driver.switch_to.default_content()
    raise TimeoutException(
        "Export confirmation button did not respond to click or keyboard actions. "
        f"Attempted: {attempts}"
    )


def latest_export(prefix: str) -> Path:
    candidates = sorted(
        DOWNLOADS_DIR.glob(f"{prefix}*.csv"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError(
            f"No export CSV found in {DOWNLOADS_DIR} matching prefix '{prefix}'."
        )
    return candidates[0]


def wait_for_export(
    prefix: str, timeout_seconds: int = 30, log_prefix: Optional[str] = None
) -> Path:
    deadline = time.time() + timeout_seconds
    last_size = None
    export_path: Path
    first_detection_logged = False

    while time.time() < deadline:
        try:
            export_path = latest_export(prefix)
        except FileNotFoundError:
            time.sleep(0.5)
            continue

        if export_path.suffix == ".crdownload" or export_path.name.endswith(".crdownload"):
            time.sleep(0.5)
            continue

        size = export_path.stat().st_size
        if size and size == last_size:
            if log_prefix:
                log_stage(
                    log_prefix,
                    f"Export download complete: {export_path.name} ({size} bytes).",
                )
            return export_path
        if size and log_prefix and not first_detection_logged:
            log_stage(
                log_prefix,
                f"Detected download: {export_path.name} ({size} bytes). Waiting for completion.",
            )
            first_detection_logged = True
        last_size = size
        time.sleep(0.5)

    if log_prefix:
        log_stage(
            log_prefix,
            f"Timed out waiting for exported file matching '{prefix}' after {timeout_seconds}s.",
        )
    raise TimeoutException(f"Export file matching '{prefix}' did not finish downloading in time.")


def _parse_save_paths(raw: Dict[str, object]) -> List[Path]:
    paths: List[str]
    if "save_paths" in raw:
        candidate = raw["save_paths"]
        if isinstance(candidate, list):
            paths = [str(path) for path in candidate]
        else:
            paths = [str(candidate)]
    elif "save_path" in raw:
        paths = [str(raw["save_path"])]
    else:
        raise KeyError("Chart configuration must include 'save_paths'.")
    return [Path(path) for path in paths]


def move_exported_file(
    prefix: str, destinations: Sequence[Path], log_prefix: Optional[str] = None
) -> None:
    if not destinations:
        raise ValueError("No destinations provided for exported file.")
    if log_prefix:
        log_stage(log_prefix, f"Waiting for exported file with prefix '{prefix}'.")
    export_file = wait_for_export(prefix, log_prefix=log_prefix)
    for destination in destinations:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(export_file, destination)
    try:
        export_file.unlink()
    except OSError as err:
        destinations_str = ", ".join(str(dest) for dest in destinations)
        print(f"{prefix}: copied to [{destinations_str}], but failed to remove '{export_file}': {err}")
    else:
        if log_prefix:
            dest_list = ", ".join(dest.name for dest in destinations)
            log_stage(log_prefix, f"Moved '{export_file.name}' to [{dest_list}].")
        else:
            print(f"{prefix}: moved '{export_file.name}' to destinations.")


def process_chart(chart: ChartConfig, driver: webdriver.Chrome) -> Tuple[bool, float, str]:
    prefix = chart.export_prefix
    log_stage(prefix, f"Starting export for {chart.name} ({chart.url}).")
    start_time = time.perf_counter()

    reused_tab = ensure_chart_tab(driver, chart.url, log_prefix=prefix)
    if reused_tab:
        log_stage(prefix, "Chart tab ready; continuing with existing session.")
    else:
        log_stage(prefix, "New chart tab opened.")

    log_stage(prefix, "Waiting for page readiness.")
    wait_for_page_ready(driver)
    log_stage(prefix, "Page ready. Waiting for save/load menu.")
    wait_for_menu_ready(driver)
    log_stage(prefix, "Save/load menu available.")

    success = False
    error_message = ""
    elapsed_ms = 0.0

    try:
        log_stage(prefix, "Locating save menu button.")
        button = find_save_menu_button(driver)
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
        driver.execute_script("arguments[0].click();", button)
        log_stage(prefix, "Save menu opened. Selecting 'Export chart data'.")
        click_export_chart_data(driver)
        log_stage(prefix, "Export dialog opened. Confirming export.")
        click_export_confirm(driver)
        move_exported_file(chart.export_prefix, chart.save_paths, log_prefix=prefix)
        success = True
    except TimeoutException as exc:
        error_message = f"timeout - {exc}"
    except Exception as exc:  # pylint: disable=broad-except
        error_message = f"failed with error - {exc}"
    finally:
        if driver is not None:
            try:
                driver.switch_to.default_content()
            except Exception:
                pass

    elapsed_ms = (time.perf_counter() - start_time) * 1000

    if success:
        log_stage(prefix, f"Export completed in {elapsed_ms:.0f} ms.")
    else:
        log_stage(prefix, f"Export failed after {elapsed_ms:.0f} ms - {error_message}")

    return success, elapsed_ms, error_message


def run(charts: Iterable[ChartConfig]) -> None:
    driver = attach_driver()
    set_driver(driver)

    metrics: List[float] = []

    try:
        for chart in charts:
            success, elapsed_ms, _ = process_chart(chart, driver)
            if success:
                metrics.append(elapsed_ms)
        if metrics:
            average_ms = sum(metrics) / len(metrics)
            print(f"Average runtime: {average_ms:.0f} ms across {len(metrics)} charts.")
    finally:
        if driver is not None:
            try:
                driver.switch_to.default_content()
            except Exception:
                pass


def interactive_session(charts: List[ChartConfig]) -> None:
    driver: Optional[webdriver.Chrome] = None

    def ensure_driver() -> webdriver.Chrome:
        nonlocal driver
        if driver is None:
            try:
                log_stage("driver", "No active driver. Attaching to Chrome debugger.")
                driver = attach_driver()
                set_driver(driver)
                log_stage("driver", "Chrome driver attached.")
            except Exception:
                driver = None
                raise
        return driver

    options: Dict[str, ChartConfig] = {
        str(index): chart for index, chart in enumerate(charts, start=1)
    }

    def debugger_ready() -> bool:
        if driver is not None:
            return True
        return is_debugger_available(REMOTE_DEBUG_ADDRESS)

    primary_app_name = get_frontmost_app()
    if primary_app_name:
        log_stage("focus", f"Primary application set to '{primary_app_name}'.")
    else:
        log_stage("focus", "Primary application could not be determined.")

    def refocus_primary_app(reason: str) -> None:
        if not primary_app_name:
            return
        log_stage("focus", f"Refocusing to '{primary_app_name}' ({reason}).")
        activate_app(primary_app_name)

    metrics: List[float] = []

    def print_overall_metrics() -> None:
        if metrics:
            avg_runtime = sum(metrics) / len(metrics)
            print(
                f"Overall average runtime: {avg_runtime:.0f} ms across {len(metrics)} chart runs."
            )

    def run_chart_batch(batch_keys: List[str], apply_geometry: bool = False) -> None:
        try:
            active_driver = ensure_driver()
        except Exception as exc:
            print(f"Failed to attach to Chrome: {exc}")
            if not is_debugger_available(REMOTE_DEBUG_ADDRESS):
                print("Hint: choose option 'l' first to launch Chrome with remote debugging.")
            return

        if apply_geometry:
            ensure_window_geometry(active_driver)

        if not batch_keys:
            log_stage("batch", "No charts selected in batch.")
            return

        batch_names = ", ".join(options[key].name for key in batch_keys)
        log_stage("batch", f"Starting batch for: {batch_names}")

        batch_metrics: List[float] = []
        for key in batch_keys:
            chart = options[key]
            success, elapsed_ms, _ = process_chart(chart, active_driver)
            if success:
                metrics.append(elapsed_ms)
                batch_metrics.append(elapsed_ms)

        if batch_metrics and len(batch_keys) > 1:
            avg_batch = sum(batch_metrics) / len(batch_metrics)
            print(f"Selection average runtime: {avg_batch:.0f} ms across {len(batch_metrics)} charts.")
        print_overall_metrics()
        log_stage("batch", f"Completed batch for: {batch_names}")
        refocus_primary_app("batch complete")

    def selection_description(run_all: bool, selected_keys: List[str]) -> str:
        if run_all:
            return "All charts"
        names = [options[key].name for key in selected_keys]
        return ", ".join(names)

    def build_menu_text(paused: bool, loop_state: Optional[Dict[str, object]]) -> str:
        if loop_state and not paused:
            status_text = "RUNNING"
            status_color = ANSI_GREEN
        elif paused:
            status_text = "PAUSED"
            status_color = ANSI_ORANGE
        else:
            status_text = "READY"
            status_color = ANSI_GREY
        lines: List[str] = [
            "",
            f"{status_color}[Status: {status_text}]{ANSI_RESET}",
            schedule_window_text(),
        ]
        if debugger_ready():
            lines.append(
                "Select chart numbers (comma-separated). Append '-loop' or '-l' to repeat every minute."
            )
            lines.extend(
                [
                    f"  {index}. {chart.name} ({chart.export_prefix})"
                    for index, chart in options.items()
                ]
            )
            lines.append("  a. Export all charts")
            lines.append("  l. Launch remote-debug Chrome window")
            lines.append("  p. Pause active loop")
            lines.append("  r. Resume active loop")
            lines.append("  s. Stop and reset loop")
            lines.append("  h. Show menu")
            lines.append("      Use '--session NAME' (NY, LON, ASIA) for presets.")
            lines.append("      Use '-start HH:MM' / '-end HH:MM' (Eastern) to adjust the loop window.")
        else:
            lines.append("Launch Chrome with remote debugging to enable exports:")
            lines.append("  l. Launch remote-debug Chrome window")
        lines.append("  x. Exit")
        lines.append("")
        lines.append("Enter option (comma-separated numbers, a, l, p, r, h, or x):")
        return "\n".join(lines)

    loop_state: Optional[Dict[str, object]] = None
    loop_start_time: Optional[dt_time] = None
    loop_end_time: Optional[dt_time] = None
    loop_session_name: Optional[str] = None
    paused = False
    menu_dirty = True
    status_line_active = False
    last_status_line = ""
    fallback_status_length = 0
    ansi_cursor_supported = enable_virtual_terminal_processing()
    if getattr(sys, "frozen", False) and ansi_cursor_supported:
        ansi_cursor_supported = False
        log_stage(
            "console",
            "Running as bundled executable; using carriage-return status updates for compatibility.",
        )
    if ansi_cursor_supported:
        log_stage("console", "ANSI cursor control enabled.")
    else:
        log_stage(
            "console",
            "ANSI cursor control unavailable; live countdown updates will log as separate lines.",
        )

    def invalidate_menu() -> None:
        nonlocal menu_dirty, status_line_active, last_status_line
        menu_dirty = True
        status_line_active = False
        last_status_line = ""

    def schedule_window_text() -> str:
        if loop_start_time or loop_end_time:
            start_text = loop_start_time.strftime("%H:%M") if loop_start_time else "--:--"
            end_text = loop_end_time.strftime("%H:%M") if loop_end_time else "--:--"
            details = f"Loop window (ET): {start_text} - {end_text}"
        else:
            details = "Loop window (ET): not set"
        if loop_session_name:
            details = f"{details} (session: {loop_session_name})"
        return details

    def format_status_line(current_time: datetime, remaining_seconds: Optional[float]) -> str:
        window_suffix = ""
        if loop_start_time or loop_end_time:
            window_suffix = f" | {schedule_window_text()}"
        base_message: str
        if loop_state:
            description = str(loop_state.get("description", "n/a"))
            next_run_obj = loop_state.get("next_run")
            if paused:
                if isinstance(next_run_obj, datetime):
                    base_message = (
                        f"Loop paused: {description} "
                        f"(scheduled at {next_run_obj.astimezone(NEW_YORK_TZ).strftime('%H:%M:%S')})"
                    )
                else:
                    base_message = f"Loop paused: {description}"
            elif isinstance(next_run_obj, datetime) and remaining_seconds is not None:
                remaining_int = max(0, int(remaining_seconds))
                base_message = (
                    f"Active loop: {description} "
                    f"(next run {next_run_obj.astimezone(NEW_YORK_TZ).strftime('%H:%M:%S')} in {remaining_int:02d}s)"
                )
            else:
                base_message = f"Active loop: {description} (next run n/a)"
        else:
            base_message = "No active loop scheduled."

        current_et = current_time.astimezone(NEW_YORK_TZ).strftime("%H:%M:%S")
        current_aest = current_time.astimezone(AEST_TZ).strftime("%H:%M:%S")
        time_suffix = f" | Time: {current_et} ET / {current_aest} AEST"
        full_message = f"{base_message}{window_suffix}{time_suffix}"

        columns = shutil.get_terminal_size((140, 24)).columns
        # Leave a little space so we do not wrap onto a new row when the console is narrow.
        max_len = max(20, columns - 2)
        if len(full_message) > max_len:
            full_message = full_message[: max_len - 3] + "..."
        return full_message

    def recalc_next_run() -> None:
        if loop_state is not None:
            loop_state["next_run"] = next_loop_timestamp(
                datetime.now(NEW_YORK_TZ),
                loop_start_time,
                loop_end_time,
                tz=NEW_YORK_TZ,
            )

    def strip_loop_suffix(token: str) -> Tuple[str, bool]:
        lower = token.lower()
        for suffix in ("-loop", "-l"):
            if lower.endswith(suffix) and len(token) > len(suffix):
                return token[: -len(suffix)], True
        return token, False

    def update_status_line(message: str) -> None:
        nonlocal last_status_line, fallback_status_length
        if not status_line_active:
            return
        if message == last_status_line:
            return
        if not ansi_cursor_supported:
            display = f"{message} | > "
            fallback_status_length = max(fallback_status_length, len(display))
            padding = " " * (fallback_status_length - len(display))
            sys.stdout.write("\r" + display + padding)
            sys.stdout.flush()
            last_status_line = message
            return
        sys.stdout.write("\x1b[s")  # save cursor
        sys.stdout.write("\x1b[F")  # move to beginning of previous line
        sys.stdout.write("\r")
        sys.stdout.write(message)
        sys.stdout.write("\x1b[K")
        sys.stdout.write("\x1b[u")  # restore cursor
        sys.stdout.flush()
        last_status_line = message

    try:
        while True:
            now = datetime.now(NEW_YORK_TZ)
            if loop_state and not paused:
                next_run_obj = loop_state.get("next_run")
                if isinstance(next_run_obj, datetime):
                    next_run_local = next_run_obj.astimezone(NEW_YORK_TZ)
                    if next_run_local <= now:
                        run_all = bool(loop_state.get("run_all"))
                        selected_keys = list(loop_state.get("selected_keys", []))  # type: ignore[arg-type]
                        log_stage("loop", f"Running scheduled selection: {loop_state['description']}")
                        if run_all:
                            run_chart_batch(list(options.keys()))
                        else:
                            run_chart_batch(selected_keys)
                        recalc_next_run()
                        updated_next = loop_state.get("next_run")
                        if isinstance(updated_next, datetime):
                            log_stage(
                                "loop",
                                f"Next run scheduled at {updated_next.astimezone(NEW_YORK_TZ).strftime('%H:%M:%S')}.",
                            )
                        invalidate_menu()
                        continue

            remaining_seconds: Optional[float] = None
            if loop_state and not paused:
                next_run_obj = loop_state.get("next_run")
                if isinstance(next_run_obj, datetime):
                    remaining_seconds = (next_run_obj.astimezone(NEW_YORK_TZ) - now).total_seconds()

            status_message = format_status_line(now, remaining_seconds)

            if menu_dirty:
                status_line_active = False
                print(build_menu_text(paused, loop_state))
                if ansi_cursor_supported:
                    print(status_message)
                    last_status_line = status_message
                    status_line_active = True
                    sys.stdout.write("> ")
                    sys.stdout.flush()
                else:
                    last_status_line = ""
                    status_line_active = True
                    fallback_status_length = 0
                    update_status_line(status_message)
                menu_dirty = False
            else:
                if ansi_cursor_supported:
                    update_status_line(status_message)
                elif status_line_active:
                    update_status_line(status_message)

            poll_timeout: Optional[float] = None
            if remaining_seconds is not None:
                if remaining_seconds <= 0:
                    continue
                poll_timeout = max(min(remaining_seconds, 1.0), 0.1)

            ready, _, _ = select.select([sys.stdin], [], [], poll_timeout)

            if not ready:
                # timeout expired (waiting for scheduled run)
                continue

            raw_line = sys.stdin.readline()
            if raw_line == "":
                print("EOF received. Exiting.")
                break

            raw_choice = raw_line.strip()
            if not raw_choice:
                invalidate_menu()
                continue

            log_stage("menu", f"Command received: {raw_choice}")

            try:
                tokens = shlex.split(raw_choice)
            except ValueError as exc:
                print(f"Invalid input: {exc}")
                invalidate_menu()
                continue

            if not tokens:
                invalidate_menu()
                continue

            single_token = tokens[0].lower()
            if len(tokens) == 1 and single_token in {"x", "h", "l", "p", "r", "s"}:
                if single_token == "x":
                    print("Exiting.")
                    break
                if single_token == "h":
                    invalidate_menu()
                    continue
                if single_token == "l":
                    if debugger_ready():
                        print("Chrome remote-debugger already running.")
                    else:
                        try:
                            launch_remote_debug_chrome()
                        except Exception as exc:
                            print(f"Failed to launch remote-debug Chrome: {exc}")
                        else:
                            refocus_primary_app("post Chrome launch")
                    invalidate_menu()
                    continue
                if single_token == "p":
                    if loop_state:
                        if paused:
                            print("Loop already paused.")
                        else:
                            paused = True
                            print("Loop paused.")
                    else:
                        print("No active loop to pause.")
                    invalidate_menu()
                    continue
                if single_token == "r":
                    if loop_state:
                        if not paused:
                            print("Loop already running.")
                        else:
                            paused = False
                            print("Loop resumed.")
                            recalc_next_run()
                    else:
                        print("No active loop to resume.")
                    invalidate_menu()
                    continue
                if single_token == "s":
                    loop_state = None
                    loop_start_time = None
                    loop_end_time = None
                    loop_session_name = None
                    paused = False
                    metrics.clear()
                    print("Loop stopped and schedule cleared.")
                    invalidate_menu()
                    continue

            loop_every_minute = False
            selection_tokens: List[str] = []
            start_option_set = False
            start_argument: Optional[str] = None
            end_option_set = False
            end_argument: Optional[str] = None
            session_option_set = False
            session_argument: Optional[str] = None
            schedule_valid = True

            idx = 0
            while idx < len(tokens):
                token = tokens[idx]
                token_lower = token.lower()

                if token_lower in {"-l", "-loop"}:
                    loop_every_minute = True
                    idx += 1
                    continue

                if token_lower.startswith("-start"):
                    argument = token[len("-start"):].lstrip("=").strip()
                    if not argument and token_lower == "-start":
                        if idx + 1 < len(tokens) and not tokens[idx + 1].startswith("-"):
                            argument = tokens[idx + 1]
                            idx += 1
                    start_option_set = True
                    start_argument = argument
                    idx += 1
                    continue

                if token_lower in SESSION_PRESETS:
                    session_option_set = True
                    session_argument = token_lower
                    idx += 1
                    continue

                if token_lower == "-s":
                    if idx + 1 < len(tokens):
                        session_option_set = True
                        session_argument = tokens[idx + 1]
                        idx += 2
                    else:
                        print("Session shortcut '-s' requires a value (e.g. -s NY).")
                        invalidate_menu()
                        schedule_valid = False
                        break
                    continue

                if token_lower.startswith("--session") or token_lower.startswith("-session"):
                    argument = token.split("=", 1)[1].strip() if "=" in token else ""
                    if not argument:
                        if idx + 1 < len(tokens) and not tokens[idx + 1].startswith("-"):
                            argument = tokens[idx + 1]
                            idx += 1
                        else:
                            print("Session option requires a value (e.g. --session NY).")
                            invalidate_menu()
                            schedule_valid = False
                            break
                    session_option_set = True
                    session_argument = argument
                    idx += 1
                    continue

                if token_lower.startswith("-end"):
                    argument = token[len("-end"):].lstrip("=").strip()
                    if not argument and token_lower == "-end":
                        if idx + 1 < len(tokens) and not tokens[idx + 1].startswith("-"):
                            argument = tokens[idx + 1]
                            idx += 1
                    end_option_set = True
                    end_argument = argument
                    idx += 1
                    continue

                stripped_token, had_loop_suffix = strip_loop_suffix(token)
                if had_loop_suffix:
                    loop_every_minute = True
                    token = stripped_token
                    if not token:
                        idx += 1
                        continue

                selection_tokens.append(token)
                idx += 1

            schedule_changed = False
            if not schedule_valid:
                continue
            cleared_values = {"", "clear", "none", "off", "reset"}

            available_sessions = ", ".join(sorted(name.upper() for name in SESSION_PRESETS))

            if session_option_set:
                value = (session_argument or "").strip().lower()
                if not value:
                    print("Session option requires a value (e.g. --session NY).")
                    invalidate_menu()
                    continue
                preset = SESSION_PRESETS.get(value)
                if not preset:
                    print(f"Unknown session '{session_argument}'. Available: {available_sessions}")
                    invalidate_menu()
                    continue
                try:
                    start_str, end_str = preset
                    loop_start_time = parse_time_of_day(start_str)
                    loop_end_time = parse_time_of_day(end_str)
                except ValueError as exc:
                    print(f"Failed to apply session '{session_argument}': {exc}")
                    invalidate_menu()
                    continue
                loop_session_name = value.upper()
                print(
                    f"Session {loop_session_name} applied ({loop_start_time.strftime('%H:%M')} - "
                    f"{loop_end_time.strftime('%H:%M')} ET)."
                )
                schedule_changed = True

            if start_option_set:
                value = (start_argument or "").strip()
                if value.lower() in cleared_values:
                    loop_start_time = None
                    print("Loop start cleared (Eastern).")
                else:
                    try:
                        loop_start_time = parse_time_of_day(value)
                    except ValueError as exc:
                        print(str(exc))
                        invalidate_menu()
                        continue
                    print(f"Loop start set to {loop_start_time.strftime('%H:%M')} ET.")
                loop_session_name = None
                schedule_changed = True

            if end_option_set:
                value = (end_argument or "").strip()
                if value.lower() in cleared_values:
                    loop_end_time = None
                    print("Loop end cleared (Eastern).")
                else:
                    try:
                        loop_end_time = parse_time_of_day(value)
                    except ValueError as exc:
                        print(str(exc))
                        invalidate_menu()
                        continue
                    print(f"Loop end set to {loop_end_time.strftime('%H:%M')} ET.")
                loop_session_name = None
                schedule_changed = True

            if schedule_changed:
                try:
                    recalc_next_run()
                except RuntimeError as exc:
                    print(str(exc))
                    schedule_valid = False
                invalidate_menu()
                # allow additional actions in same command
                if not schedule_valid:
                    continue

            raw_selection_parts: List[str] = []
            run_all = False
            selected_keys: List[str] = []

            for token in selection_tokens:
                clean_token = token.strip()
                if not clean_token:
                    continue
                for part in (segment.strip() for segment in clean_token.split(",") if segment.strip()):
                    if part.lower() == "a":
                        run_all = True
                    else:
                        raw_selection_parts.append(part)

            if run_all:
                selected_keys = []
            elif raw_selection_parts:
                deduped: List[str] = []
                unknown = False
                for part in raw_selection_parts:
                    if part not in options:
                        print(f"Unknown selection '{part}'. Try again.")
                        unknown = True
                        break
                    if part not in deduped:
                        deduped.append(part)
                if unknown:
                    invalidate_menu()
                    continue
                if not deduped:
                    print("No charts selected. Try again.")
                    invalidate_menu()
                    continue
                selected_keys = deduped
            else:
                selected_keys = []

            if not (run_all or selected_keys):
                if schedule_changed:
                    continue
                print("No charts selected. Try again.")
                invalidate_menu()
                continue

            if not debugger_ready():
                print("Chrome with remote debugging is not running. Choose option 'l' to launch it.")
                invalidate_menu()
                continue

            if loop_every_minute:
                description = selection_description(run_all, selected_keys)
                log_stage("loop", f"Running loop selection now: {description}")
                if run_all:
                    run_chart_batch(list(options.keys()), apply_geometry=True)
                else:
                    run_chart_batch(selected_keys, apply_geometry=True)
                loop_state = {
                    "run_all": run_all,
                    "selected_keys": selected_keys,
                    "description": description,
                    "next_run": next_loop_timestamp(
                        datetime.now(NEW_YORK_TZ),
                        loop_start_time,
                        loop_end_time,
                        tz=NEW_YORK_TZ,
                    ),
                }
                paused = False
                next_run_obj = loop_state["next_run"]
                if isinstance(next_run_obj, datetime):
                    log_stage(
                        "loop",
                        f"Loop scheduled. Next run at {next_run_obj.astimezone(NEW_YORK_TZ).strftime('%H:%M:%S')}.",
                    )
                else:
                    print("Loop scheduled.")
                invalidate_menu()
                continue

            if run_all:
                log_stage("menu", "Running selection once: All charts")
                run_chart_batch(list(options.keys()), apply_geometry=True)
            else:
                log_stage("menu", f"Running selection once: {selection_description(False, selected_keys)}")
                run_chart_batch(selected_keys, apply_geometry=True)
            invalidate_menu()
    finally:
        if driver is not None:
            try:
                driver.switch_to.default_content()
            except Exception:
                pass


if __name__ == "__main__":
    chart_configs = load_chart_configs(CONFIG_PATH)
    interactive_session(chart_configs)
