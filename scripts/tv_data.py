import contextlib
import json
import os
import select
import shutil
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

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

CONFIG_PATH = Path(__file__).with_suffix(".json")
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
LOG_TIMESTAMP_FORMAT = "%H:%M:%S"


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
    save_path: Path
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
                save_path=Path(raw["save_path"]),
                url=raw["url"],
            )
        )
    return charts


def log_stage(prefix: str, message: str) -> None:
    timestamp = datetime.now().strftime(LOG_TIMESTAMP_FORMAT)
    print(f"[{timestamp}] {prefix} {message}")


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
            driver.set_window_position(0, 0)
            driver.set_window_size(1920, 1080)
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


def next_loop_timestamp(now: datetime) -> datetime:
    target = now.replace(second=50, microsecond=0)
    if target <= now:
        target = (target + timedelta(minutes=1)).replace(second=50, microsecond=0)
    return target


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


def move_exported_file(
    prefix: str, destination: Path, log_prefix: Optional[str] = None
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if log_prefix:
        log_stage(log_prefix, f"Waiting for exported file with prefix '{prefix}'.")
    export_file = wait_for_export(prefix, log_prefix=log_prefix)
    shutil.copy2(export_file, destination)
    try:
        export_file.unlink()
    except OSError as err:
        print(f"{prefix}: copied to '{destination}', but failed to remove '{export_file}': {err}")
    else:
        if log_prefix:
            log_stage(log_prefix, f"Moved '{export_file.name}' to '{destination}'.")
        else:
            print(f"{prefix}: moved '{export_file.name}' to '{destination}'.")


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
        move_exported_file(chart.export_prefix, chart.save_path, log_prefix=prefix)
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

    metrics: List[float] = []

    def print_overall_metrics() -> None:
        if metrics:
            avg_runtime = sum(metrics) / len(metrics)
            print(
                f"Overall average runtime: {avg_runtime:.0f} ms across {len(metrics)} chart runs."
            )

    def run_chart_batch(batch_keys: List[str]) -> None:
        try:
            active_driver = ensure_driver()
        except Exception as exc:
            print(f"Failed to attach to Chrome: {exc}")
            if not is_debugger_available(REMOTE_DEBUG_ADDRESS):
                print("Hint: choose option 'l' first to launch Chrome with remote debugging.")
            return

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

    def selection_description(run_all: bool, selected_keys: List[str]) -> str:
        if run_all:
            return "All charts"
        names = [options[key].name for key in selected_keys]
        return ", ".join(names)

    def build_menu_text(paused: bool, loop_state: Optional[Dict[str, object]]) -> str:
        status = "PAUSED" if paused else "READY"
        lines: List[str] = ["", f"[Status: {status}]"]
        if loop_state:
            next_run = loop_state.get("next_run")
            next_run_str = (
                next_run.strftime("%H:%M:%S") if isinstance(next_run, datetime) else "n/a"
            )
            lines.append(
                f"Active loop: {loop_state['description']} (next run {next_run_str})"
            )
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
            lines.append("  h. Show menu")
        else:
            lines.append("Launch Chrome with remote debugging to enable exports:")
            lines.append("  l. Launch remote-debug Chrome window")
        lines.append("  x. Exit")
        lines.append("")
        lines.append("Enter option (comma-separated numbers, a, l, p, r, h, or x):")
        return "\n".join(lines)

    loop_state: Optional[Dict[str, object]] = None
    paused = False
    menu_dirty = True

    try:
        while True:
            now = datetime.now()
            if loop_state and not paused:
                next_run = loop_state.get("next_run")
                if isinstance(next_run, datetime) and next_run <= now:
                    run_all = bool(loop_state.get("run_all"))
                    selected_keys = list(loop_state.get("selected_keys", []))  # type: ignore[arg-type]
                    log_stage("loop", f"Running scheduled selection: {loop_state['description']}")
                    if run_all:
                        run_chart_batch(list(options.keys()))
                    else:
                        run_chart_batch(selected_keys)
                    loop_state["next_run"] = next_loop_timestamp(datetime.now())
                    updated_next = loop_state["next_run"]
                    if isinstance(updated_next, datetime):
                        log_stage("loop", f"Next run scheduled at {updated_next.strftime('%H:%M:%S')}.")
                    menu_dirty = True
                    continue

            if menu_dirty:
                print(build_menu_text(paused, loop_state))
                sys.stdout.write("> ")
                sys.stdout.flush()
                menu_dirty = False

            poll_timeout: Optional[float] = None
            if loop_state and not paused:
                next_run = loop_state.get("next_run")
                if isinstance(next_run, datetime):
                    delta = (next_run - datetime.now()).total_seconds()
                    if delta <= 0:
                        continue
                    poll_timeout = max(min(delta, 1.0), 0.1)

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
                menu_dirty = True
                continue

            lower_choice = raw_choice.lower()
            log_stage("menu", f"Command received: {raw_choice}")
            loop_every_minute = lower_choice.endswith("-loop") or lower_choice.endswith(" -loop")
            loop_every_minute = loop_every_minute or lower_choice.endswith("-l") or lower_choice.endswith(" -l")

            choice = lower_choice
            for suffix in (" -loop", "-loop", " -l", "-l"):
                if choice.endswith(suffix):
                    choice = choice[: -len(suffix)]
                    loop_every_minute = True
            choice = choice.strip()

            if choice == "x":
                print("Exiting.")
                break

            if choice == "h":
                menu_dirty = True
                continue

            if choice == "l":
                if loop_every_minute:
                    print("Loop scheduling is not supported for the launch option.")
                    continue
                if debugger_ready():
                    print("Chrome remote-debugger already running.")
                else:
                    try:
                        launch_remote_debug_chrome()
                    except Exception as exc:
                        print(f"Failed to launch remote-debug Chrome: {exc}")
                menu_dirty = True
                continue

            if choice == "p":
                if loop_state:
                    if paused:
                        print("Loop already paused.")
                    else:
                        paused = True
                        print("Loop paused.")
                else:
                    print("No active loop to pause.")
                menu_dirty = True
                continue

            if choice == "r":
                if loop_state:
                    if not paused:
                        print("Loop already running.")
                    else:
                        paused = False
                        print("Loop resumed.")
                        if loop_state.get("next_run"):
                            loop_state["next_run"] = next_loop_timestamp(datetime.now())
                else:
                    print("No active loop to resume.")
                menu_dirty = True
                continue

            ready = debugger_ready()
            if not ready:
                print("Chrome with remote debugging is not running. Choose option 'l' to launch it.")
                menu_dirty = True
                continue

            run_all = False
            selected_keys: List[str] = []

            if choice == "a":
                run_all = True
            else:
                parts = [part.strip() for part in choice.split(",") if part.strip()]
                if not parts:
                    print("Invalid option. Try again.")
                    menu_dirty = True
                    continue
                deduped: List[str] = []
                unknown = False
                for part in parts:
                    if part not in options:
                        print(f"Unknown selection '{part}'. Try again.")
                        unknown = True
                        break
                    if part not in deduped:
                        deduped.append(part)
                if unknown or not deduped:
                    menu_dirty = True
                    continue
                selected_keys = deduped

            if loop_every_minute:
                description = selection_description(run_all, selected_keys)
                log_stage("loop", f"Running loop selection now: {description}")
                if run_all:
                    run_chart_batch(list(options.keys()))
                else:
                    run_chart_batch(selected_keys)
                loop_state = {
                    "run_all": run_all,
                    "selected_keys": selected_keys,
                    "description": description,
                    "next_run": next_loop_timestamp(datetime.now()),
                }
                paused = False
                next_run = loop_state["next_run"]
                if isinstance(next_run, datetime):
                    log_stage("loop", f"Loop scheduled. Next run at {next_run.strftime('%H:%M:%S')}.")
                else:
                    print("Loop scheduled.")
                menu_dirty = True
                continue

            if run_all:
                log_stage("menu", "Running selection once: All charts")
                run_chart_batch(list(options.keys()))
            else:
                log_stage("menu", f"Running selection once: {selection_description(False, selected_keys)}")
                run_chart_batch(selected_keys)
            menu_dirty = True
    finally:
        if driver is not None:
            try:
                driver.switch_to.default_content()
            except Exception:
                pass


if __name__ == "__main__":
    chart_configs = load_chart_configs(CONFIG_PATH)
    interactive_session(chart_configs)
