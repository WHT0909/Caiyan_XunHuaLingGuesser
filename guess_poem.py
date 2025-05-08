import json
import re
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from collections import defaultdict

class PoemGuesser:
    def __init__(self):
        # 初始化浏览器（增加窗口最大化）
        self.success = False  # 新增成功状态标志
        self.driver = webdriver.Chrome()
        self.driver.maximize_window()  # 避免响应式布局问题
        self.driver.get('https://xiaoce.fun/xunhualing')

        # 使用XPath定位输入框
        input_box = WebDriverWait(self.driver, 20).until(
            EC.presence_of_element_located((By.XPATH, '//input[@placeholder="一句（7x2）诗/词等，标点随意"] | //input[@placeholder="一句（5x2）诗/词等，标点随意"]'))
        )
        placeholder = input_box.get_attribute('placeholder')

        if "（7x2）" in placeholder:
            self.length = 14
            self.poem_type = 7
        elif "（5x2）" in placeholder:
            self.length = 10
            self.poem_type = 5
        else:
            raise ValueError("无法从placeholder判断诗类型，请检查网页输入框。")

        # 初始化古诗库（增强数据清洗）
        try:
            with open('0.唐诗三百首.json', 'r', encoding='utf-8') as f:
                poems_data = json.load(f)
                self.all_poems = []
                for poem in poems_data:
                    for p in poem.get('paragraphs', []):
                        # 深度清洗数据
                        cleaned = re.sub(r'[^\u4e00-\u9fa5]', '', p.strip())
                        if len(cleaned) == self.length:
                            self.all_poems.append(cleaned)
            print(f"符合条件的诗句数量: {len(self.all_poems)}")
            if len(self.all_poems) == 0:
                print("未找到符合条件的诗句，请检查数据文件。")
        except FileNotFoundError:
            print("未找到 0.唐诗三百首.json 文件，请检查文件路径。")
        except json.JSONDecodeError:
            print("0.唐诗三百首.json 文件格式错误，请检查文件内容。")

        # 元素定位器（优化稳定性）
        self.input_box = (By.CSS_SELECTOR, f'input[placeholder="{placeholder}"]')
        self.submit_btn = (By.CSS_SELECTOR, 'button.ant-btn-primary:not([disabled])')
        self.direct_submit_btn = (By.XPATH, '//button[contains(text(), "直接提交")]')
        self.tiles = (By.CSS_SELECTOR, 'div[style*="width: 40px"][style*="font-family: fangsong"]:not([style*="rgb(170, 170, 170)"])')

        # 初始化算法参数
        self._reset_game_state()
        self.guess_history = []
        self.refresh_counter = 0
        self.green_constraints = {}  # 绿色字及其位置约束
        self.yellow_chars = set()  # 黄色字集合
        self.gray_chars = set()  # 灰色字集合

    def _reset_game_state(self):
        """重置游戏状态"""
        self.candidates = self.all_poems.copy()
        self.word_stats = self._build_word_frequency()
        self.last_guess = None

    def _build_word_frequency(self):
        """构建加权位置频率统计"""
        stats = [defaultdict(int) for _ in range(self.length)]
        for poem in self.candidates:
            for i, char in enumerate(poem):
                # 前位字符权重更高
                stats[i][char] += (self.length - i) * 2
        return stats

    def _get_best_candidate(self):
        """动态优化候选选择，避免重复猜测"""
        if not self.candidates:
            print("候选集为空，无法继续猜测。")
            return None

        guessed_set = {entry['guess'] for entry in self.guess_history}
        sorted_candidates = sorted(
            self.candidates,
            key=lambda p: sum(self.word_stats[i][c] for i, c in enumerate(p)),
            reverse=True
        )
        for candidate in sorted_candidates:
            if candidate not in guessed_set:
                # 检查候选诗是否满足绿色、黄色、灰色字的约束
                valid = True
                for pos, char in self.green_constraints.items():
                    if candidate[pos] != char:
                        valid = False
                        break
                if not valid:
                    continue
                for char in self.yellow_chars:
                    if char not in candidate:
                        valid = False
                        break
                if not valid:
                    continue
                for char in self.gray_chars:
                    if char in candidate:
                        valid = False
                        break
                if valid:
                    return candidate
        return None

    def _process_feedback(self, guess):
        """增强反馈处理逻辑，加入重试机制"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # 等待 tile 元素出现（增加容错时间）
                WebDriverWait(self.driver, 15).until(
                    EC.presence_of_all_elements_located(self.tiles)
                )

                # 获取所有 tiles 并筛选有效结果
                all_tiles = self.driver.find_elements(*self.tiles)
                if not all_tiles:
                    print(f"第{attempt + 1}次重试获取tiles...")
                    continue

                # 确保获取到最新一轮的tiles（根据数量判断）
                expected_count = len(self.guess_history) * self.length + self.length
                if len(all_tiles) >= expected_count:
                    current_tiles = all_tiles[-self.length:]
                    return [
                        {
                            'color': tile.value_of_css_property('background-color'),
                            'char': guess[i]
                        } for i, tile in enumerate(current_tiles)
                    ]
            except Exception as e:
                print(f"反馈处理异常（{attempt + 1}/{max_retries}）: {str(e)[:100]}...")
                if attempt == max_retries - 1:
                    return []

    def _parse_feedback(self, feedback):
        """精准颜色解析 + 输出原始 RGB（支持 rgba 格式）"""
        def rgba_to_rgb_name(rgba_str):
            match = re.match(r'rgba?\((\d+),\s*(\d+),\s*(\d+)', rgba_str)
            if not match:
                return 'unknown'
            r, g, b = map(int, match.groups())
            if (r, g, b) == (106, 170, 100):
                return 'green'
            elif (r, g, b) == (201, 180, 88):
                return 'yellow'
            elif (r, g, b) == (120, 124, 126):
                return 'gray'
            else:
                return 'unknown'

        result = []
        print("【调试】原始反馈 RGB：")
        for item in feedback:
            rgba = item['color']
            char = item['char']
            status = rgba_to_rgb_name(rgba)
            print(f"  字：{char}，RGBA：{rgba}，解析颜色：{status}")
            result.append({'status': status, 'char': char})
        return result

    def _refresh_session(self):
        """安全刷新页面"""
        print(f"第{self.refresh_counter // 9}次刷新页面...")
        self.driver.refresh()
        WebDriverWait(self.driver, 20).until(
            EC.presence_of_element_located(self.input_box)
        )
        self._reset_game_state()
        self.green_constraints = {}
        self.yellow_chars = set()
        self.gray_chars = set()

    def _update_candidates(self, guess, status):
        """优化后的候选集更新逻辑（确保绿色必须匹配位置，黄色必须存在，灰色条件下严格排除）"""
        for i, (char, stat) in enumerate(zip(guess, status)):
            if stat == 'green':
                self.green_constraints[i] = char
            elif stat == 'yellow':
                self.yellow_chars.add(char)
            elif stat == 'gray':
                self.gray_chars.add(char)

        new_candidates = []
        for candidate in self.candidates:
            valid = True
            for pos, char in self.green_constraints.items():
                if candidate[pos] != char:
                    valid = False
                    break
            if not valid:
                continue
            for char in self.yellow_chars:
                if char not in candidate:
                    valid = False
                    break
            if not valid:
                continue
            for char in self.gray_chars:
                if char in candidate:
                    valid = False
                    break
            if valid:
                new_candidates.append(candidate)

        self.candidates = new_candidates
        self.word_stats = self._build_word_frequency()

        # 候选为空则重置
        if not self.candidates:
            print("候选集为空，重置游戏状态")
            self._reset_game_state()
            self.green_constraints = {}
            self.yellow_chars = set()
            self.gray_chars = set()

    def run(self):
        try:
            while True:
                current_guess = self._get_best_candidate()
                if current_guess is None:
                    break
                print(f"\n当前猜测：{current_guess}")

                # 输入操作
                input_box = WebDriverWait(self.driver, 20).until(
                    EC.element_to_be_clickable(self.input_box)
                )
                input_box.clear()
                for char in current_guess:  # 改为逐个字符输入，避免粘滞键问题
                    input_box.send_keys(char)
                    # time.sleep(0.1)

                # 提交操作（优化异常处理）
                try:
                    submit_btn = WebDriverWait(self.driver, 15).until(
                        EC.element_to_be_clickable(self.submit_btn)
                    )
                    self.driver.execute_script("arguments[0].scrollIntoView();", submit_btn)
                    self.driver.execute_script("arguments[0].click();", submit_btn)
                    print("正常提交成功")
                except Exception as e:
                    print(f"常规提交失败: {e}")
                    # 尝试强制提交
                    try:
                        print("尝试强制提交...")
                        self.driver.execute_script(f"document.querySelector('input[placeholder]').value = '{current_guess}';")
                        self.driver.execute_script("document.querySelector('button.ant-btn-primary').click();")
                    except Exception as e:
                        print(f"强制提交失败: {e}")
                        continue

                # 处理反馈（增加等待动画的识别）
                raw_feedback = []
                try:
                    # 等待加载动画消失
                    WebDriverWait(self.driver, 15).until_not(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "span.ant-spin-dot"))
                    )
                    raw_feedback = self._process_feedback(current_guess)
                except Exception as e:
                    print(f"等待反馈超时: {e}")

                # 处理直接提交情况（优化按钮定位）
                if not raw_feedback:
                    print("检测到可能需要直接提交...")
                    try:
                        # 使用更精确的定位器
                        direct_btn = WebDriverWait(self.driver, 10).until(
                            EC.element_to_be_clickable((By.XPATH, '//button[.//span[contains(text(),"直接提交")]]'))
                        )
                        self.driver.execute_script("arguments[0].scrollIntoView();", direct_btn)
                        self.driver.execute_script("arguments[0].click();", direct_btn)
                        print("直接提交成功，等待结果刷新...")

                        # 提交后等待页面更新
                        WebDriverWait(self.driver, 15).until(
                            EC.invisibility_of_element_located((By.XPATH, '//button[.//span[contains(text(),"直接提交")]]'))
                        )
                        # 重新获取反馈
                        raw_feedback = self._process_feedback(current_guess)
                    except Exception as e:
                        print(f"直接提交失败: {e}")
                        continue

                status_info = self._parse_feedback(raw_feedback)
                status = [s['status'] for s in status_info]

                # ✅ 打印每个字及其颜色
                print("反馈信息：")
                for item in status_info:
                    print(f"  字：{item['char']}，颜色：{item['status']}")

                # ✅ 汇总颜色类别
                green_chars = [item['char'] for item in status_info if item['status'] == 'green']
                yellow_chars = [item['char'] for item in status_info if item['status'] == 'yellow']
                gray_chars = [item['char'] for item in status_info if item['status'] == 'gray']

                print(f"绿色字：{'、'.join(green_chars) if green_chars else '无'}")
                print(f"黄色字：{'、'.join(yellow_chars) if yellow_chars else '无'}")
                print(f"灰色字：{'、'.join(gray_chars) if gray_chars else '无'}")

                # 记录历史
                self.guess_history.append({
                    'guess': current_guess,
                    'status': status_info,
                    'attempt': self.refresh_counter % 9 + 1
                })
                self.refresh_counter += 1

                if all(s == 'green' for s in status):
                    print(f"成功！正确答案：{current_guess}")
                    while True:
                        cmd = input("\n请输入 'q' 退出程序: ")
                        if cmd.strip().lower() == 'q':
                            self.success = True
                            break
                    break

                # 每 9 次刷新
                if self.refresh_counter % 9 == 0:
                    self._refresh_session()

                # 更新候选
                self._update_candidates(current_guess, status)

        except Exception as e:
            print(f"程序出现异常: {e}")
        finally:
            with open('guess_history.json', 'w', encoding='utf-8') as f:
                json.dump(self.guess_history, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    guesser = PoemGuesser()
    if len(guesser.all_poems) > 0:
        guesser.run()
    