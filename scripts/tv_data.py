import contextlib
import json
import os
import shutil
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List

from helium import set_driver
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException

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


def find_save_menu_button(driver: webdriver.Chrome) -> WebElement:
    locators = [
        (By.CSS_SELECTOR, SAVE_MENU_SELECTOR),
        (By.XPATH, SAVE_MENU_XPATH),
    ]

    driver.switch_to.default_content()
    wait = WebDriverWait(driver, 15)
    for locator in locators:
        try:
            return wait.until(EC.element_to_be_clickable(locator))
        except TimeoutException:
            continue

    frames = driver.find_elements(By.TAG_NAME, "iframe")
    for frame in frames:
        driver.switch_to.default_content()
        driver.switch_to.frame(frame)
        inner_wait = WebDriverWait(driver, 5)
        for locator in locators:
            try:
                return inner_wait.until(EC.element_to_be_clickable(locator))
            except TimeoutException:
                continue

    driver.switch_to.default_content()
    raise TimeoutException("Save/load menu button not found in page or iframes.")


def click_export_chart_data(driver: webdriver.Chrome) -> None:
    driver.switch_to.default_content()
    wait = WebDriverWait(driver, 10)
    locators = [
        (By.CSS_SELECTOR, EXPORT_MENU_CSS),
        (By.XPATH, EXPORT_MENU_XPATH),
    ]

    for locator in locators:
        try:
            menu_item = wait.until(EC.element_to_be_clickable(locator))
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", menu_item)
            driver.execute_script("arguments[0].click();", menu_item)
            return
        except TimeoutException:
            continue

    raise TimeoutException("Export chart data menu item not found.")


def click_export_confirm(driver: webdriver.Chrome) -> None:
    driver.switch_to.default_content()
    wait = WebDriverWait(driver, 10)
    button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, EXPORT_CONFIRM_SELECTOR)))
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
    driver.execute_script("arguments[0].click();", button)


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
            time.sleep(1)
            continue

        if export_path.suffix == ".crdownload":
            time.sleep(1)
            continue

        size = export_path.stat().st_size
        if size and size == last_size:
            return export_path
        last_size = size
        time.sleep(1)

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


def process_chart(chart: ChartConfig, driver: webdriver.Chrome) -> None:
    print(f"Processing chart {chart.name} at {chart.url}")
    driver.get(chart.url)
    wait_for_page_ready(driver)
    time.sleep(5)  # TradingView loads additional UI after readyState completes.

    try:
        button = find_save_menu_button(driver)
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
        driver.execute_script("arguments[0].click();", button)
        click_export_chart_data(driver)
        click_export_confirm(driver)
        move_exported_file(chart.export_prefix, chart.save_path)
    finally:
        try:
            driver.switch_to.default_content()
        except Exception:
            pass


def run(charts: Iterable[ChartConfig]) -> None:
    driver = attach_driver()
    set_driver(driver)

    try:
        for chart in charts:
            try:
                process_chart(chart, driver)
            except TimeoutException as exc:
                print(f"{chart.name}: timeout - {exc}")
            except Exception as exc:  # pylint: disable=broad-except
                print(f"{chart.name}: failed with error - {exc}")
                continue
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
        "Select a chart to export:",
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

    try:
        while True:
            choice = input("Enter option (1/2/3/... or x to exit): ").strip().lower()
            if choice == "x":
                print("Exiting.")
                break
            if choice == "a":
                for chart in charts:
                    try:
                        process_chart(chart, driver)
                    except TimeoutException as exc:
                        print(f"{chart.name}: timeout - {exc}")
                    except Exception as exc:  # pylint: disable=broad-except
                        print(f"{chart.name}: failed with error - {exc}")
                        continue
                print(menu_text)
                continue

            chart = options.get(choice)
            if not chart:
                print("Invalid option. Try again.")
                print(menu_text)
                continue

            try:
                process_chart(chart, driver)
            except TimeoutException as exc:
                print(f"{chart.name}: timeout - {exc}")
            except Exception as exc:  # pylint: disable=broad-except
                print(f"{chart.name}: failed with error - {exc}")
                continue
            print(menu_text)
    finally:
        try:
            driver.switch_to.default_content()
        except Exception:
            pass


if __name__ == "__main__":
    chart_configs = load_chart_configs(CONFIG_PATH)
    interactive_session(chart_configs)
