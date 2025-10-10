import contextlib
import os
import shutil
import time
import urllib.request

from helium import set_driver
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException

TRADINGVIEW_URL = "https://www.tradingview.com/chart/bvfM7ug3/"
REMOTE_DEBUG_ADDRESS = os.getenv("REMOTE_DEBUG_ADDRESS", "127.0.0.1:9222")
SAVE_MENU_SELECTOR = "[data-name='save-load-menu']"
SAVE_MENU_XPATH = "/html/body/div[2]/div/div[3]/div/div/div[3]/div[1]/div/div/div/div/div[14]/div/div/div/button"
EXPORT_MENU_CSS = "#overlap-manager-root div.menu-yyMUOAN9 div div div:nth-child(6)"
EXPORT_MENU_XPATH = "//div[@data-role='menuitem' and .//span[contains(normalize-space(.), 'Export chart data')]]"
EXPORT_CONFIRM_SELECTOR = "[data-name='submit-button']"


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
    return webdriver.Chrome(service=build_service(), options=options)


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
    try:
        button = wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, EXPORT_CONFIRM_SELECTOR))
        )
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
        driver.execute_script("arguments[0].click();", button)
    except TimeoutException:
        raise TimeoutException("Export confirmation button not found or not clickable.")


browser = attach_driver()
set_driver(browser)
browser.get(TRADINGVIEW_URL)
wait_for_page_ready(browser)

time.sleep(5)  # Allow additional time for TradingView's dynamic content to load.

# Example interaction: click TradingView's save/load menu button if present.
try:
    button = find_save_menu_button(browser)
    browser.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
    browser.execute_script("arguments[0].click();", button)
    click_export_chart_data(browser)
    click_export_confirm(browser)
except TimeoutException:
    print("Save/load menu button not found or not clickable.")
except Exception as exc:
    print(f"Failed to click save/load menu button: {exc}")
finally:
    try:
        browser.switch_to.default_content()
    except Exception:
        pass
