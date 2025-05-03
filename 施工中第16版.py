import time
import csv
import os
import re
import json
import random # 用於隨機延遲
from datetime import datetime
import requests # 用於解析 URL 參數
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException, ElementClickInterceptedException, StaleElementReferenceException
from typing import Optional, Dict, Any, Tuple, Callable, List

# --- Helper Functions (可以放在類別外部或內部作為靜態方法) ---
# 只為了測試jenkins

def parse_number(text: Optional[str]) -> Optional[float]:
    """從文本中解析數字，處理 K 和 M"""
    if not text: return None
    clean_text = re.sub(r'[^\d.KMk]', '', str(text)).upper()
    try:
        if 'K' in clean_text: return float(clean_text.replace('K', '')) * 1000
        elif 'M' in clean_text: return float(clean_text.replace('M', '')) * 1_000_000
        return float(clean_text)
    except ValueError: return None

def extract_integer(text: Optional[str]) -> Optional[int]:
    """從文本中提取第一個整數"""
    if not text: return None
    matches = re.findall(r'\d+', str(text))
    return int(matches[0]) if matches else None

def extract_year_and_count(text: str) -> Optional[Tuple[str, int]]:
    """從 'YYYY (Count)' 格式的文本中提取年份和數量"""
    year_match = re.match(r'^(\d{4})', text)
    count_match = re.search(r'\((\d+)\)', text)
    if year_match and count_match:
        year = year_match.group(1)
        count = int(count_match.group(1))
        return year, count
    # 可以添加其他格式的處理邏輯，例如只有年份或只有數量
    return None

# --- 主爬蟲類別 ---

class PatreonScraperRefactored:
    """
    一個重構後的 Patreon 爬蟲類別，用於抓取創作者頁面數據。
    """
    # --- 選擇器集中管理 ---
    # TODO: 以下所有選擇器都需要你根據實際 Patreon 頁面結構進行驗證和替換！
    # 建議優先使用 ID、穩定的 class、data-* 屬性或基於文本內容的相對 XPath/CSS。
    SELECTORS = {
        # 靜態內容
        "creator_name": (By.XPATH, "//h1[contains(@class, 'eEyNbR')]"), # 示例：嘗試 data-testid 或 header h1
        "patron_count": (By.XPATH, "//span[@data-tag='patron-count']"), # 示例：查找包含特定文本的 span
        "total_posts": (By.XPATH, "//span[@data-tag='creation-count']"), # 示例：查找包含特定文本的 span
        # "monthly_income": (By.XPATH, "//span[contains(text(), '$')]/parent::li/span"), # 收入信息可能受隱私設置影響，較難獲取

        # 下拉菜單觸發按鈕
        "post_type_button": (By.XPATH, "//button[@aria-label='Sort posts by post type']"), # 示例
        "tier_button": (By.XPATH, "//button[@aria-label='Sort posts by tier']"), # 示例
        "year_button": (By.XPATH, "//button[@aria-label='Sort posts by date']"), # 示例

        # 下拉菜單容器 (通用)
        "dropdown_container": (By.XPATH, "//div[@role='dialog' and (@aria-label='Sort posts by post type' or @aria-label='Sort posts by tier' or @aria-label='Sort posts by date')]"), # 示例

        # 下拉菜單項目 (通用)
        "dropdown_item_link": (By.TAG_NAME, "a"), # 適用於很多情況
        "dropdown_item_button": (By.TAG_NAME, "button"), # 有時是按鈕

        # 社交互動
        "like_count_element": (By.XPATH, "//span[@data-tag='like-count']"), # 示例
        "comment_count_element": (By.XPATH, "//a[@data-tag='comment-post-icon']//p"), # 示例

        # 社群連結 (在特定區域查找)
        "social_link_area": (By.XPATH, "//div[@data-testid='creator-profile-social-links'] | //section[contains(@aria-label,'Social')] | //body"), # 示例：找到包含社群連結的父容器
        "social_link": (By.XPATH, ".//a[@href]"), # 在上述區域內查找 a 標籤

        # 載入更多按鈕
        "load_more_button": (By.XPATH, "//button[contains(., '查看更多文章') or contains(., 'See more posts')]"), # 示例

        # 年齡驗證按鈕
        "age_verification_button": (By.XPATH, "//button[@data-tag='age-verification-button-yes']"), # 示例

        # "關於"頁面
        "about_link": (By.XPATH, "//li/a[substring(@href, string-length(@href) - string-length('/about?') + 1) = '/about?' and (normalize-space(.)='About' or normalize-space(.)='關於')]"),
        "about_content_container": (By.XPATH, "//div[@data-tag='about-contents']"),

        "monthly_income_element": (By.XPATH, "//span[@data-tag='earnings-count']"),
        #單個貼文容器
        "post_card_container": (By.XPATH, "//div[@data-tag='post-card']"),
        #用data-tag 找是否有鎖定的圖示
        "lock_icon_indicator": (By.XPATH, ".//button[@data-tag='locked-badge-button'] | .//svg[@data-tag='IconLock']"),
        #確定是否有聊天室
        "chat_nav_link": (By.XPATH, "//li/a[contains(@href, '/chats') and normalize-space(.)='Chats']"),
        "chat_list_item": (By.XPATH, "//button[starts-with(@data-tag, 'chat-list-item-')]"),
        "chat_lock_icon": (By.XPATH, ".//svg[@data-tag='IconLock']"),
        #會籍
        "tier_card": (By.XPATH, ".//div[@data-tag='tier-card']"),
        "tier_name": (By.XPATH, ".//div[contains(@aria-label, ' per month')]/preceding-sibling::div"),
        "tier_price": (By.XPATH, ".//div[contains(@aria-label, ' per month')]//div[starts-with(normalize-space(.), '$')]"),
        "tier_description_area": (By.XPATH, ".//a[@data-tag='patron-checkout-continue-button']/ancestor::div[2]/following-sibling::div"),

        "tier_carousel_right_button": (By.XPATH, "//button[@data-tag='carousel-right']"),
        # 只選擇可點擊的右按鈕 (aria-disabled 不是 true)
        "tier_carousel_right_button_clickable": (By.XPATH, "//button[@data-tag='carousel-right' and (not(@aria-disabled) or @aria-disabled='false')]"),
        "tier_carousel_left_button_clickable": (By.XPATH, "//button[@data-tag='carousel-left' and (not(@aria-disabled) or @aria-disabled='false')]"),

    }


    def __init__(self, output_dir: str = "output_data", headless: bool = True):
        """
        初始化爬蟲。

        Args:
            output_dir (str): 儲存輸出 CSV 檔案的目錄。
            headless (bool): 是否以無頭模式運行瀏覽器。
        """
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_path = os.path.join(self.output_dir, f'patreon_data_{timestamp}_refactored.csv')
        print(f"輸出檔案將儲存至: {self.output_path}")

        print("正在初始化 WebDriver...")
        chrome_options = Options()
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--start-maximized") # 嘗試最大化視窗
        chrome_options.add_argument("--disable-infobars")
        chrome_options.add_argument("--disable-extensions")
        # 設置語言偏好，可能影響頁面文本
        chrome_options.add_experimental_option('prefs', {'intl.accept_languages': 'en,en_US'})
        if headless:
            chrome_options.add_argument("--headless")
            print("啟用無頭模式。")

        try:
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            # 增加預設等待時間
            self.wait = WebDriverWait(self.driver, 15) # 增加到 15 秒
            print("WebDriver 初始化成功。")
        except Exception as e:
            print(f"WebDriver 初始化失敗: {e}")
            print("請確保 Chrome 瀏覽器已安裝，或網路連線正常以下載 ChromeDriver。")
            raise # 拋出異常，終止程式

    def _find_element(self, locator: Tuple[str, str], parent=None, timeout=10) -> Optional[webdriver.remote.webelement.WebElement]:
        """輔助函數：安全地查找單個元素，使用指定的超時時間"""
        target = parent or self.driver
        wait = WebDriverWait(target, timeout) if timeout != 15 else self.wait # 允許臨時超時
        try:
            return wait.until(EC.presence_of_element_located(locator))
        except TimeoutException:
            # print(f"查找元素超時: {locator}") # 減少輸出
            return None
        except Exception as e:
            print(f"查找元素時發生錯誤 {locator}: {e}")
            return None

    def _find_elements(self, locator: Tuple[str, str], parent=None) -> List[webdriver.remote.webelement.WebElement]:
        """輔助函數：安全地查找多個元素"""
        target = parent or self.driver
        try:
            # 短暫等待至少一個元素出現
            WebDriverWait(target, 5).until(EC.presence_of_element_located(locator))
            return target.find_elements(locator[0], locator[1])
        except TimeoutException:
             # print(f"查找元素列表超時或未找到: {locator}")
            return []
        except Exception as e:
            print(f"查找元素列表時發生錯誤 {locator}: {e}")
            return []

    def _click_element(self, locator: Tuple[str, str], timeout=10) -> bool:
        """輔助函數：安全地滾動到元素並點擊"""
        element = self._find_element(locator, timeout=timeout)
        if not element:
            print(f"無法找到用於點擊的元素: {locator}")
            return False
        try:
            # 滾動到元素並等待可點擊
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'smooth'});", element)
            clickable_element = WebDriverWait(self.driver, timeout).until(EC.element_to_be_clickable(locator))
            clickable_element.click()
            print(f"成功點擊元素: {locator}")
            return True
        except ElementClickInterceptedException:
            print(f"元素 {locator} 被遮擋，嘗試 JS 點擊...")
            try:
                self.driver.execute_script("arguments[0].click();", element)
                print(f"成功使用 JS 點擊元素: {locator}")
                return True
            except Exception as js_e:
                print(f"JS 點擊失敗 {locator}: {js_e}")
                return False
        except StaleElementReferenceException:
             print(f"元素 {locator} 已過時，點擊失敗。")
             return False
        except TimeoutException:
            print(f"等待元素 {locator} 可點擊超時。")
            return False
        except Exception as e:
            print(f"點擊元素 {locator} 時發生未知錯誤: {e}")
            return False

    def handle_age_verification(self) -> bool:
        """處理年齡確認彈窗"""
        print("檢查年齡驗證彈窗...")
        # 使用更短的超時，因為彈窗通常很快出現
        clicked = self._click_element(self.SELECTORS["age_verification_button"], timeout=3)
        if clicked:
            print("已處理年齡驗證。")
            # 等待彈窗消失或頁面穩定
            try:
                self.wait.until(EC.invisibility_of_element_located(self.SELECTORS["age_verification_button"]))
            except TimeoutException:
                time.sleep(1) # 保留短暫 sleep 作為備用
            return True
        else:
            print("未找到或無法點擊年齡驗證按鈕。")
            return False

    def get_static_content(self) -> Dict[str, Any]:
        """獲取頁面頂部的靜態信息"""
        print("正在獲取靜態內容...")
        static_data = {
            'creator_name': '',
            'patron_count': 0,
            'total_posts': 0,
            'monthly_income': 0 # 收入信息通常不可靠或不可見
        }

        # 獲取創作者名稱
        name_element = self._find_element(self.SELECTORS["creator_name"])
        if name_element:
            static_data['creator_name'] = name_element.text.strip()
            print(f"  找到 Creator Name: {static_data['creator_name']}")

        # 獲取 Patrons 數量
        # Patreon 頁面結構可能將數字和文本分開，需要更複雜的定位
        # TODO: 仔細檢查 Patron 數量的 HTML 結構
        # 嘗試找到包含 "patron" 的元素，然後在其附近查找數字
        try:
            patron_label_element = self._find_element(self.SELECTORS["patron_count"])
            if patron_label_element:
                # 嘗試在其父元素或兄弟元素中尋找數字
                parent = patron_label_element.find_element(By.XPATH, "..") # 父元素
                # 這裡需要根據實際結構調整XPath來找數字
                # number_element = parent.find_element(By.XPATH, "./preceding-sibling::span | ./span[not(self::*)]")
                # 假設數字就在標籤旁邊的某個 span
                number_text = ""
                possible_spans = parent.find_elements(By.TAG_NAME, "span")
                if not possible_spans: # 有時可能直接在 li 下
                    parent_li = patron_label_element.find_element(By.XPATH, "./ancestor::li")
                    possible_spans = parent_li.find_elements(By.TAG_NAME, "span")

                for span in possible_spans:
                     if span.text and span.text.strip() and any(char.isdigit() for char in span.text):
                          number_text = span.text.strip()
                          break
                if number_text:
                    static_data['patron_count'] = parse_number(number_text) or 0
                    print(f"  找到 Patron Count: {static_data['patron_count']} (來自文本: {number_text})")
                else:
                     print(f"  找到 Patron 標籤，但未能提取數字。")

        except Exception as e:
            print(f"  獲取 Patron Count 時出錯: {e}")

        print("  嘗試獲取月收入...")
        income_element = self._find_element(self.SELECTORS["monthly_income_element"], timeout=2)
        if income_element:
            income_text = income_element.text.strip()
            income_value = parse_number(income_text) # 使用輔助函數解析
            if income_value is not None:
                static_data['income_per_month'] = income_value
                print(f"  找到 Monthly Income: {static_data['income_per_month']} (來自文本: {income_text})")
            else:
                print(f"  找到月收入元素，但無法從文本 '{income_text}' 解析數字。")
        else:
            print("  未找到公開的月收入信息。")


        # 獲取 Posts 數量 (邏輯類似 Patron Count)
        # TODO: 仔細檢查 Post 數量的 HTML 結構
        try:
            post_label_element = self._find_element(self.SELECTORS["total_posts"])
            if post_label_element:
                parent = post_label_element.find_element(By.XPATH, "..")
                number_text = ""
                possible_spans = parent.find_elements(By.TAG_NAME, "span")
                if not possible_spans:
                    parent_li = post_label_element.find_element(By.XPATH, "./ancestor::li")
                    possible_spans = parent_li.find_elements(By.TAG_NAME, "span")
                for span in possible_spans:
                     if span.text and span.text.strip() and any(char.isdigit() for char in span.text):
                          number_text = span.text.strip()
                          break
                if number_text:
                     static_data['total_posts'] = parse_number(number_text) or 0
                     print(f"  找到 Total Posts: {static_data['total_posts']} (來自文本: {number_text})")
                else:
                     print(f"  找到 Post 標籤，但未能提取數字。")

        except Exception as e:
            print(f"  獲取 Total Posts 時出錯: {e}")

        return static_data

    def get_about_section_word_count(self) -> int:
        """
        嘗試點擊 '關於' 標籤頁，並計算其內容區域的字數 (Word Count)。

        Returns:
            int: '關於' 區域的字數。如果無法找到或處理，則返回 0。
                 注意: 目前計算的是以空格分隔的單詞數。
                       如果需要計算總字符數，請使用 len(about_text)。
        """
        print("嘗試獲取 '關於' 區域的字數...")
        about_word_count = 0
        about_link_selector = self.SELECTORS["about_link"]
        content_container_selector = self.SELECTORS["about_content_container"]

        # --- 步驟 1: 找到並點擊 '關於' 連結/標籤頁 ---
        print(f"查找 '關於' 連結: {about_link_selector}")
        # 注意：這裡假設點擊 '關於' 是安全的，不會導致後續爬取狀態混亂
        # 如果點擊會改變 URL 或頁面狀態，可能需要更複雜的處理 (例如爬完後導航回去)
        if not self._click_element(about_link_selector, timeout=10):
            print("未能找到或點擊 '關於' 連結/標籤頁，無法計算字數。")
            return 0 # 點擊失敗，返回 0

        # --- 步驟 2: 等待 '關於' 內容容器出現 ---
        print(f"等待 '關於' 內容容器加載: {content_container_selector}")
        # 增加等待時間，因為內容可能是動態加載的
        content_container = self._find_element(content_container_selector, timeout = 10)

        if content_container is None:
            print("未能找到 '關於' 內容容器，無法計算字數。")
            # 嘗試導航離開或點擊其他地方，避免停留在未完全加載的狀態？ (可選)
            return 0

        # --- 步驟 3: 提取文本並計算字數 ---
        try:
            print("提取 '關於' 區域文本...")
            about_text = content_container.text
            if about_text:
                # 計算字數 (以空格分隔)
                words = about_text.strip().split()
                about_word_count = len(words)
                print(f"'關於' 區域字數 (Word Count): {about_word_count}")
                # 如果需要字符數：
                # about_char_count = len(about_text.strip())
                # print(f"'關於' 區域字符數 (Character Count): {about_char_count}")
            else:
                print("'關於' 區域文本為空。")

        except StaleElementReferenceException:
            print("'關於' 內容容器元素已過時，無法提取文本。")
            return 0 # 或者返回上一次成功獲取的值？暫定返回 0
        except Exception as e:
            print(f"提取或計算 '關於' 區域字數時出錯: {e}")
            return 0

        # --- 步驟 4: (可選) 操作完成後，是否需要點擊返回或做其他操作以恢復頁面狀態？
        # print("處理完 '關於' 區域。")
        # 例如，點擊回到主要 Posts 標籤頁？這取決於網站行為和後續爬取需求

        return about_word_count

    def check_chat_tab_exists(self) -> bool:
        """
        檢查頁面上是否存在 'Chats' 導航連結/標籤頁。

        Returns:
            bool: 如果找到 'Chats' 連結則返回 True，否則返回 False。
        """
        print("檢查是否存在 'Chats' 導航連結...")
        chat_link_selector = self.SELECTORS["chat_nav_link"]

        # 使用短超時快速檢查元素是否存在，不需要等待它可點擊
        chat_link = self._find_element(chat_link_selector, timeout=3) # 用 3 秒超時

        if chat_link:
            print("  找到 'Chats' 導航連結。")
            return True
        else:
            print("  未找到 'Chats' 導航連結。")
            return False
        
    def get_chat_room_details(self) -> Dict[str, int]:
        """
        點擊 'Chats' 標籤頁 (如果存在)，查找所有聊天室項目，
        並統計免費和付費（鎖定）聊天室的數量。

        Returns:
            Dict[str, int]: 包含 'free_chat_count' 和 'paid_chat_count' 的字典。
        """
        print("嘗試獲取聊天室詳細信息 (免費/付費數量)...")
        free_chat_count = 0
        paid_chat_count = 0
        default_return = {'free_chat_count': 0, 'paid_chat_count': 0}

        chat_nav_selector = self.SELECTORS["chat_nav_link"]
        chat_item_selector = self.SELECTORS["chat_list_item"]
        lock_icon_selector = self.SELECTORS["chat_lock_icon"]

        # --- 步驟 1: 檢查並點擊 'Chats' 導航連結 ---
        chat_link = self._find_element(chat_nav_selector, timeout=3)
        if not chat_link:
            print("  未找到 'Chats' 導航連結，無法獲取聊天室詳情。")
            return default_return

        print("  找到 'Chats' 連結，嘗試點擊...")
        if not self._click_element(chat_nav_selector, timeout=5):
            print("  點擊 'Chats' 導航連結失敗。")
            return default_return
        print("  成功點擊 'Chats' 連結。")

        # --- 步驟 2: 等待聊天室列表項加載 ---
        print(f"  等待聊天室列表項加載 (使用選擇器: {chat_item_selector})...")
        try:
            # 等待至少一個聊天室項目出現 (增加等待時間)
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located(chat_item_selector)
            )
            print("  聊天室列表項已初步加載。")
            # 可以選擇再短暫 sleep 一下確保渲染完成，但最好避免
            # time.sleep(1)
        except TimeoutException:
            print("  等待聊天室列表項加載超時，可能沒有聊天室或加載失敗。")
            # **重要**: 點擊 Chats 後可能需要導航回主頁面，否則後續爬蟲會出錯
            # self.driver.back() # 考慮是否需要返回
            return default_return

        # --- 步驟 3: 查找所有聊天室項目並遍歷 ---
        chat_items = self._find_elements(chat_item_selector)
        print(f"  找到 {len(chat_items)} 個聊天室列表項。")

        if not chat_items:
            # self.driver.back() # 同上，考慮返回
            return default_return

        for i, item in enumerate(chat_items):
            is_locked = False
            print(f"    處理第 {i+1} 個聊天室...")
            try:
                # 檢查內部是否有鎖定圖示
                lock_icon = self._find_element(lock_icon_selector, parent=item, timeout=0.1) # 快速檢查
                if lock_icon:
                    is_locked = True
                    print("      檢測到鎖定圖示 (付費/鎖定)。")
                # else:
                #     print("      未檢測到鎖定圖示 (免費)。")

                # 累加計數器
                if is_locked:
                    paid_chat_count += 1
                else:
                    free_chat_count += 1

            except StaleElementReferenceException:
                 print(f"    處理第 {i+1} 個聊天室時元素過時，跳過。")
                 continue
            except Exception as e:
                 print(f"    處理第 {i+1} 個聊天室時發生錯誤: {e}")
                 continue

        print(f"  聊天室統計完成: 免費={free_chat_count}, 付費={paid_chat_count}")

        # **重要**: 點擊 Chats 標籤後，頁面 URL 或狀態可能已改變。
        # 如果後續的 self.get_social_values() 等操作需要在原始頁面（例如 Posts 頁）進行，
        # 你可能需要 在這裡添加程式碼導航回去，例如：
        # print("  嘗試導航回主頁面...")
        # self.driver.back()
        # time.sleep(1) # 等待返回生效

        return {'free_chat_count': free_chat_count, 'paid_chat_count': paid_chat_count}

# 在 PatreonScraperRefactored 類別中

# 在 PatreonScraperRefactored 類別中

    def get_membership_tiers(self) -> List[Dict[str, Any]]:
        """
        爬取創作者定義的會員方案 (Tiers) 及其資訊。
        通過滾動輪播，在發現新卡片時立即解析並存儲其內容。
        """
        print("正在獲取會員方案 (Tiers) 資訊 (發現時立即解析策略)...")
        discovered_tiers_data = {} # 字典: {card_id: tier_info_dict}

        # --- 獲取選擇器 ---
        card_selector = self.SELECTORS["tier_card"]
        carousel_right_selector = self.SELECTORS["tier_carousel_right_button"]
        carousel_left_clickable_selector = self.SELECTORS["tier_carousel_left_button_clickable"]
        carousel_right_clickable_selector = self.SELECTORS["tier_carousel_right_button_clickable"]

        # --- 步驟 1: 處理輪播 ---
        print("檢查是否存在會員方案輪播...")
        right_button_exists = self._find_element(carousel_right_selector, timeout=2)

        if right_button_exists:
            print("檢測到會員方案輪播。")
            max_clicks = 15
            click_count_left = 0
            click_count_right = 0

            # --- 1a: 先滾動到最左邊 ---
            print("  嘗試滾動到最左端...")
            while click_count_left < max_clicks:
                clickable_button = self._find_element(carousel_left_clickable_selector, timeout=0.5)
                if clickable_button:
                    if self._click_element(carousel_left_clickable_selector, timeout=1):
                        click_count_left += 1; time.sleep(0.6)
                    else: break
                else: break
            if click_count_left == max_clicks: print(f"警告：向左滾動達到最大點擊次數 ({max_clicks})。")
            print("  應已到達最左端。")

            # --- 1b: 初始掃描並處理 ---
            print("  初始掃描並處理可見卡片...")
            initial_cards = self._find_elements(card_selector)
            print(f"    找到 {len(initial_cards)} 個初始卡片元素。")
            for card_element in initial_cards:
                parsed_info = self._parse_tier_card(card_element)
                if parsed_info and parsed_info.get('tier_id'):
                     card_id = parsed_info['tier_id']
                     if card_id not in discovered_tiers_data: # 確保只添加一次
                          print(f"    初始發現並處理卡片 ID: {card_id}")
                          discovered_tiers_data[card_id] = parsed_info
                     # else: print(f"    卡片 ID {card_id} 已處理過 (初始)。") # 調試用
                # else: print(f"    一個初始卡片解析失敗或無 ID。") # 調試用

            print(f"  初始處理後，已記錄 {len(discovered_tiers_data)} 個方案。")

            # --- 1c: 向右滾動，發現新卡片時處理 ---
            print("  嘗試向右滾動並處理新出現的卡片...")
            while click_count_right < max_clicks:
                clickable_button = self._find_element(carousel_right_clickable_selector, timeout=0.5)
                if clickable_button:
                    if self._click_element(carousel_right_clickable_selector, timeout=1):
                        click_count_right += 1
                        time.sleep(0.8) # 等待滾動和可能的加載

                        # 查找當前可見卡片
                        current_cards = self._find_elements(card_selector)
                        # print(f"    右滾第 {click_count_right} 次後找到 {len(current_cards)} 個卡片元素。") # 調試用
                        found_new_in_step = False
                        for card_element in current_cards:
                             card_id = card_element.get_attribute('id') # 先獲取ID檢查
                             if card_id and card_id not in discovered_tiers_data:
                                 # 發現了之前未記錄的 ID，立即解析
                                 print(f"    發現新卡片 ID: {card_id}，嘗試處理...")
                                 parsed_info = self._parse_tier_card(card_element)
                                 if parsed_info: # 確保解析成功
                                     discovered_tiers_data[card_id] = parsed_info
                                     found_new_in_step = True
                                 # else: print(f"    新卡片 ID {card_id} 解析失敗。") # 調試用

                        # if not found_new_in_step: print(f"    此步未發現新卡片。") # 調試用

                    else:
                        print("    點擊向右按鈕失敗，停止向右滾動。")
                        break
                else:
                    print("    未找到可點擊的向右按鈕，應已到達最右端。")
                    break
            if click_count_right == max_clicks: print(f"警告：向右滾動達到最大點擊次數 ({max_clicks})。")

        else:
            # --- 處理沒有輪播的情況 ---
            print("未檢測到會員方案輪播按鈕。直接查找並處理所有卡片...")
            all_cards = self._find_elements(card_selector)
            print(f"  找到 {len(all_cards)} 個卡片元素。")
            for card_element in all_cards:
                 parsed_info = self._parse_tier_card(card_element)
                 if parsed_info and parsed_info.get('tier_id'):
                      card_id = parsed_info['tier_id']
                      if card_id not in discovered_tiers_data: # 確保只添加一次
                           discovered_tiers_data[card_id] = parsed_info

        # --- 步驟 2: 整理結果 ---
        tiers_data = list(discovered_tiers_data.values()) # 將字典的值（解析好的 tier_info）轉換為列表
        print(f"會員方案資訊提取完成，共 {len(tiers_data)} 個方案。")
        return tiers_data

# 在 PatreonScraperRefactored 類別中修改

    def _parse_tier_card(self, card_element: webdriver.remote.webelement.WebElement) -> Optional[Dict[str, Any]]:
        """
        解析單個會員方案卡片元素。
        使用 get_attribute('textContent') 替代 .text 嘗試獲取不可見元素的文本。
        """
        card_id = None
        try:
            # (獲取 ID 的邏輯不變，包含重試)
            for _ in range(2):
                try:
                    card_id = card_element.get_attribute('id')
                    if card_id: break
                except StaleElementReferenceException: time.sleep(0.3)
            if not card_id:
                print("    警告：卡片元素沒有 ID 或多次嘗試後仍 Stale，無法處理。")
                return None

            tier_info = {'name': '', 'price': 0.0, 'description_word_count': 0, 'tier_id': card_id}
            max_retries = 3
            retry_delay = 0.5

            # --- 修改點：使用 textContent ---
            def get_element_text_content(selector, parent):
                element = None
                for attempt in range(max_retries):
                    try:
                        element = self._find_element(selector, parent=parent, timeout=1)
                        if element:
                            # 嘗試獲取 textContent
                            content = element.get_attribute('textContent')
                            if content is not None: # 確保屬性存在
                                return content.strip() # 返回去除首尾空格的文本
                            else:
                                # 如果 textContent 為 None，嘗試 innerText 作為備用
                                content = element.get_attribute('innerText')
                                return content.strip() if content is not None else ""
                    except StaleElementReferenceException:
                        if attempt == max_retries - 1: print(f"      查找元素時 Stale (ID: {card_id}, 多次重試失敗)")
                        else: time.sleep(retry_delay)
                    except TimeoutException:
                        print(f"      查找元素時 Timeout (ID: {card_id}, attempt {attempt+1})")
                        break # 超時通常不需重試相同元素
                    except Exception as e_find:
                         print(f"      查找或獲取文本時未知錯誤 (ID: {card_id}): {e_find}")
                         break # 其他錯誤也退出重試
                return "" # 如果所有嘗試都失敗，返回空字符串

            # 提取名稱
            name_text = get_element_text_content(self.SELECTORS["tier_name"], card_element)
            tier_info['name'] = name_text
            print(f"    DEBUG: 原始名稱文本 (ID: {card_id}): '{name_text}'") # 增加名稱的 DEBUG

            # 提取價格
            price_text_raw = get_element_text_content(self.SELECTORS["tier_price"], card_element)
            print(f"    DEBUG: 原始價格文本 (ID: {card_id}): '{price_text_raw}'")
            if price_text_raw: # 確保文本不是空的再解析
                price_value = parse_number(price_text_raw)
                tier_info['price'] = price_value if price_value is not None else 0.0

            # 提取描述區域
            desc_text_raw = get_element_text_content(self.SELECTORS["tier_description_area"], card_element)
            print(f"    DEBUG: 原始描述文本 (ID: {card_id}): '{desc_text_raw[:100]}...'") # 打印前100個字符
            if desc_text_raw:
                words = desc_text_raw.strip().split()
                tier_info['description_word_count'] = len(words)
            # --- 修改點結束 ---

            if tier_info['name'] or tier_info['price'] > 0:
                 print(f"    成功解析/記錄卡片 ID {card_id}: Name='{tier_info['name']}', Price={tier_info['price']}, DescWords={tier_info['description_word_count']}")
                 return tier_info
            else:
                 print(f"    卡片 ID {card_id} 解析完成，但未提取到有效 Name 或 Price。")
                 return tier_info # 仍然返回，標記已處理

        # (外層的 Stale 和 Exception 捕獲不變)
        except StaleElementReferenceException:
            print(f"  解析卡片 (ID: {card_id or '未知'}) 時卡片元素本身 Stale。")
            return None
        except Exception as e:
            print(f"  解析卡片 (ID: {card_id or '未知'}) 時發生未知錯誤: {e}")
            return None


    def _parse_year_item(self, item_element: webdriver.remote.webelement.WebElement) -> Optional[Tuple[str, int]]:
        """解析年份下拉選單項目"""
        try:
            text = item_element.text.strip()
            return extract_year_and_count(text)
        except Exception as e:
            # print(f"解析年份項目時出錯: {e}")
            return None

    def _parse_tier_item(self, item_element: webdriver.remote.webelement.WebElement) -> Optional[Tuple[str, int]]:
        """
        解析 Tier 下拉選單項目 (接收 <a> 元素)。
        從內部的 <p> 標籤獲取文本 "Tier Name (Count)"。
        """
        try:
            # **修改點：找到內部的 <p> 標籤來獲取文本**
            # TODO: 確認這個 p 標籤的選擇器是否穩定
            p_element = item_element.find_element(By.CSS_SELECTOR, "p.sc-gsDKAQ") # 嘗試使用 class 定位
            # 或者更簡單地： p_element = item_element.find_element(By.TAG_NAME, "p")
            text = p_element.text.strip()

            # 解析數量
            count_match = re.search(r'\((\d+)\)', text)
            count = int(count_match.group(1)) if count_match else 0

            # 解析 Tier 名稱 (移除括號和數字)
            tier_name = re.sub(r'\s*\(\d+\)\s*$', '', text).strip().lower().replace(" ", "_")
            if not tier_name: # 如果名稱為空，嘗試從 URL 或設為 unknown
                # (保留之前的 URL 解析邏輯作為備用，但通常文本解析足夠)
                tier_name = "unknown_tier"

            print(f"  解析到 Tier 項目: {tier_name} = {count} (來自文本: '{text}')")
            return tier_name, count

        except NoSuchElementException:
            print(f"  在 Tier 項目 <a> 內未找到預期的 <p> 標籤。")
            return None
        except StaleElementReferenceException:
            print("  解析 Tier 項目時元素過時。")
            return None
        except Exception as e:
            print(f"  解析 Tier 項目時發生未知錯誤: {e}")
            return None

    def _parse_type_item(self, item_element: webdriver.remote.webelement.WebElement) -> Optional[Tuple[str, int]]:
        """
        解析文章類型下拉選單項目 (接收 <button> 元素)。
        優先使用 SVG 的 data-tag 判斷類型，從 SVG 同級的 div 提取數量。
        """
        try:
            type_name = "unknown"
            count = 0 # 默認數量為 0

            # 1. 提取類型 (優先用 SVG data-tag) - 這部分邏輯看起來仍然有效
            try:
                # 使用 CSS Selector 查找 SVG 仍然可以
                svg_element = item_element.find_element(By.CSS_SELECTOR, "svg[data-tag]")
                data_tag = svg_element.get_attribute("data-tag")
                # (這裡可以根據需要添加或更新映射)
                tag_to_type = {
                    "IconPhoto": "image_posts", "IconPoll": "poll_posts", "IconEditorText": "text_posts",
                    "IconVideo": "video_posts", "IconHeadphones": "audio_posts", # <-- 確保有 audio
                    "IconPodcast": "podcast_posts", # <-- 根據需要添加 Podcast
                    "IconLink": "link_posts", "IconLivestream": "livestream_posts",
                    # 可以根據觀察到的其他 data-tag 添加更多類型
                }
                # 如果找不到映射，則歸類為 other_posts
                type_name = tag_to_type.get(data_tag, f"other_posts_{data_tag}") # fallback 包含 data_tag 幫助識別
                print(f"  從 data-tag '{data_tag}' 解析到類型: {type_name}")
            except NoSuchElementException:
                print(f"  按鈕內未找到帶 data-tag 的 SVG，無法確定類型。")
                type_name = "unknown_type_no_svg" # 標記為未知類型


            # 2. 提取數量 (從包含文本的 div) - !! 修改的部分 !!
            try:
                # 使用 XPath 找到包含 SVG 的 span 的下一個同級 div
                # .// 表示在當前 item_element (按鈕) 內部查找
                # span[svg[@data-tag]] 找到包含帶 data-tag 的 svg 的 span
                # /following-sibling::div 找到該 span 的下一個 div 兄弟節點
                text_div = item_element.find_element(By.XPATH, ".//span[svg[@data-tag]]/following-sibling::div")
                text = text_div.text.strip()
                # 解析數量
                count_match = re.search(r'\((\d+)\)', text) # 從文本中找 (數字)
                if count_match:
                    count = int(count_match.group(1))
                    print(f"  從文本 '{text}' 中提取到數量: {count}")
                else:
                    print(f"  在文本 '{text}' 中未找到括號內的計數。")
                    # 如果需要，可以嘗試從 text 中解析類型名稱作為備用
                    # type_name_from_text = re.sub(r'\s*\(\d+\)\s*$', '', text).strip().lower()
                    # if type_name == "unknown_type_no_svg": type_name = f"{type_name_from_text}_posts"

            except NoSuchElementException:
                # 如果找不到那個特定的 div，可能是結構又變了，或者沒有 SVG (上面的 try 會先處理)
                print(f"  在按鈕內找不到預期的包含文本的 div (SVG 的同級元素)。HTML: {item_element.get_attribute('outerHTML')}")
                # 可以嘗試直接獲取按鈕的文本作為備用
                try:
                     button_text = item_element.text.strip()
                     count_match = re.search(r'\((\d+)\)', button_text)
                     if count_match: count = int(count_match.group(1))
                     print(f"  備用：從按鈕文本 '{button_text}' 提取數量: {count}")
                except: pass # 忽略備用方案的錯誤

            except Exception as e:
                print(f"  提取類型數量時出錯: {e}")

            # 返回結果
            if type_name != "unknown": # 只要類型不是 unknown 就返回
                print(f"  => 解析到類型項目: {type_name} = {count}")
                return type_name, count
            else:
                 print(f"  => 無法完全解析此類型項目。")
                 return None # 返回 None 表示解析失敗

        except StaleElementReferenceException:
            print("  解析類型項目時元素過時。")
            return None
        except Exception as e:
            print(f"  解析類型項目時發生未知錯誤: {e}")
            return None
        # return None # 確保所有路徑都有返回值


    def _get_dropdown_data(self,
                           button_selector: Tuple[str, str],
                           item_locator: Tuple[str, str],
                           item_parser: Callable[[webdriver.remote.webelement.WebElement], Optional[Tuple[str, int]]],
                           container_selector: Tuple[str, str] = SELECTORS["dropdown_container"]) -> Dict[str, int]:
        """
        通用的下拉選單數據獲取函數。

        Args:
            button_selector: 觸發下拉選單的按鈕選擇器。
            item_locator: 下拉選單中每個選項的定位器 (通常是 By.TAG_NAME, "a" 或 "button")。
            item_parser: 一個函數，接收選項的 WebElement，返回 (key, value) 元組或 None。
            container_selector: 下拉選單容器的選擇器。

        Returns:
            一個包含解析結果的字典。
        """
        results = {}
        print(f"嘗試打開下拉選單: {button_selector}")

        # 滾動到頂部，增加按鈕可見性
        self.driver.execute_script("window.scrollTo(0, 0);")
        try:
            # 短暫等待確保滾動生效
            time.sleep(0.5)
        except: pass

        # 點擊按鈕打開下拉選單
        if not self._click_element(button_selector, timeout=10):
            print(f"無法點擊按鈕 {button_selector}，跳過此下拉選單。")
            return results

        # 等待並查找下拉選單容器
        print(f"等待下拉選單容器: {container_selector}")
        dropdown_container = self._find_element(container_selector, timeout=5) # 容器出現通常較快

        if dropdown_container is None:
            print(f"無法找到下拉選單容器 {container_selector}。")
             # 嘗試點擊 body 關閉可能存在的不可見菜單
            try: self._click_element((By.TAG_NAME, "body"), timeout=1); time.sleep(0.5)
            except: pass
            return results

        # 查找並處理選單項目
        print(f"查找選單項目: {item_locator}")
        menu_items = self._find_elements(item_locator, parent=dropdown_container)
        print(f"找到 {len(menu_items)} 個選單項目。")

        for item in menu_items:
            try:
                # 增加檢查，確保元素仍然有效
                item_text_debug = item.text # 嘗試訪問，如果失敗則元素可能過時
                parsed_data = item_parser(item)
                if parsed_data:
                    key, value = parsed_data
                    results[key] = value
                    print(f"  解析到項目: {key} = {value}")
            except StaleElementReferenceException:
                 print("  處理選單項目時元素過時，跳過。")
                 continue # 元素已失效，跳過
            except Exception as e:
                print(f"  處理選單項目時發生錯誤: {e}")

        # 關閉下拉選單 (點擊 body 通常可以)
        print("嘗試關閉下拉選單...")
        try:
            # 點擊 body 的空白區域
            body_element = self._find_element((By.TAG_NAME, 'body'))
            if body_element:
                 webdriver.ActionChains(self.driver).move_to_element(body_element).click().perform()
            # 等待菜單消失 (可選但建議)
            WebDriverWait(self.driver, 5).until(
                 EC.invisibility_of_element_located(container_selector)
            )
            print("下拉選單已關閉。")
        except TimeoutException:
             print("警告: 無法確認下拉選單是否已關閉。")
        except Exception as e:
            print(f"關閉下拉選單時出錯: {e}")
            # 作為備用，發送 ESC 鍵
            try: webdriver.ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
            except: pass

        return results

    def get_post_years(self) -> Dict[str, int]:
        """獲取各年份的文章數量"""
        print("獲取文章年份數據...")
        button_selector = self.SELECTORS["year_button"] # 使用年份按鈕選擇器
        return self._get_dropdown_data(
            button_selector=button_selector,
            item_locator=(By.TAG_NAME, "a"), # <--- 指定查找 <a> 標籤
            item_parser=self._parse_year_item,
            container_selector=(By.XPATH, "//div[@role='dialog' and @aria-label='Sort posts by date']") # <--- 可選：更精確的容器
        )

    def get_post_tiers(self) -> Dict[str, int]:
        """獲取各 Tier 的文章數量"""
        print("獲取文章 Tier 數據...")
        button_selector = self.SELECTORS["tier_button"] # 使用 Tier 按鈕選擇器
        return self._get_dropdown_data(
            button_selector=button_selector,
            item_locator=(By.TAG_NAME, "a"), # <--- 指定查找 <a> 標籤
            item_parser=self._parse_tier_item,
            container_selector=(By.XPATH, "//div[@role='dialog' and @aria-label='Sort posts by tier']") # <--- 可選：更精確的容器
        )

    def get_post_types(self) -> Dict[str, int]:
        """獲取各類型的文章數量"""
        print("獲取文章類型數據...")
        button_selector = self.SELECTORS["post_type_button"] # 使用類型按鈕選擇器
        return self._get_dropdown_data(
            button_selector=button_selector,
            item_locator=(By.TAG_NAME, "button"), # <--- 指定查找 <button> 標籤
            item_parser=self._parse_type_item,
            container_selector=(By.XPATH, "//div[@role='dialog' and @aria-label='Sort posts by post type']") # <--- 可選：更精確的容器
        )

    def scroll_page_to_load_more(self, max_scrolls: int = 10) -> None:
        """
        滾動頁面或點擊「載入更多」按鈕以加載內容。
        現在只處理加載，不返回數據。數據由 get_social_value 獲取。
        """
        print("開始嘗試加載更多內容 (滾動/點擊)...")
        scroll_attempts = 0
        # TODO: 確認 Load More 按鈕選擇器
        load_more_selector = self.SELECTORS["load_more_button"]

        last_height = self.driver.execute_script("return document.body.scrollHeight")

        while scroll_attempts < max_scrolls:
            print(f"加載嘗試 {scroll_attempts + 1}/{max_scrolls}...")

            load_more_found_and_visible = False
            try:
                # 檢查按鈕是否存在且可見
                load_more_button = WebDriverWait(self.driver, 2).until( # 短暫等待按鈕出現
                    EC.visibility_of_element_located(load_more_selector)
                )
                load_more_found_and_visible = True
            except TimeoutException:
                # print("未找到可見的'載入更多'按鈕。")
                load_more_found_and_visible = False

            clicked_button = False
            if load_more_found_and_visible:
                print("嘗試點擊 '載入更多' 按鈕...")
                if self._click_element(load_more_selector, timeout=5):
                     clicked_button = True
                     # 點擊後等待，最好是等待特定元素加載或 spinner 消失
                     print("點擊後等待內容加載...")
                     # 簡單等待高度變化
                     try:
                         WebDriverWait(self.driver, 10).until(
                             lambda driver: driver.execute_script("return document.body.scrollHeight") > last_height
                         )
                         print("檢測到頁面高度增加。")
                     except TimeoutException:
                         print("點擊按鈕後頁面高度未在預期內增加。")
                     # time.sleep(2) # 避免使用 sleep
                else:
                     print("'載入更多' 按鈕點擊失敗。")


            # 如果沒有找到或點擊按鈕，則滾動
            if not clicked_button:
                 print("向下滾動頁面...")
                 self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                 # 滾動後等待
                 print("滾動後等待內容加載...")
                 # 簡單等待高度變化
                 try:
                     WebDriverWait(self.driver, 5).until( # 滾動觸發的加載可能較快
                         lambda driver: driver.execute_script("return document.body.scrollHeight") > last_height
                     )
                     print("檢測到頁面高度增加。")
                 except TimeoutException:
                     # print("滾動後頁面高度未在預期內增加。") # 可能已到底部
                     pass # 繼續檢查最終高度
                 # time.sleep(1.5) # 避免使用 sleep

            # 檢查是否真的到底了
            try:
                time.sleep(0.5) # 給 JS 一點時間更新高度
                new_height = self.driver.execute_script("return document.body.scrollHeight")
                if new_height == last_height:
                     print("頁面高度未改變，判斷已到達底部。")
                     break # 停止加載
                else:
                     print(f"頁面高度已從 {last_height} 增加到 {new_height}。")
                     last_height = new_height
            except Exception as height_e:
                 print(f"檢查頁面高度時出錯: {height_e}")
                 break # 出錯時停止

            scroll_attempts += 1
            # 添加小的隨機延遲
            time.sleep(random.uniform(0.5, 1.5))

        print(f"加載更多內容結束，共完成 {scroll_attempts} 次嘗試。")


    def get_social_values(self) -> Dict[str, int]:
        """
        遍歷頁面上的貼文，區分公開和私密貼文，分別統計按讚數和留言數。
        """
        print("正在區分公開/私密貼文並統計社交互動數據...")
        public_likes = 0
        public_comments = 0
        locked_likes = 0
        locked_comments = 0

        # 先確保內容已盡可能加載
        self.scroll_page_to_load_more(max_scrolls = 5) # 增加滾動次數

        print("查找所有點讚和留言元素...")
        # TODO: 確認點讚和留言元素的選擇器
        post_cards = self._find_elements(self.SELECTORS["post_card_container"])
        print(f"找到 {len(post_cards)} 個貼文卡片容器。")


        for i, card in enumerate(post_cards):
            is_locked = False
            post_likes = 0
            post_comments = 0
            print(f"  處理第 {i+1} 個貼文卡片...")

            try:
                # 3.1 檢查是否為私密貼文 (在卡片內部查找鎖定標誌)
                # 使用 timeout=0.1 快速檢查是否存在，避免等待
                lock_indicator = self._find_element(self.SELECTORS["lock_icon_indicator"], parent=card, timeout=0.1)
                if lock_indicator:
                    is_locked = True
                    print("貼文已鎖定。")
                # else:
                #     print("貼文是公開的。")

                # 3.2 在卡片內部查找按讚數
                # 注意選擇器需要是相對的，或者確保全局選擇器能正確匹配到卡片內的元素
                # 使用 '.' 開頭的相對 XPath
                like_element_xpath = ".//span[@data-tag='like-count']"
                like_element = self._find_element((By.XPATH, like_element_xpath), parent=card, timeout=0.1)
                if like_element:
                    like_text = like_element.text.strip()
                    count = extract_integer(like_text) # 使用輔助函數
                    if count is not None:
                        post_likes = count
                        print(f"找到按讚數: {post_likes}")

                # 3.3 在卡片內部查找留言數
                # 使用 '.' 開頭的相對 XPath
                comment_element_xpath = ".//a[@data-tag='comment-post-icon']//p"
                comment_element = self._find_element((By.XPATH, comment_element_xpath), parent=card, timeout=0.1)
                if comment_element:
                    comment_text = comment_element.text.strip()
                    count = extract_integer(comment_text)
                    if count is not None:
                        post_comments = count
                        print(f"找到留言數: {post_comments}")

                # 3.4 根據是否鎖定，累加到對應計數器
                if is_locked:
                    locked_likes += post_likes
                    locked_comments += post_comments
                else:
                    public_likes += post_likes
                    public_comments += post_comments

            except StaleElementReferenceException:
                 print(f"處理第 {i+1} 個貼文卡片時元素過時，跳過此卡片。")
                 continue
            except Exception as e:
                 print(f"處理第 {i+1} 個貼文卡片時發生錯誤: {e}")
                 continue # 跳過這個卡片，繼續處理下一個

        print("-" * 20)
        print(f"統計結果: ")
        print(f"  公開 - Likes: {public_likes}, Comments: {public_comments}")
        print(f"  私密 - Likes: {locked_likes}, Comments: {locked_comments}")
        print("-" * 20)

        return {
            'public_likes': public_likes,
            'public_comments': public_comments,
            'locked_likes': locked_likes,
            'locked_comments': locked_comments
        }

    def get_social_links(self) -> Dict[str, Any]:
        """獲取創作者頁面上的社群平台連結"""
        print("正在獲取社群平台連結...")
        social_platforms = {'facebook': 'no', 'twitter': 'no', 'instagram': 'no', 'youtube': 'no', 'twitch': 'no', 'tiktok': 'no', 'discord': 'no'}
        social_link_count = 0
        processed_links = set()

        try:
            # 嘗試定位包含社群連結的特定區域
            link_area = self._find_element(self.SELECTORS["social_link_area"])
            if link_area:
                print("在指定區域查找社群連結...")
                links = self._find_elements(self.SELECTORS["social_link"], parent=link_area)
            else:
                print("未找到特定社群連結區域，查找頁面所有連結...")
                links = self._find_elements(self.SELECTORS["social_link"])

            print(f"找到 {len(links)} 個潛在連結。")

            for link in links:
                try:
                    href = link.get_attribute('href')
                    if href and href not in processed_links and not href.startswith("https://www.patreon.com/"):
                         href_lower = href.lower()
                         platform_found = None
                         # 平台判斷邏輯
                         if 'facebook.com' in href_lower: platform_found = 'facebook'
                         elif 'twitter.com' in href_lower or 'x.com' in href_lower: platform_found = 'twitter'
                         elif 'instagram.com' in href_lower: platform_found = 'instagram'
                         # 注意：Youtube 連結可能需要更精確判斷，避免誤判圖片等
                         elif 'youtube.com/channel/' in href_lower or 'youtube.com/user/' in href_lower or 'youtube.com/@' in href_lower: platform_found = 'youtube'
                         elif 'twitch.tv' in href_lower: platform_found = 'twitch'
                         elif 'discord.gg' in href_lower or 'discord.com/invite' in href_lower: platform_found = 'discord'
                         elif 'tiktok.com' in href_lower: platform_found = 'tiktok'

                         if platform_found and social_platforms[platform_found] == 'no':
                              social_platforms[platform_found] = 'yes'
                              social_link_count += 1
                              processed_links.add(href)
                              print(f"  找到社群連結: {platform_found} - {href[:50]}...") # 截斷長連結

                except StaleElementReferenceException: continue
                except Exception: pass # 忽略處理單個連結的錯誤

        except Exception as e:
            print(f"獲取社群連結時發生錯誤: {e}")

        social_platforms['social_link_count'] = social_link_count
        print(f"社群連結處理完成: {social_platforms}")
        return social_platforms

    def scrape_url(self, url: str) -> Optional[Dict[str, Any]]:
        """
        爬取單個 URL 的所有內容。

        Args:
            url (str): 要爬取的 Patreon 創作者頁面 URL。

        Returns:
            包含爬取數據的字典，如果發生嚴重錯誤則返回 None。
        """
        print(f"\n--- 開始爬取 URL: {url} ---")
        try:
            self.driver.get(url)
            # 等待頁面加載標誌，例如創作者名稱
            print("等待頁面加載...")
            if not self._find_element(self.SELECTORS["creator_name"], timeout=20): # 增加頁面加載等待時間
                 print("頁面關鍵元素加載超時，可能 URL 無效或頁面結構改變。")
                 return None # 無法加載關鍵信息，跳過此 URL
            print("頁面初步加載完成。")

            self.handle_age_verification()

            # 滾動到頂部，確保後續操作的基準點一致
            self.driver.execute_script("window.scrollTo(0, 0);")
            try: time.sleep(0.5) # 等待滾動生效
            except: pass

            # --- 依次獲取各部分數據 ---
            static_data = self.get_static_content()
            print(f"\nDEBUG: static_data received in scrape_url:")
            import pprint
            pprint.pprint(static_data)
            social_links_data = self.get_social_links()
            membership_tiers_data = self.get_membership_tiers()
            post_types_data = self.get_post_types()
            post_years_data = self.get_post_years()
            post_tiers_data = self.get_post_tiers() # Tier 數據
            social_values_data = self.get_social_values() # 點讚和留言
            has_chat_tab = self.check_chat_tab_exists() #檢查是不是有聊天室
            chat_details = self.get_chat_room_details()
            free_chat_count = chat_details.get('free_chat_count', 0)
            paid_chat_count = chat_details.get('paid_chat_count', 0)
            has_chat_tab = 'yes' if (free_chat_count > 0 or paid_chat_count > 0) else 'no'

            about_word_count = self.get_about_section_word_count()

             # 計算總連結數 (如果需要)
            print("正在計算頁面外部連結數...")
            all_a_tags = self.driver.find_elements(By.TAG_NAME, "a")
            external_links_count = 0
            #processed_hrefs_for_total = set()
           

            for link_element in all_a_tags:
                try:
                    href = link_element.get_attribute('href')
                    # 關鍵過濾條件
                    if href and href.strip() and not href.startswith("#") and not href.startswith("https://www.patreon.com/"):
                        external_links_count += 1
                        # # 如果需要去重計數域名，取消註解以下部分
                        # from urllib.parse import urlparse # 需要導入
                        # parsed_uri = urlparse(href)
                        # domain = f"{parsed_uri.scheme}://{parsed_uri.netloc}"
                        # if domain not in processed_hrefs_for_total:
                        #     external_links_count += 1
                        #     processed_hrefs_for_total.add(domain)
                except StaleElementReferenceException:
                    continue
                except Exception as e:
                    print(f"處理連結標籤時出錯: {e}")
                    continue

            total_links = external_links_count
            print(f"頁面外部連結數: {total_links}")

            # --- 組合最終結果 ---
            result = {
                'URL': url,
                'creator_name': static_data.get('creator_name', ''),
                'total_post': static_data.get('total_posts', 0),
                'patreon_number': static_data.get('patron_count', 0),
                
                'income_per_month': static_data.get('income_per_month', 0), # 通常難以獲取

                # 字典數據源 (用於後續處理)
                'tier_post_dict': post_tiers_data,
                'post_year_dict': post_years_data,
                'post_type_dict': post_types_data,
                'social_links_dict': social_links_data,

                # 計數數據
                'tier_count': len(post_tiers_data),
                'total_links': total_links,
                'social_link_count': social_links_data.get('social_link_count', 0),

                'about_word_count': about_word_count,

                # 區分後的按讚和留言數
                'public_likes': social_values_data.get('public_likes', 0),
                'public_comments': social_values_data.get('public_comments', 0),
                'locked_likes': social_values_data.get('locked_likes', 0),
                'locked_comments': social_values_data.get('locked_comments', 0),
                #紀錄是否有聊天室
                'has_chat_tab': 'yes' if has_chat_tab else 'no', # 記錄 'yes' 或 'no'
                'free_chat_count': free_chat_count,
                'paid_chat_count': paid_chat_count,

                'membership_tiers': membership_tiers_data,
                'tier_count': len(post_tiers_data),
                'membership_tier_count': len(membership_tiers_data), # 計算會員等級數量
                'about_word_count': about_word_count,
    
            
            }

            result['total_likes_combined'] = result['public_likes'] + result['locked_likes']
            result['total_comments_combined'] = result['public_comments'] + result['locked_comments']

            print(f"--- URL: {url} 爬取完成 ---")
            print(f"DEBUG: Final result dict before return: {result}")
            return result

        except Exception as e:
            print(f"爬取 URL {url} 時發生嚴重錯誤: {e}")
            import traceback
            traceback.print_exc() # 打印詳細錯誤信息
            return {
                'URL': url, 'creator_name': '','total_post': 0,'patreon_number': 0, 'income_per_month' : 0, 
                'tier_post_dict': {}, 'post_year_dict': {}, 'post_type_dict': {}, 'social_links_dict': {'social_link_count': 0},
                'tier_count': 0, 'total_links': 0,'social_link_count': 0,
                'about_word_count': 0, 
                'has_chat_tab': 'no', 'free_chat_count': 0, 'paid_chat_count': 0,
                'public_likes': 0, 'public_comments': 0, 'locked_likes': 0, 'locked_comments': 0,
                'total_likes_combined': 0, 'total_comments_combined': 0 
            }

    def _prepare_row_data(self, data: Dict[str, Any], fieldnames: List[str]) -> Dict[str, Any]:
        """
        根據 fieldnames 準備用於寫入 CSV 的單行數據。

        Args:
            data (Dict[str, Any]): 從 scrape_url 返回的原始數據字典。
            fieldnames (List[str]): CSV 的欄位名列表。

        Returns:
            準備好寫入 CSV 的字典。
        """
        row_data = {}

        # 填充基本欄位
        for field in ['URL', 'creator_name', 'total_post', 'patreon_number', 'income_per_month',
                      'tier_count', 'total_links', 'social_link_count','about_word_count',
                      'public_likes', 'public_comments', 'locked_likes', 'locked_comments',
                      'has_chat_tab', 'free_chat_count', 'paid_chat_count', 'membership_tier_count',
                      ]:
            if field in fieldnames:
                default_val = '' if field in ['URL', 'creator_name'] else ('no' if field == 'has_chat_tab' else 0)
                row_data[field] = data.get(field, default_val)


        # 處理字典數據 -> 字串 (按用戶要求)
        if 'tier_post_data' in fieldnames:
            tier_dict = data.get('tier_post_dict', {})
            row_data['tier_post_data'] = str(tier_dict) if tier_dict else '{}'
        if 'post_year_count' in fieldnames: # CSV 欄位名仍用 post_year_count
            year_dict = data.get('post_year_dict', {})
            row_data['post_year_count'] = str(year_dict) if year_dict else '{}'

        if 'membership_tiers_json' in fieldnames:
            tiers_list = data.get('membership_tiers', []) # 從 data 獲取列表
            # ensure_ascii=False 確保中文等字符能正確顯示
            row_data['membership_tiers_json'] = json.dumps(tiers_list, ensure_ascii=False) if tiers_list else '[]'

        # 展開社群平台連結狀態
        social_links_dict = data.get('social_links_dict', {})
        for platform in ['facebook', 'twitter', 'instagram', 'youtube', 'twitch', 'tiktok', 'discord']:
            if platform in fieldnames:
                row_data[platform] = social_links_dict.get(platform, 'no')

        # 展開文章類型計數
        post_type_dict = data.get('post_type_dict', {})
        for type_key, type_value in post_type_dict.items():
            if type_key in fieldnames:
                row_data[type_key] = type_value

        # 為 fieldnames 中存在但 row_data 中缺失的欄位設置默認值 (主要是展開的文章類型)
        for field in fieldnames:
            if field not in row_data:
                 # 判斷是否為字典字串欄位
                is_dict_string = field in ['tier_post_data', 'post_year_count']
                is_social_yes_no = field in ['facebook', 'twitter', 'instagram', 'youtube', 'twitch', 'tiktok', 'discord']
                is_json_string = field == 'membership_tiers_json'
                if is_json_string: row_data[field] = '[]'
                elif is_dict_string: row_data[field] = '{}'
                elif is_social_yes_no: row_data[field] = 'no'
                elif field in ['URL', 'creator_name']: pass # 通常已處理
                else: row_data[field] = 0 # 其他 (如文章類型) 默認為 0


        return row_data


    def scrape_multiple_targets(self, urls: List[str]):
        """爬取多個目標 URL 並保存到 CSV"""
        if not urls:
            print("沒有提供 URL，無法爬取。")
            return

        # *** 明確定義所有期望的 CSV 欄位 ***
        # 順序可以根據你的偏好調整
        fieldnames = [
            # 基本信息
            'URL', 'creator_name', 'total_post', 'patreon_number', 'income_per_month',
            # 聚合信息 (字典字串 + 計數)
            'tier_post_data', 'post_year_count', 'tier_count',
            'total_links',
            # 社群連結狀態 + 計數
            'facebook', 'twitter', 'instagram', 'youtube', 'twitch', 'tiktok', 'discord', 'social_link_count',
            # 文章類型計數 (展開)
            'text_posts', 'image_posts', 'video_posts', 'podcast_posts', 'audio_posts',
            'link_posts', 'poll_posts', 'livestream_posts',
            'other_posts', 'unknown',

            'public_likes', 'public_comments', 'locked_likes', 'locked_comments',
            'total_likes_combined', 'total_comments_combined',

            'free_chat_count', 'paid_chat_count',# 是否有聊天室

            'membership_tier_count','membership_tiers_json',

            'about_word_count' # 其他和未知類型
        ]

        fieldnames = sorted(list(set(fieldnames)), key=lambda x: fieldnames.index(x)) # 去重並保持順序
        print(f"CSV 欄位將是: {fieldnames}")

        results_list = [] # 先將結果存儲在列表中

        for i, url in enumerate(urls):
            data = self.scrape_url(url) # scrape_url 現在返回 None 表示失敗
            if data: # 僅處理成功爬取的數據
                row_data = self._prepare_row_data(data, fieldnames)
                results_list.append(row_data)
                print(f"成功處理 URL ({i+1}/{len(urls)}): {url}")
            else:
                 print(f"跳過失敗的 URL ({i+1}/{len(urls)}): {url}")

            # 添加隨機延遲，避免請求過於頻繁
            if i < len(urls) - 1: # 最後一個 URL 後不需要等待
                delay = random.uniform(5, 10) # 增加延遲範圍
                print(f"等待 {delay:.1f} 秒...")
                time.sleep(delay)

        # --- 所有 URL 處理完畢後，一次性寫入 CSV ---
        if results_list:
            print(f"\n準備將 {len(results_list)} 條記錄寫入 CSV: {self.output_path}")
            try:
                with open(self.output_path, 'w', newline='', encoding='utf-8-sig') as csvfile:
                    writer = csv.DictWriter(csvfile, fieldnames=fieldnames, extrasaction='ignore')
                    writer.writeheader()
                    writer.writerows(results_list)
                print("CSV 文件寫入成功！")
            except IOError as e:
                 print(f"寫入 CSV 文件時出錯: {e}")
            except Exception as e:
                 print(f"寫入 CSV 時發生未知錯誤: {e}")
        else:
            print("沒有成功爬取到任何數據，未生成 CSV 文件。")


    def close(self):
        """關閉瀏覽器"""
        if hasattr(self, 'driver') and self.driver:
            try:
                print("正在關閉 WebDriver...")
                self.driver.quit()
                print("WebDriver 已關閉。")
            except Exception as e:
                print(f"關閉 WebDriver 時出錯: {e}")

def load_urls_from_txt(filepath: str) -> List[str]:
    """從文字檔讀取 URL 列表"""
    urls = []
    if not os.path.exists(filepath):
         print(f"錯誤：URL 文件不存在: {filepath}")
         return urls
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    urls.append(line)
        print(f"從 {filepath} 成功載入 {len(urls)} 個 URL。")
    except Exception as e:
        print(f"讀取 URL 文件 {filepath} 時發生錯誤: {e}")
    return urls

if __name__ == "__main__":
    #紀錄爬蟲時間
    start_time_monotonic = time.monotonic()
    print(f"爬蟲開始執行於: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("-" * 30)
    url_file = os.path.join(os.path.dirname(__file__), "urls_for_scrape.txt") 
    

    output_directory = os.path.join(os.path.dirname(__file__), "Patreon_Scraped_Data") 

    run_headless = False   # 是否使用無頭模式 (True 或 False)

    target_urls = load_urls_from_txt(url_file)

    if not target_urls:
        print("未能載入任何 URL，程式結束。")
    else:
        scraper = None # 初始化為 None
        try:
            scraper = PatreonScraperRefactored(output_dir=output_directory, headless=run_headless)
            print(f"準備開始爬取 {len(target_urls)} 個目標...")
            scraper.scrape_multiple_targets(target_urls)
            print("\n所有目標處理完成。")
        except Exception as e:
            print(f"\n爬取過程中發生未預期的嚴重錯誤: {e}")
            import traceback
            traceback.print_exc()
        finally:
            if scraper:
                scraper.close()

        end_time_monotonic = time.monotonic() # 記錄結束時間
        total_duration_seconds = end_time_monotonic - start_time_monotonic

        minutes, seconds = divmod(total_duration_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        
        print("-" * 30)
        print(f"爬蟲總執行時間:")
        if hours > 0:
            print(f"  {int(hours)} 小時 {int(minutes)} 分鐘 {seconds:.2f} 秒")
        elif minutes > 0:
            print(f"  {int(minutes)} 分鐘 {seconds:.2f} 秒")
        else:
            print(f"  {seconds:.2f} 秒")
        print("-" * 30)

        print("程式執行完畢。")