import contextlib
import json
import os
import shutil
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from helium import set_driver
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException

CONFIG_PATH = Path(__file__).with_suffix(".json")
DOWNLOADS_DIR = Path.home() / "Downloads"
REMOTE_DEBUG_ADDRESS = os.getenv("REMOTE_DEBUG_ADDRESS", "127.0.0.1:9222")
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
EXPORT_DIALOG_SETTLE_SECONDS = 1.2
UI_READY_TIMEOUT = 10


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


def build_service() -> Service:
    try:
        from webdriver_manager.chrome import ChromeDriverManager  # type: ignore
    except ImportError:
        chromedriver_path = os.getenv("CHROMEDRIVER_PATH") or shutil.which("chromedriver")
        if not chromedriver_path:
            raise RuntimeError(
                "Chromedriver not found. Install webdriver-manager or set CHROMEDRIVER_PATH."
            )
        return Service(executable_path=chromedriver_path)
    return Service(ChromeDriverManager().install())


def wait_for_debugger(address: str, timeout_seconds: int = 15) -> None:
    host, _, port = address.partition(":")
    if not host or not port:
        raise ValueError(f"REMOTE_DEBUG_ADDRESS '{address}' must be in host:port format.")

    url = f"http://{host}:{port}/json/version"
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with contextlib.closing(urllib.request.urlopen(url, timeout=2)):
                return
        except OSError:
            time.sleep(0.5)

    raise RuntimeError(
        f"Chrome debugger not reachable at {address}. "
        "Start Chrome with --remote-debugging-port and ensure the port matches."
    )


def attach_driver() -> webdriver.Chrome:
    wait_for_debugger(REMOTE_DEBUG_ADDRESS)
    options = Options()
    options.add_experimental_option("debuggerAddress", REMOTE_DEBUG_ADDRESS)
    driver = webdriver.Chrome(service=build_service(), options=options)
    driver.set_window_position(0, 0)
    driver.set_window_size(1920, 1080)
    return driver


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
    time.sleep(EXPORT_DIALOG_SETTLE_SECONDS)

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

    for name, action in (
        ("direct click", lambda: button.click()),
        ("js click", lambda: driver.execute_script("arguments[0].click();", button)),
    ):
        try:
            action()
            driver.switch_to.default_content()
            return
        except Exception as err:  # noqa: PERF203 - debugging fallback
            record_failure(name, err)

    try:
        driver.execute_script("arguments[0].focus();", button)
    except Exception as err:
        record_failure("focus", err)

    for name, action in (
        ("enter on button", lambda: button.send_keys(Keys.ENTER)),
        (
            "enter on active element",
            lambda: driver.switch_to.active_element.send_keys(Keys.ENTER),
        ),
    ):
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


def wait_for_export(prefix: str, timeout_seconds: int = 30) -> Path:
    deadline = time.time() + timeout_seconds
    last_size = None
    export_path: Path

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
            return export_path
        last_size = size
        time.sleep(0.5)

    raise TimeoutException(f"Export file matching '{prefix}' did not finish downloading in time.")


def move_exported_file(prefix: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    export_file = wait_for_export(prefix)
    shutil.copy2(export_file, destination)
    try:
        export_file.unlink()
    except OSError as err:
        print(f"{prefix}: copied to '{destination}', but failed to remove '{export_file}': {err}")
    else:
        print(f"{prefix}: moved '{export_file.name}' to '{destination}'.")


def process_chart(chart: ChartConfig, driver: webdriver.Chrome) -> Tuple[bool, float, str]:
    print(f"Processing chart {chart.name} at {chart.url}")
    start_time = time.perf_counter()
    driver.get(chart.url)
    wait_for_page_ready(driver)
    wait_for_menu_ready(driver)

    success = False
    error_message = ""
    elapsed_ms = 0.0

    try:
        button = find_save_menu_button(driver)
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
        driver.execute_script("arguments[0].click();", button)
        click_export_chart_data(driver)
        click_export_confirm(driver)
        move_exported_file(chart.export_prefix, chart.save_path)
        success = True
    except TimeoutException as exc:
        error_message = f"timeout - {exc}"
    except Exception as exc:  # pylint: disable=broad-except
        error_message = f"failed with error - {exc}"
    finally:
        try:
            driver.switch_to.default_content()
        except Exception:
            pass

    elapsed_ms = (time.perf_counter() - start_time) * 1000

    if success:
        print(f"{chart.name}: completed in {elapsed_ms:.0f} ms.")
    else:
        print(f"{chart.name}: {error_message} (after {elapsed_ms:.0f} ms)")

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
        try:
            driver.switch_to.default_content()
        except Exception:
            pass


def interactive_session(charts: List[ChartConfig]) -> None:
    driver = attach_driver()
    set_driver(driver)

    options: Dict[str, ChartConfig] = {
        str(index): chart for index, chart in enumerate(charts, start=1)
    }

    menu_lines = [
        "",
        "Select a chart to export (append '-loop' or '-l' to run every minute, e.g. 1 -loop or a -l):",
        *[
            f"  {index}. {chart.name} ({chart.export_prefix})"
            for index, chart in options.items()
        ],
        "  a. Export all charts",
        "  x. Exit",
        "",
    ]
    menu_text = "\n".join(menu_lines)

    print(menu_text)

    metrics: List[float] = []

    def print_overall_metrics() -> None:
        if metrics:
            avg_runtime = sum(metrics) / len(metrics)
            print(
                f"Overall average runtime: {avg_runtime:.0f} ms across {len(metrics)} chart runs."
            )

    def run_single_chart(selected_chart: ChartConfig) -> None:
        success, elapsed_ms, _ = process_chart(selected_chart, driver)
        if success:
            metrics.append(elapsed_ms)
            print_overall_metrics()

    def run_all_charts() -> None:
        batch_metrics: List[float] = []
        for chart in charts:
            success, elapsed_ms, _ = process_chart(chart, driver)
            if success:
                metrics.append(elapsed_ms)
                batch_metrics.append(elapsed_ms)
        if batch_metrics:
            avg_batch = sum(batch_metrics) / len(batch_metrics)
            print(f"Batch average runtime: {avg_batch:.0f} ms across {len(batch_metrics)} charts.")
            print_overall_metrics()

    try:
        while True:
            raw_choice = input("Enter option (1/2/3/... or x to exit): ").strip().lower()
            loop_every_minute = raw_choice.endswith("-loop") or raw_choice.endswith(" -loop")
            loop_every_minute = loop_every_minute or raw_choice.endswith("-l") or raw_choice.endswith(" -l")

            choice = raw_choice
            for suffix in (" -loop", "-loop", " -l", "-l"):
                if choice.endswith(suffix):
                    choice = choice[: -len(suffix)]
                    loop_every_minute = True
            choice = choice.strip()

            if choice == "x":
                print("Exiting.")
                break

            if not choice:
                print("Invalid option. Try again.")
                print(menu_text)
                continue

            if choice != "a" and choice not in options:
                print("Invalid option. Try again.")
                print(menu_text)
                continue

            def perform_selection() -> None:
                if choice == "a":
                    run_all_charts()
                else:
                    run_single_chart(options[choice])

            if loop_every_minute and choice != "x":
                print("Starting scheduled loop. Press Ctrl+C to stop.")
                try:
                    while True:
                        perform_selection()
                        now = datetime.now()
                        target = (now + timedelta(minutes=1)).replace(
                            second=0, microsecond=0
                        ) - timedelta(seconds=10)
                        if target <= now:
                            target += timedelta(minutes=1)
                        wait_seconds = max((target - now).total_seconds(), 0)
                        next_time_str = target.strftime("%H:%M:%S")
                        print(
                            f"Next run at {next_time_str} in {wait_seconds:.0f} seconds..."
                        )
                        time.sleep(wait_seconds)
                except KeyboardInterrupt:
                    print("Minute loop stopped. Returning to menu.")
                print(menu_text)
                continue

            perform_selection()
            print(menu_text)
    finally:
        try:
            driver.switch_to.default_content()
        except Exception:
            pass


if __name__ == "__main__":
    chart_configs = load_chart_configs(CONFIG_PATH)
    interactive_session(chart_configs)
