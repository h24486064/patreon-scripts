# 1. Imports (請確保這些都已在你的檔案頂部)
import time
import csv
import os
import re
import requests
import random
from datetime import datetime
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options
# 從 selenium.common.exceptions 導入需要的例外
from selenium.common.exceptions import TimeoutException, NoSuchElementException, ElementClickInterceptedException
from typing import Optional, Dict, Any

# 2. 你的類別定義 (替換掉你原有的整個 class)
class HybridPatreonScraper:
    def __init__(self, output_path: Optional[str] = None):
        # 設置 Selenium
        chrome_options = Options()
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        # 可以考慮添加 headless 選項，如果你不需要看到瀏覽器介面
        # chrome_options.add_argument("--headless")

        self.driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=chrome_options
        )
        # *** 重要：增加預設等待時間 ***
        self.wait = WebDriverWait(self.driver, 10) # 將等待時間從 1 秒增加到 10 秒

        # 設置請求標頭 (這部分主要用於 requests，對 Selenium 影響不大)
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }

        # 設置輸出路徑 (使用 os.path.join 更健壯)
        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            # 建議使用相對路徑或更通用的方式獲取基礎目錄
            # default_dir = os.path.join(os.path.dirname(__file__), "output_data") # 示例：存儲在腳本目錄下的 output_data 文件夾
            default_dir = "D:/成功大學/論文資料/爬蟲資料" # 暫時保留你的路徑
            os.makedirs(default_dir, exist_ok=True)
            self.output_path = os.path.join(default_dir, f'patreon_data_{timestamp}_14.csv') # 更新版本號
        else:
            self.output_path = output_path
        print(f"輸出檔案將儲存至: {self.output_path}")

        # 定義靜態內容選擇器 (保留你的定義)
        self.static_selectors = {
            'creator_name': [
                "//h1[contains(@class, 'sc-')]",
                "//div[contains(@class, 'sc-')]//h1",
                "//header//h1"
            ],
            'patron_count': [
                "//span[contains(text(), 'patron')]/parent::li/span",
                "//ul/li[1]/span[contains(@class, 'sc-')]",
                "//header//ul/li[1]/span"
            ],
            'total_posts': [
                "//span[contains(text(), 'post')]/parent::li/span",
                "//ul/li[2]/span[contains(@class, 'sc-')]",
                "//header//ul/li[2]/span"
            ],
            'monthly_income': [
                "//span[contains(text(), '$')]/parent::li/span",
                "//ul/li[3]/span[contains(@class, 'sc-')]",
                "//header//ul/li[3]/span"
            ]
        }

    # --- 保留你其他的輔助方法 ---
    def parse_number(self, text: Optional[str]) -> Optional[float]:
        """改進的數字解析方法"""
        if not text:
            return None
        clean_text = re.sub(r'[^\d.KMk]', '', str(text))
        clean_text = clean_text.upper()
        try:
            if 'K' in clean_text:
                return float(clean_text.replace('K', '')) * 1000
            elif 'M' in clean_text:
                return float(clean_text.replace('M', '')) * 1000000
            return float(clean_text)
        except ValueError:
            return None

    def extract_integer(self, text: Optional[str]) -> Optional[int]:
        """從文字中提取整數"""
        if not text:
            return None
        matches = re.findall(r'\d+', str(text))
        return int(matches[0]) if matches else None

    def _prepare_tier_post_data(self, data):
        """將會員等級(tier)數據轉換為字串格式"""
        public_post = data.get('public_post', {})
        if public_post:
            return str(public_post)
        return "{}"

    def _prepare_post_year_data(self, data):
        """將年份數據轉換為字串格式"""
        # 注意：你原來的程式碼這裡的 key 是 'year_post'，但 scrape_url 返回的是 'post_year_count'
        year_post = data.get('post_year_count', {}) # 使用正確的 key
        if year_post:
            return str(year_post)
        return "{}"

    def handle_age_verification(self):
        """處理年齡確認彈窗"""
        age_verification_xpaths = [
            "/html/body/div[2]/div[2]/div/div[2]/div/div[2]/div/button[1]",
            "/html/body/div[3]/div[2]/div/div[2]/div/div[2]/div/button[1]",
            "/html/body/div[4]/div[2]/div/div[2]/div/div[2]/div/button[1]"
        ]
        # 使用更短的 WebDriverWait，因為彈窗通常很快出現
        age_wait = WebDriverWait(self.driver, 3)
        for xpath in age_verification_xpaths:
            try:
                age_button = age_wait.until(
                    EC.element_to_be_clickable((By.XPATH, xpath))
                )
                age_button.click()
                print("已處理年齡驗證彈窗。")
                time.sleep(1) # 點擊後短暫等待確保生效
                return True
            except TimeoutException:
                continue # 沒找到這個 xpath 的按鈕，嘗試下一個
            except Exception as e:
                print(f"處理年齡驗證 XPath {xpath} 出錯: {e}")
                continue # 出錯也嘗試下一個
        print("未找到年齡驗證彈窗或處理失敗。")
        return False

    # --- 保留你的主要爬取邏輯方法 ---
    def get_static_content(self, url: str) -> Dict[str, Any]:
        """使用 Selenium 爬取静态内容"""
        # (你的 get_static_content 程式碼保持不變)
        try:
            static_content = {}
            for field, xpaths in self.static_selectors.items():
                content_found = False
                for xpath in xpaths:
                    try:
                        # 使用 self.wait (現在是 10 秒)
                        element = self.wait.until(
                            EC.presence_of_element_located((By.XPATH, xpath))
                        )
                        if element:
                            text_content = element.text.strip()
                            # 避免空字串覆蓋已找到的內容
                            if text_content:
                                print(f"Found {field}: {text_content} using XPath: {xpath}")
                                if field == 'creator_name':
                                    static_content[field] = text_content
                                else:
                                    static_content[field] = self.parse_number(text_content)
                                content_found = True
                                break # 找到有效的內容就不用試這個 field 的其他 xpath 了
                    except TimeoutException:
                        # print(f"Timeout waiting for {field} using XPath: {xpath}")
                        continue # 沒找到，嘗試下一個 XPath
                    except Exception as e:
                        print(f"Error getting {field} with XPath {xpath}: {str(e)}")
                        continue # 其他錯誤，嘗試下一個 XPath
                if not content_found:
                    print(f"警告: 未能找到 {field} 的有效內容。")
                    static_content[field] = static_content.get(field, None if field == 'creator_name' else 0) # 提供預設值

            return static_content

        except Exception as e:
            print(f"靜態內容爬取失敗: {str(e)}")
            # 返回帶有預設值的字典，確保鍵存在
            return {
                'creator_name': '',
                'patron_count': 0,
                'total_posts': 0,
                'monthly_income': 0
            }

    # count_post_year, count_tier_post, count_post_type 方法保持不變 (使用絕對 XPath)
    def count_post_year(self) -> dict:
        # (你的 count_post_year 程式碼保持不變)
        results = {}
        known_button_xpaths = [
            "/html/body/div[1]/main/div/div/div[1]/div/div/div/div[3]/div[2]/div[2]/div/div[1]/button[3]",
            "/html/body/div[1]/main/div/div[1]/div/div/div[3]/div[2]/div[2]/div/div[1]/button[3]",
            "/html/body/div[1]/main/div/div[1]/div/div/div[3]/div[4]/div[2]/div/div[1]/button[3]",
            "/html/body/div[1]/main/div[1]/div/div[3]/div[2]/div[2]/div/div[1]/button[3]",
        ]
        if not self.driver.current_url.startswith("https://www.patreon.com/"): return results
        dropdown_opened = False
        for button_xpath in known_button_xpaths:
            try:
                button = self.wait.until(EC.element_to_be_clickable((By.XPATH, button_xpath)))
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
                time.sleep(0.5)
                self.driver.execute_script("arguments[0].click();", button)
                time.sleep(1)
                dropdown_opened = True
                break
            except TimeoutException: continue
            except Exception as e: print(f"Error clicking year button: {str(e)}")
        if not dropdown_opened: print("無法打開年份下拉式選單"); return results
        try:
            dropdown_container_xpaths = ["/html/body/div[3]/div/div/div/div[2]","/html/body/div[3]/div/div/div[2]","/html/body/div[3]/div/div[2]"]
            dropdown_container = None
            for container_xpath in dropdown_container_xpaths:
                try: dropdown_container = self.wait.until(EC.presence_of_element_located((By.XPATH, container_xpath))); break
                except TimeoutException: continue
            if dropdown_container is None: print("無法找到年份下拉式選單容器"); return results
            menu_items = dropdown_container.find_elements(By.TAG_NAME, "a") # Patreon 通常用 a 標籤
            print(f"找到 {len(menu_items)} 個年份選單項目")
            for item in menu_items:
                try:
                    link_text = item.text.strip()
                    link_url = item.get_attribute("href")
                    count = self.extract_integer(link_text)
                    item_type = "unknown"
                    # ... (保持你原有的 item_type 提取邏輯) ...
                    if link_url:
                        url_parts = link_url.split("/")
                        if len(url_parts) > 0 and "posts" in url_parts:
                            posts_index = url_parts.index("posts")
                            if posts_index + 1 < len(url_parts):
                                potential_type = url_parts[posts_index + 1]
                                if potential_type.isdigit(): # 檢查是否為年份
                                    item_type = potential_type
                    if item_type == "unknown" and link_text:
                         item_type = ''.join([c for c in link_text if c.isdigit()]) # 簡化，只取數字作為年份
                    if item_type and count is not None and item_type != "unknown":
                        results[item_type] = count
                        print(f"找到年份項目: {item_type} = {count}")
                except Exception as e: print(f"處理年份選單項目時出錯: {str(e)}")
        except Exception as e: print(f"處理年份下拉式選單時出錯: {str(e)}")
        finally:
            try: self.driver.find_element(By.TAG_NAME, "body").click(); time.sleep(0.5)
            except: pass
        return results

    def count_tier_post(self) -> dict:
        # (你的 count_tier_post 程式碼保持不變, 但建議進行類似 count_post_year 的優化)
        results = {}
        known_button_xpaths = [
            "/html/body/div[1]/main/div/div/div[1]/div/div/div/div[3]/div[2]/div[2]/div/div[1]/button[2]",
            "/html/body/div[1]/main/div/div[1]/div/div/div[3]/div[2]/div[2]/div/div[1]/button[2]",
            "/html/body/div[1]/main/div/div[1]/div/div/div[3]/div[4]/div[2]/div/div[1]/button[2]",
            "/html/body/div[1]/main/div[1]/div/div[3]/div[2]/div[2]/div/div[1]/button[2]",
        ]
        if not self.driver.current_url.startswith("https://www.patreon.com/"): return results
        dropdown_opened = False
        for button_xpath in known_button_xpaths:
            try:
                button = self.wait.until(EC.element_to_be_clickable((By.XPATH, button_xpath)))
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
                time.sleep(0.5)
                self.driver.execute_script("arguments[0].click();", button)
                time.sleep(1)
                dropdown_opened = True
                break
            except TimeoutException: continue
            except Exception as e: print(f"Error clicking tier button: {str(e)}")
        if not dropdown_opened: print("無法打開 Tier 下拉式選單"); return results
        try:
            dropdown_container_xpaths = ["/html/body/div[3]/div/div/div/div[2]","/html/body/div[3]/div/div/div[2]","/html/body/div[3]/div/div[2]"]
            dropdown_container = None
            for container_xpath in dropdown_container_xpaths:
                try: dropdown_container = self.wait.until(EC.presence_of_element_located((By.XPATH, container_xpath))); break
                except TimeoutException: continue
            if dropdown_container is None: print("無法找到 Tier 下拉式選單容器"); return results
            menu_items = dropdown_container.find_elements(By.TAG_NAME, "a") # Patreon 通常用 a 標籤
            print(f"找到 {len(menu_items)} 個 Tier 選單項目")
            for item in menu_items:
                try:
                    link_text = item.text.strip()
                    link_url = item.get_attribute("href")
                    count = self.extract_integer(link_text)
                    item_type = "unknown"
                    # ... (保持你原有的 item_type 提取邏輯) ...
                    if link_url:
                        query_params = requests.utils.urlparse(link_url).query
                        params_dict = requests.utils.parse_qs(query_params)
                        if 'filters[tiers]' in params_dict:
                            item_type = params_dict['filters[tiers]'][0] # Tier ID 通常是數字
                        elif 'filters[access_level]' in params_dict:
                             item_type = params_dict['filters[access_level]'][0] # 例如 'public'
                    if item_type == "unknown" and link_text:
                        item_type = ''.join([c for c in link_text if not (c.isdigit() or c in "()[]{}.,;:!?")]).strip().lower().replace(" ", "_")

                    if item_type and count is not None and item_type != "unknown":
                        results[item_type] = count
                        print(f"找到 Tier 項目: {item_type} = {count}")
                except Exception as e: print(f"處理 Tier 選單項目時出錯: {str(e)}")
        except Exception as e: print(f"處理 Tier 下拉式選單時出錯: {str(e)}")
        finally:
            try: self.driver.find_element(By.TAG_NAME, "body").click(); time.sleep(0.5)
            except: pass

        print(f"DEBUG count_tier_post 返回: {results}")
        return results

    def count_post_type(self) -> dict:
        # (你的 count_post_type 程式碼保持不變, 但建議進行類似 count_post_year 的優化)
        results = {}
        if not self.driver.current_url.startswith("https://www.patreon.com/"): return results
        self.driver.execute_script("window.scrollTo(0, 0);"); time.sleep(1)
        known_button_xpaths = [
            "/html/body/div[1]/main/div/div/div[1]/div/div/div/div[3]/div[2]/div[2]/div/div[1]/button[1]",
            "/html/body/div[1]/main/div/div[1]/div/div/div[3]/div[2]/div[2]/div/div[1]/button[1]",
            "/html/body/div[1]/main/div[1]/div/div[3]/div[2]/div[2]/div/div[1]/button[1]",
            "/html/body/div[1]/main/div/div[1]/div/div/div[3]/div[4]/div[2]/div/div[1]/button[1]",
        ]
        dropdown_opened = False
        for button_xpath in known_button_xpaths:
            try:
                print(f"嘗試找到按鈕: {button_xpath}")
                button = self.wait.until(EC.element_to_be_clickable((By.XPATH, button_xpath)))
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", button); time.sleep(1)
                self.driver.execute_script("arguments[0].click();", button); time.sleep(1.5)
                dropdown_opened = True; print(f"成功點擊按鈕: {button_xpath}"); break
            except TimeoutException: print(f"找不到按鈕: {button_xpath}"); continue
            except Exception as e: print(f"點擊按鈕出錯: {button_xpath}, 錯誤: {str(e)}")
        # ... (保持你原有的備用方法和選單處理邏輯) ...
        if not dropdown_opened: print("無法打開類型下拉式選單"); return results # 簡化：如果主方法失敗則直接返回
        try:
            dropdown_container_xpaths = ["/html/body/div[3]/div/div/div[2]","/html/body/div[3]/div/div/div/div[2]","/html/body/div[3]/div/div[2]","/html/body/div[2]/div/div[2]","/html/body/div[4]/div/div[2]","//div[@role='menu']"]
            dropdown_container = None
            for container_xpath in dropdown_container_xpaths:
                try: print(f"嘗試找到類型選單容器: {container_xpath}"); dropdown_container = self.wait.until(EC.presence_of_element_located((By.XPATH, container_xpath))); print(f"找到類型選單容器: {container_xpath}"); break
                except TimeoutException: continue
            if dropdown_container is None: print("無法找到類型下拉式選單容器"); return results
            menu_items = []
            try: menu_items = dropdown_container.find_elements(By.TAG_NAME, "a") # 類型通常是連結
            except Exception as e: print(f"無法找到類型選單項目: {str(e)}")
            print(f"找到 {len(menu_items)} 個類型選單項目")
            for item in menu_items:
                try:
                    link_text = ""; link_url = ""
                    try: link_text = item.text.strip(); link_url = item.get_attribute("href")
                    except: continue
                    if not link_text: continue
                    count = self.extract_integer(link_text)
                    item_type = "unknown"
                    # ... (保持你原有的 item_type 提取邏輯) ...
                    if link_url:
                         url_parts = link_url.split("/")
                         if len(url_parts) > 0 and "posts" in url_parts:
                            posts_index = url_parts.index("posts")
                            if posts_index + 1 < len(url_parts):
                                 item_type = url_parts[posts_index + 1] # e.g., 'image', 'video'
                    if item_type == "unknown" and link_text: # 保持你基於文本的判斷
                        text_lower = link_text.lower()
                        if "image" in text_lower or "圖片" in text_lower: item_type = "image_posts"
                        elif "video" in text_lower or "影片" in text_lower: item_type = "video_posts"
                        elif "audio" in text_lower or "音頻" in text_lower or "podcast" in text_lower: item_type = "podcast_posts"
                        elif "text" in text_lower or "文章" in text_lower: item_type = "text_posts"
                        elif "link" in text_lower or "連結" in text_lower: item_type = "link_posts"
                        elif "poll" in text_lower or "投票" in text_lower: item_type = "poll_posts"
                        else: item_type = ''.join([c for c in link_text if not (c.isdigit() or c in "()[]{}.,;:!?")]).strip().lower().replace(" ", "_")

                    if item_type and count is not None and item_type != "unknown":
                        results[item_type] = count
                        print(f"找到類型項目: {item_type} = {count} (文本: {link_text})")
                except Exception as e: print(f"處理類型選單項目時出錯: {str(e)}")
        except Exception as e: print(f"處理類型下拉式選單時出錯: {str(e)}")
        finally:
             try: self.driver.find_element(By.TAG_NAME, "body").click(); time.sleep(0.5)
             except: pass # 簡化關閉邏輯

        print(f"DEBUG count_post_type 返回: {results}")
        return results

    def get_social_links(self) -> Dict[str, str]:
        # (你的 get_social_links 程式碼保持不變)
        social_platforms = {'facebook': 'no','twitter': 'no','instagram': 'no','youtube': 'no','twitch': 'no','tiktok': 'no','discord': 'no',}
        social_link_count = 0
        try:
            # 稍微改進，等待連結加載
            try:
                self.wait.until(EC.presence_of_element_located((By.TAG_NAME, "a")))
            except TimeoutException:
                print("頁面上未及時找到任何連結。")
                social_platforms['social_link_count'] = 0
                return social_platforms

            links = self.driver.find_elements(By.TAG_NAME, "a")
            print(f"找到 {len(links)} 個 <a> 標籤")
            processed_hrefs = set() # 避免重複計算同一平台

            for link in links:
                try:
                    href = link.get_attribute('href')
                    if href and href not in processed_hrefs:
                         # 檢查是否為常見的社群平台域名
                        href_lower = href.lower()
                        platform_found = None
                        if 'facebook.com' in href_lower: platform_found = 'facebook'
                        elif 'twitter.com' in href_lower or 'x.com' in href_lower: platform_found = 'twitter'
                        elif 'instagram.com' in href_lower: platform_found = 'instagram'
                        elif 'youtube.com' in href_lower and 'googleusercontent' not in href_lower : platform_found = 'youtube' # 排除圖片代理
                        elif 'twitch.tv' in href_lower: platform_found = 'twitch'
                        elif 'discord.gg' in href_lower or 'discord.com' in href_lower: platform_found = 'discord'
                        elif 'tiktok.com' in href_lower: platform_found = 'tiktok'

                        if platform_found and social_platforms[platform_found] == 'no':
                            social_platforms[platform_found] = 'yes'
                            social_link_count += 1
                            processed_hrefs.add(href) # 標記已處理
                            print(f"找到社群連結: {platform_found} - {href}")

                except Exception as e:
                    # print(f"處理連結時出錯: {str(e)}") # 減少不必要的輸出
                    continue

            # 圖標查找邏輯可以保留，但通常連結查找更可靠
            # social_icons = self.driver.find_elements(By.XPATH, "//a[@data-testid='external-link']") # 嘗試更精確的 XPATH
            # for icon_link in social_icons:
            #      href = icon_link.get_attribute('href')
                 # ... (類似的平台檢查邏輯) ...

        except Exception as e:
            print(f"獲取社群平台連結時出錯: {str(e)}")

        social_platforms['social_link_count'] = social_link_count
        return social_platforms


    # *** 替換成新的 scroll_page_to_load_more ***
    def scroll_page_to_load_more(self, max_scrolls=5, load_more_button_selector=None):
        """
        捲動頁面或點擊「載入更多」按鈕以加載內容。

        Args:
            max_scrolls (int): 最大嘗試加載的次數（滾動或點擊都算一次）。
            load_more_button_selector (tuple): 用於定位「載入更多」按鈕的 Selenium 定位器元組，
                                               例如 (By.XPATH, "//button[contains(text(), '載入更多')]")
                                               或 (By.CSS_SELECTOR, "button.load-more-button")。
                                               如果為 None，則只嘗試無限滾動。
        """
        print("開始嘗試加載更多內容...")
        scroll_attempts = 0
        # 使用類別的 wait (現在是 10 秒)
        wait = self.wait
        last_height = self.driver.execute_script("return document.body.scrollHeight")

        while scroll_attempts < max_scrolls:
            print(f"嘗試加載第 {scroll_attempts + 1}/{max_scrolls} 次...")

            load_more_clicked = False
            # --- 步驟 1: 嘗試尋找並點擊「載入更多」按鈕 (如果提供了選擇器) ---
            if load_more_button_selector:
                try:
                    # 等待按鈕出現並且可見 (使用提供的選擇器)
                    load_more_button = wait.until(
                        EC.visibility_of_element_located(load_more_button_selector)
                    )
                    print("找到「載入更多」按鈕。")

                    # 嘗試將按鈕滾動到視窗內並點擊
                    try:
                        # 滾動到按鈕附近，增加點擊成功率
                        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", load_more_button)
                        time.sleep(0.5) # 給一點點時間讓滾動完成

                        # 等待按鈕可被點擊 (再次確認)
                        clickable_button = wait.until(
                            EC.element_to_be_clickable(load_more_button_selector)
                        )
                        clickable_button.click()
                        print("已點擊「載入更多」按鈕。")
                        load_more_clicked = True
                        # **優化點**: 點擊後應等待特定內容加載，而不是固定 sleep
                        print("等待內容加載...")
                        # 範例：可以等待下一個按鈕再次出現，或等待高度變化
                        try:
                            # 簡單等待高度變化
                            wait.until(lambda driver: driver.execute_script("return document.body.scrollHeight") > last_height)
                            print("檢測到頁面高度增加。")
                        except TimeoutException:
                            print("點擊後頁面高度未在預期內增加。")
                        # time.sleep(2) # 保留備用，但不建議

                    except ElementClickInterceptedException:
                        print("「載入更多」按鈕被其他元素遮擋，嘗試使用 JavaScript 點擊...")
                        try:
                            self.driver.execute_script("arguments[0].click();", load_more_button)
                            print("已使用 JavaScript 點擊「載入更多」按鈕。")
                            load_more_clicked = True
                             # **優化點**: 同上，等待內容加載
                            print("等待內容加載...")
                            try:
                                wait.until(lambda driver: driver.execute_script("return document.body.scrollHeight") > last_height)
                                print("檢測到頁面高度增加。")
                            except TimeoutException:
                                print("點擊後頁面高度未在預期內增加。")
                            # time.sleep(2) # 保留備用
                        except Exception as js_e:
                            print(f"使用 JavaScript 點擊失敗: {js_e}")
                    except Exception as click_e:
                        print(f"點擊「載入更多」按鈕時出錯: {click_e}")

                except TimeoutException:
                    print("在指定時間內找不到可見的「載入更多」按鈕。") # 更清晰的訊息
                except Exception as find_e:
                    print(f"尋找「載入更多」按鈕時發生錯誤: {find_e}")

            # --- 步驟 2: 如果沒有成功點擊按鈕，或者沒有提供按鈕選擇器，則嘗試滾動頁面 ---
            if not load_more_clicked:
                print("未點擊按鈕，嘗試向下滾動頁面...")
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                # **優化點**: 滾動後也應等待內容加載完成
                # 可以短暫 sleep 或等待高度變化
                time.sleep(1.5) # 暫時保留

            # --- 步驟 3: 檢查頁面高度是否有變化 ---
            try:
                # 給予一點時間讓 JS 更新 scrollHeight
                time.sleep(0.5)
                new_height = self.driver.execute_script("return document.body.scrollHeight")
                if new_height == last_height:
                     print("頁面高度未改變，判斷已到達底部或無更多內容加載。")
                     break # 跳出 while 循環
                else:
                    print(f"頁面高度已從 {last_height} 增加到 {new_height}。")
                    last_height = new_height
            except Exception as height_e:
                 print(f"檢查頁面高度時出錯: {height_e}")
                 break # 發生錯誤時停止

            scroll_attempts += 1
            # 可以在此處加一個小的固定延遲，避免過於頻繁的請求/操作
            # time.sleep(random.uniform(0.5, 1.5))

        print(f"加載更多內容結束，共完成 {scroll_attempts} 次嘗試。")


    def get_social_value(self) -> dict: # 返回字典更清晰
        """爬取頁面上所有按讚數和留言數並加總"""
        total_likes = 0
        total_comments = 0

        try:
            # *** 修改調用方式，傳入你的絕對 XPath ***
            load_more_xpath = "/html/body/div[1]/main/div/div/div[1]/div/div/div/div[3]/div[2]/div[2]/div/div[4]/button"
            load_more_selector = (By.XPATH, load_more_xpath)
            # 調用新的滾動函數，設定嘗試次數，例如 10 次
            self.scroll_page_to_load_more(max_scrolls=10, load_more_button_selector=load_more_selector)

            # 捲動完成後，再查找所有元素
            print("開始查找按讚和留言元素...")
            # 使用相對 XPath 可能更穩定，但暫時保留你的方式或嘗試改進
            # 例子：尋找包含 'like' 文本的按鈕或 span
            # like_elements = self.driver.find_elements(By.XPATH, "//*[contains(@data-tag, 'like-count')] | //button[contains(., 'like')] | //span[contains(., 'like')]")
            like_elements = self.driver.find_elements(By.XPATH, "//*[@data-tag='like-count']") # 保留你的選擇器

            # 你的留言選擇器非常具體且可能不穩定，嘗試更通用的方法
            # 例子：尋找包含 'comment' 文本的按鈕或連結
            # comment_elements = self.driver.find_elements(By.XPATH, "//a[contains(@href, '#comment')] | //button[contains(., 'comment')] | //span[contains(., 'comment')]")
            comment_elements = self.driver.find_elements(By.XPATH, "//*[@class='sc-furwcr gvdFXB']") # 保留你的選擇器

            print(f"找到 {len(like_elements)} 個按讚計數相關元素")
            print(f"找到 {len(comment_elements)} 個留言計數相關元素")

            # 遍歷每個按讚元素並提取數值
            for element in like_elements:
                try:
                    like_text = element.text.strip()
                    like_count = self.extract_integer(like_text) # 使用你的輔助函數
                    if like_count is not None:
                        total_likes += like_count
                        # print(f"找到按讚數: {like_count}") # 減少輸出
                except Exception as e:
                    # print(f"解析按讚數時出錯: {str(e)}") # 減少輸出
                    pass # 解析單個元素失敗不影響總數

            # 遍歷每個留言元素並提取數值
            for element in comment_elements:
                try:
                    comment_text = element.text.strip()
                    comment_count = self.extract_integer(comment_text) # 使用你的輔助函數
                    if comment_count is not None:
                        total_comments += comment_count
                        # print(f"找到留言數: {comment_count}") # 減少輸出
                except Exception as e:
                    # print(f"解析留言數時出錯: {str(e)}") # 減少輸出
                    pass # 解析單個元素失敗不影響總數

            print(f"總按讚數: {total_likes}, 總留言數: {total_comments}")
            return {
                'total_likes': total_likes,
                'total_comments': total_comments
            }

        except Exception as e:
            print(f"獲取社交數值時發生整體錯誤: {str(e)}")
            return {
                'total_likes': 0,
                'total_comments': 0
            }


    # --- scrape_url 方法保持不變 ---
    def scrape_url(self, url: str) -> Dict[str, Any]:
        """爬取單個 URL 的所有內容"""
        try:
            self.driver.get(url)
            print(f"已開始訪問頁面: {url}")
            # 使用 WebDriverWait 等待頁面某個關鍵元素加載完成，比固定 sleep 好
            try:
                self.wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                 # 可以等待更具體的元素，例如創作者名字 h1
                self.wait.until(EC.presence_of_element_located((By.XPATH, "//h1")))
            except TimeoutException:
                print("頁面基礎元素加載超時。")
                # 可能需要返回錯誤或重試
            # time.sleep(1) # 替換為上面的 WebDriverWait

            self.handle_age_verification()
            # print("已處理年齡驗證") # handle_age_verification 內部已有打印

            self.driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(0.5) # 短暫等待滾動完成

            static_content = self.get_static_content(url)
            print("獲取靜態內容:", static_content)

            social_links = self.get_social_links()
            print("獲取社群平台連結:", social_links)

            post_type_count = self.count_post_type()
            print("獲取post_type_count:", post_type_count)

            post_year_count = self.count_post_year()
            print("獲取post_year_count:", post_year_count)

            public_post = self.count_tier_post()
            print("獲取public_post:", public_post)

            # *** get_social_value 現在返回字典 ***
            social_values = self.get_social_value()
            total_likes = social_values.get('total_likes', 0) # 使用 .get 更安全
            total_comments = social_values.get('total_comments', 0) # 使用 .get 更安全
            print(f"文章按讚總數: {total_likes}")
            print(f"文章留言總數: {total_comments}")

            # 獲取頁面上的總連結數可能意義不大，且耗時
            # links = self.driver.find_elements(By.TAG_NAME, "a")
            # total_links = len(links)
            total_links = -1 # 標記為未計算或不需要
            print(f"頁面總連結數 (未計算): {total_links}")


            # 組合結果
            result = {
                'URL': url,
                'creator_name': static_content.get('creator_name', ''),
                # 注意 public_post 和 post_year_count 會被下面的 prepare 函數處理
                'public_post': public_post,
                'post_year_count': post_year_count,
                'total_post': static_content.get('total_posts', 0),
                'patreon_number': static_content.get('patron_count', 0),
                'income_per_month': static_content.get('monthly_income', 0),
                'post_type_count': post_type_count, # 這個後面會被展開
                'social_links': social_links, # 這個後面會被展開
                'total_likes': total_likes,
                'total_comments': total_comments,
                'total_links': total_links,
            }

            print(f"已爬取原始數據 {url}:")
            # print(result) # 打印原始數據可能太長

            return result

        except Exception as e:
            print(f"爬取失敗 {url}: {str(e)}")
            # 返回一個含有空值的默認結果 (與 scrape_multiple_targets 保持一致)
            return {
                'URL': url, 'creator_name': '','public_post': {},'total_post': 0,'patreon_number': 0,
                'income_per_month': 0,'post_year_count': {}, 'post_type_count': {},
                'social_links': {'facebook': 'no', 'twitter': 'no', 'instagram': 'no', 'youtube': 'no', 'twitch': 'no', 'discord': 'no', 'tiktok': 'no', 'social_link_count': 0},
                'total_likes': 0,'total_comments': 0,'total_links': -1,
            }

    # --- scrape_multiple_targets 和 _prepare_row_data 方法保持不變 ---
    def scrape_multiple_targets(self, targets: list):
        """爬取多個目標URL並保存到CSV"""
        # (你的 scrape_multiple_targets 程式碼保持不變)
        first_data = {}
        if targets:
            try: first_data = self.scrape_url(targets[0])
            except Exception as e: print(f"爬取首個URL時出錯: {str(e)}")

        # *** 建議：明確定義所有可能的欄位 ***
        fieldnames = [
            'URL', 'creator_name', 'total_post', 'patreon_number', 'income_per_month',
            'tier_post_data', # 這是 tier 字典的字串形式
            'post_year_count', # 這是 year 字典的字串形式
            'tier_count', # Tier 數量
            'total_likes', 'total_comments', 'total_links',
            # 社群平台
            'facebook', 'twitter', 'instagram', 'youtube', 'twitch', 'tiktok', 'discord', 'social_link_count',
            # 文章類型 (列出所有預期類型)
            'image_posts', 'video_posts', 'podcast_posts', 'text_posts', 'link_posts', 'poll_posts','audio_posts',
            # 可以再加一些常見但可能不在第一頁的類型
            'livestream_posts', 'other_posts'
        ]
        # 去重，以防萬一
        fieldnames = sorted(list(set(fieldnames)), key=lambda x: fieldnames.index(x)) # 保持原始順序的去重

        print(f"CSV 欄位將是: {fieldnames}")

        # 確保輸出目錄存在
        os.makedirs(os.path.dirname(self.output_path), exist_ok=True)

        with open(self.output_path, 'w', newline='', encoding='utf-8-sig') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames, extrasaction='ignore') # extrasaction='ignore' 忽略不在 fieldnames 中的鍵
            writer.writeheader()

            processed_urls = 0
            # 如果已經爬取了第一個URL，直接寫入
            if first_data and targets:
                url = targets[0]
                row_data = self._prepare_row_data(url, first_data, fieldnames)
                writer.writerow(row_data)
                processed_urls += 1
                print(f"已成功爬取並記錄 ({processed_urls}/{len(targets)}): {url}")

            # 爬取剩餘的URL
            start_index = 1 if first_data and targets else 0
            for i, url in enumerate(targets[start_index:], start=start_index):
                try:
                    data = self.scrape_url(url)
                    row_data = self._prepare_row_data(url, data, fieldnames)
                    writer.writerow(row_data)
                    processed_urls += 1
                    print(f"已成功爬取並記錄 ({processed_urls}/{len(targets)}): {url}")

                except Exception as e:
                    print(f"處理 URL {url} 時發生嚴重錯誤，記錄空行: {str(e)}")
                    # 記錄空行但包含 URL，方便追蹤
                    error_row = {field: '' for field in fieldnames}
                    error_row['URL'] = url
                    writer.writerow(error_row)
                    continue # 繼續處理下一個 URL

                # 每次爬取後增加延遲，避免 IP 被封鎖
                delay = random.uniform(3, 5) # 3到7秒的隨機延遲
                print(f"等待 {delay:.1f} 秒...")
                time.sleep(delay)
                # time.sleep(2) # 原來的固定延遲

    def _prepare_row_data(self, url, data, fieldnames):
        """準備CSV行數據"""
        # (你的 _prepare_row_data 程式碼基本保持不變)
        public_post = data.get('public_post', {}) # 這是 tier data

        row_data = {
            'URL': url,
            'creator_name': data.get('creator_name', ''),
            'total_post': data.get('total_post', 0),
            'patreon_number': data.get('patreon_number', 0),
            'income_per_month': data.get('income_per_month', 0),
            # 使用 _prepare... 方法將字典轉為字符串
            'tier_post_data': self._prepare_tier_post_data(data), # 這裡使用的是 data['public_post']
            'post_year_count': self._prepare_post_year_data(data), # 這裡使用的是 data['post_year_count']
            'tier_count': len(public_post) if public_post else 0,
            'total_likes': data.get('total_likes', 0),
            'total_comments': data.get('total_comments', 0),
            'total_links': data.get('total_links', 0), # 使用更新後的值
        }

        # 添加社群媒體資訊
        social_links = data.get('social_links', {})
        for platform in ['facebook', 'twitter', 'instagram', 'youtube', 'twitch', 'tiktok', 'discord', 'social_link_count']:
             # 使用 .get 提供預設值
             default_social = 0 if platform == 'social_link_count' else 'no'
             row_data[platform] = social_links.get(platform, default_social)


        # 從post_type_count獲取文章類型數據並展開
        post_type_count = data.get('post_type_count', {})
        # 將 post_type_count 中的鍵值對添加到 row_data
        for type_key, type_value in post_type_count.items():
            if type_key in fieldnames: # 只添加在預期欄位中的類型
                 row_data[type_key] = type_value
            else:
                 print(f"警告: 發現未預期/未定義的文章類型 '{type_key}'，將被忽略。")

        # 確保所有 fieldnames 都有值，沒有對應數據的填 0 (除了已填的 'no' 或其他字串)
        for field in fieldnames:
            if field not in row_data:
                # 判斷是否為社群平台 'yes'/'no' 欄位
                is_social_yes_no = field in ['facebook', 'twitter', 'instagram', 'youtube', 'twitch', 'tiktok', 'discord']
                # 判斷是否為字典字串欄位
                is_dict_string = field in ['tier_post_data', 'post_year_count']

                if is_social_yes_no:
                     row_data[field] = 'no'
                elif is_dict_string:
                     row_data[field] = '{}'
                elif field == 'creator_name':
                     row_data[field] = ''
                elif field == 'URL':
                    pass # URL 總是在 row_data 中
                else:
                     row_data[field] = 0 # 其他數字欄位默認為 0


        return row_data


    def close(self):
        """關閉瀏覽器"""
        try:
            print("正在關閉 WebDriver...")
            self.driver.quit()
            print("WebDriver 已關閉。")
        except Exception as e:
            print(f"關閉 WebDriver 時出錯: {e}")
            pass # 即使出錯也繼續

# --- load_urls_from_txt 函數保持不變 ---
# (你的 load_urls_from_txt 函數定義)
def load_urls_from_txt(filepath="urls_for_scrape.txt"): # 使用相對路徑
    urls = []
    # 修正：確保使用傳入的 filepath 參數
    # print(f"嘗試從以下路徑加載 URLs: {os.path.abspath(filepath)}") # 調試信息
    # 修正你的硬編碼路徑問題
    # 正確做法是讓調用者傳入完整路徑，或者基於腳本位置計算
    # 暫時保留你的寫法，但強烈建議修改
    # filepath = "D:/成功大學/論文資料/urls_for_scrape.txt" # 這是你原來函數的隱藏問題
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    urls.append(line)
        print(f"從 {filepath} 成功載入 {len(urls)} 個 URL。")
    except FileNotFoundError:
        print(f"錯誤：找不到 URL 檔案 {filepath}。請確認檔案路徑和名稱是否正確。")
    except Exception as e:
        print(f"讀取 URL 檔案 {filepath} 時發生錯誤: {e}")
    return urls


# --- if __name__ == "__main__": 主執行區塊保持不變 ---
# (你的主執行區塊)
if __name__ == "__main__":
    # *** 重要：修改這裡的路徑為你實際的檔案路徑 ***
    # 使用相對路徑，假設 urls_for_scrape.txt 和你的 .py 文件在同一目錄
    # url_file_path = "urls_for_scrape.txt"
    # 或者保持你的絕對路徑，如果必須的話
    url_file_path = "D:\成功大學\論文資料/for_gemini/urls_for_scrape.txt" # 使用變數更清晰

    target_urls = load_urls_from_txt(url_file_path)

    if not target_urls:
        print("未能從檔案載入任何 URL，程式即將結束。")
    else:
        # 可以指定輸出路徑，或者讓類別使用默認路徑
        # output_csv_path = "D:/成功大學/論文資料/爬蟲資料/my_custom_output.csv"
        # scraper = HybridPatreonScraper(output_path=output_csv_path)
        scraper = HybridPatreonScraper() # 使用默認輸出路徑

        try:
            print(f"準備開始爬取 {len(target_urls)} 個目標...")
            scraper.scrape_multiple_targets(target_urls)
            print("所有目標爬取完成。")
        except Exception as e:
            print(f"爬取過程中發生未預期的錯誤: {e}")
            import traceback
            traceback.print_exc() # 打印詳細的錯誤追蹤信息
        finally:
            print("正在關閉爬蟲資源...")
            scraper.close()
            print("爬蟲資源已關閉。")