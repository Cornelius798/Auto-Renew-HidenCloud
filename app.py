#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, re, sys, time, random, requests
from playwright.sync_api import sync_playwright

# --- 环境变量 ---
COOKIE_VALUE = os.environ.get('COOKIE_VALUE') or ""     # remember_web cookie 值，必填
EMAIL        = os.environ.get('EMAIL') or ""            # 登录邮箱,可选，作为备用,TG通知需要填写
PASSWORD     = os.environ.get('PASSWORD') or ""         # 登录密码,可选，作为备用
TG_BOT_TOKEN = os.environ.get('TG_BOT_TOKEN') or ""     # Telegram Bot Token,可选
TG_CHAT_ID   = os.environ.get('TG_CHAT_ID') or ""       # Telegram Chat ID,可选

BASE_URL = "https://dash.hidencloud.com"
LOGIN_URL = f"{BASE_URL}/auth/login"

# --- 代理配置（由工作流 shell 脚本写入 $GITHUB_ENV）---
IS_PROXY      = os.environ.get('IS_PROXY', 'false').lower() == 'true'
PROXY_SERVER  = os.environ.get('PROXY_SERVER') or "socks5://127.0.0.1:1080"
REQUESTS_PROXIES = {"http": PROXY_SERVER, "https": PROXY_SERVER} if IS_PROXY else None

def log(message):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}", flush=True)

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.chrome = { runtime: {} };
"""

def get_current_ip(proxy_server=None):
    """获取当前出口IP"""
    proxies = {"http": proxy_server, "https": proxy_server} if (proxy_server and IS_PROXY) else None
    try:
        resp = requests.get("https://api.ip.sb/ip", proxies=proxies, timeout=15)
        if resp.status_code == 200:
            return resp.text.strip()
        return "获取失败"
    except Exception as e:
        log(f"❌ 获取出口IP失败: {e}")
        return "获取失败"

def send_telegram_notification(status, old_due, new_due):
    """发送 Telegram 通知"""
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        log("⚠️ Telegram 未配置，跳过通知")
        return False
    
    local_time = time.gmtime(time.time() + 8 * 3600)
    now = time.strftime("%Y-%m-%d %H:%M:%S", local_time)
    if '@' in EMAIL:
        name, domain = EMAIL.split('@', 1)
        if len(name) > 4:
            masked_email = f"{name[:2]}****{name[-2:]}@{domain}"
        else:
            masked_email = f"{name}@{domain}"
    else:
        masked_email = (EMAIL[:2] + '****') if EMAIL else "未知账号"

    text = (
        f"🎉 HidenCloud 续期通知\n\n"
        f"{status}\n"
        f"👤 账号: {masked_email}\n"
        f"📅 续期前到期：{old_due}\n"
        f"📅 续期后到期：{new_due}\n"
        f"🕒 续期时间：{now}"
    )
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TG_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        resp = requests.post(url, json=payload, timeout=10, proxies=REQUESTS_PROXIES)
        if resp.status_code == 200:
            log("✅ Telegram 通知发送成功")
            return True
        else:
            log(f"❌ Telegram 通知失败: {resp.text}")
            return False
    except Exception as e:
        log(f"❌ Telegram 通知异常: {e}")
        return False

def handle_cloudflare(page):
    iframe_selector = 'iframe[src*="challenges.cloudflare.com"]'
    if page.locator(iframe_selector).count() == 0:
        return True
    log("⚠️ 检测到 Cloudflare 验证...")
    start_time = time.time()
    while time.time() - start_time < 60:
        if page.locator(iframe_selector).count() == 0:
            log("✅ Cloudflare 验证通过！")
            return True
        try:
            frame = page.frame_locator(iframe_selector)
            checkbox = frame.locator('input[type="checkbox"]')
            if checkbox.is_visible():
                log("🖱️ 点击验证复选框...")
                time.sleep(random.uniform(0.5, 1.5))
                checkbox.click()
                log("⏳ 已点击，等待验证结果...")
                time.sleep(5)
            else:
                time.sleep(1)
        except Exception:
            pass
    log("❌ 验证超时。")
    return False

def login(page):
    if COOKIE_VALUE:
        log("📇 尝试 Cookie 登录...")
        try:
            page.context.add_cookies([{
                'name': 'remember_web_59ba36addc2b2f9401580f014c7f58ea4e30989d',
                'value': COOKIE_VALUE,
                'domain': 'dash.hidencloud.com',
                'path': '/',
                'expires': int(time.time()) + 3600 * 24 * 365,
                'httpOnly': True,
                'secure': True,
                'sameSite': 'Lax'
            }])
            page.goto(f"{BASE_URL}/dashboard", wait_until="domcontentloaded", timeout=60000)
            handle_cloudflare(page)
            page_title = page.title()
            log(f"📝 当前Title: {page_title}")
            if "auth/login" not in page.url:
                log("✅ Cookie 登录成功！当前已到达dashboard页面")
                return True
            log("❌ Cookie 失效，请更换")
        except Exception:
            pass

    if not EMAIL or not PASSWORD:
        return False
    log("💣 尝试账号密码登录...")
    try:
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
        handle_cloudflare(page)
        page.fill('input[name="email"]', EMAIL)
        page.fill('input[name="password"]', PASSWORD)
        time.sleep(0.5)
        handle_cloudflare(page)
        page.click('button[type="submit"]')
        time.sleep(3)
        handle_cloudflare(page)
        page.wait_for_url(f"{BASE_URL}/*", timeout=30000)
        page.goto(f"{BASE_URL}/dashboard", wait_until="domcontentloaded", timeout=60000)
        handle_cloudflare(page)
        page_title = page.title()
        log(f"📝 当前Title: {page_title}")
        if "auth/login" in page.url:
            log("❌ 登录失败。")
            page.screenshot(path="login_fail.png")
            return False
        log("✅ 账号密码登录成功！当前已到达dashboard页面")
        return True
    except Exception as e:
        log(f"❌ 登录异常: {e}")
        page.screenshot(path="login_fail.png")
        return False

def get_server_id(page):
    try:
        handle_cloudflare(page)
        time.sleep(3)
        html = page.content()
        log(f"📝 页面长度: {len(html)}, URL: {page.url}")

        matches = re.findall(r'/service/(\d+)/manage', html)
        if matches:
            server_id = matches[0]
            log(f"✅ 从链接中获取到 Server ID: {server_id}")
            return server_id

        matches = re.findall(r'#(\d{4,})', html)
        if matches:
            server_id = matches[0]
            log(f"✅ 从文本 #号中获取到 Server ID: {server_id}")
            return server_id

        log("❌ 所有 URL 均未找到 Server ID")
        page.screenshot(path="server_id_error.png")
        return None
    except Exception as e:
        log(f"❌ 获取 Server ID 失败: {e}")
        page.screenshot(path="server_id_error.png")
        return None

def get_due_date(page):
    try:
        if SERVICE_URL not in page.url:
            page.goto(SERVICE_URL, wait_until="domcontentloaded", timeout=60000)
        handle_cloudflare(page)
        body_text = page.locator("body").inner_text()
        patterns = [
            r"Due date\s+(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})",
            r"Due date\s*\n\s*(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})",
            r"Due date.*?(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})",
        ]
        for pattern in patterns:
            match = re.search(pattern, body_text, re.IGNORECASE | re.DOTALL)
            if match:
                due_date = match.group(1).strip()
                log(f"📅 获取到Due Date: {due_date}")
                return due_date
    except Exception as e:
        log(f"❌ 获取Due Date失败: {e}")
    return "未知"

def try_pay_existing_invoices(page):
    """当 Renew 无法弹出时，直接去左侧 Invoices 页面支付已生成的账单"""
    log("💡 检测到可能已生成续期账单，尝试进入 Invoices 页面核销...")
    try:
        invoices_link = page.locator('a[href*="/invoices"], a:has-text("Invoices")').first
        if invoices_link.is_visible():
            invoices_link.click()
        else:
            page.goto(f"{BASE_URL}/invoices", wait_until="domcontentloaded", timeout=30000)
        
        handle_cloudflare(page)
        page.wait_for_timeout(3000)
        page.screenshot(path="invoices_list_page.png")

        # 查找未支付账单 (Unpaid / Pending)
        unpaid_items = page.locator('a:has-text("Unpaid"), a:has-text("Pay"), a:has-text("View"):visible')
        count = unpaid_items.count()
        log(f"📋 发现可能待付的链接/账单数量: {count}")
        if count > 0:
            target_invoice = unpaid_items.first
            log("🖱️ 点击进入最新的账单...")
            target_invoice.click()
            page.wait_for_timeout(3000)
            handle_cloudflare(page)
            page.screenshot(path="invoice_detail_page.png")

            pay_btn = page.locator('button:has-text("Pay"), a:has-text("Pay"):visible, input[value*="Pay"]').first
            if pay_btn.is_visible():
                log("✅ 在账单页面找到 Pay 按钮，执行支付...")
                pay_btn.click(force=True)
                page.wait_for_timeout(5000)
                page.screenshot(path="invoice_paid_success.png")
                return True
    except Exception as e:
        log(f"⚠️ 处理已有账单失败: {e}")
    return False

def renew_service(page):
    try:
        log("➡ 进入续期流程...")
        if page.url != SERVICE_URL:
            page.goto(SERVICE_URL, wait_until="domcontentloaded", timeout=60000)
        handle_cloudflare(page)
        page.wait_for_timeout(3000)
        page.screenshot(path="service_page.png")

        # 保存整页 HTML 供 F12 深度调试
        with open("page_source.html", "w", encoding="utf-8") as f:
            f.write(page.content())
        log("💾 已导出完整页面源码到 page_source.html")

        log("🖱️ 定位绿色 'Renew' 按钮并提取 F12 DOM 详情...")
        renew_candidates = [
            'button:has-text("Renew"):visible',
            'a:has-text("Renew"):visible',
            'div:has-text("Renew") button:visible',
            '//button[contains(normalize-space(.), "Renew")]',
            '//a[contains(normalize-space(.), "Renew")]'
        ]

        target_btn = None
        for sel in renew_candidates:
            loc = page.locator(sel)
            count = loc.count()
            if count > 0:
                for idx in range(count):
                    item = loc.nth(idx)
                    try:
                        box = item.bounding_box()
                        if box and box['width'] > 20 and box['height'] > 20 and box['y'] > 100:
                            target_btn = item
                            break
                    except Exception:
                        pass
            if target_btn:
                break

        if not target_btn:
            log("⚠️ 坐标筛选未命中，降级为原生查找")
            target_btn = page.get_by_role("button", name=re.compile("Renew", re.I)).first

        # 抓取并输出 F12 DOM 信息
        btn_info = page.evaluate("""(el) => {
            return {
                tag: el.tagName,
                outerHTML: el.outerHTML,
                disabled: el.disabled || false,
                onclick: el.getAttribute('onclick'),
                x_on_click: el.getAttribute('x-on:click') || el.getAttribute('@click'),
                wire_click: el.getAttribute('wire:click'),
                data_modal: el.getAttribute('data-modal-target') || el.getAttribute('data-target') || el.getAttribute('data-bs-target')
            };
        }""", target_btn.element_handle())

        with open("dom_debug.txt", "w", encoding="utf-8") as f:
            for k, v in btn_info.items():
                f.write(f"{k}: {v}\n")
        log(f"🔎 [F12 诊断] 按钮信息:\n  标签: {btn_info.get('tag')}\n  HTML: {btn_info.get('outerHTML')}\n  Alpine/Wire/Modal属性: {btn_info.get('x_on_click') or btn_info.get('wire_click') or btn_info.get('data_modal')}")

        modal_opened = False
        create_btn = page.locator('button:has-text("Create Invoice"), input[value*="Create Invoice"]').first

        for i in range(3):
            try:
                log(f"🖱️ 第 {i+1} 次点击 'Renew'...")
                target_btn.scroll_into_view_if_needed()
                page.wait_for_timeout(500)

                # 尝试通过多种触发方式派发 click
                page.evaluate("""(el) => {
                    el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                    el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                    el.click();
                }""", target_btn.element_handle())

                page.wait_for_timeout(2000)
                page.screenshot(path=f"after_renew_click_{i+1}.png")

                # 检查弹窗
                try:
                    create_btn.wait_for(state="visible", timeout=4000)
                    modal_opened = True
                    log("✅ 弹窗已成功弹出！")
                    page.screenshot(path="modal_opened.png")
                    break
                except Exception:
                    page.wait_for_timeout(1000)

            except Exception as e:
                log(f"❌ 点击出错: {e}")

        if not modal_opened:
            log("❌ 续费弹窗未出现，启动备选方案：检查已有 Invoices...")
            if try_pay_existing_invoices(page):
                log("🎉 已有账单支付完成！")
                page.goto(SERVICE_URL, wait_until="domcontentloaded", timeout=60000)
                handle_cloudflare(page)
                return True
            else:
                log("❌ 弹窗未出现且未能通过 Invoices 页面支付。")
                page.screenshot(path="renew_modal_failed.png")
                return False

        handle_cloudflare(page)
        log("🖱️ 点击 'Create Invoice'...")
        create_btn.click(force=True)

        new_invoice_url = None
        start_wait = time.time()
        while time.time() - start_wait < 90:
            if "/payment/invoice/" in page.url:
                new_invoice_url = page.url
                log(f"🎉 页面已跳转: {new_invoice_url}")
                break
            if page.locator('iframe[src*="challenges.cloudflare.com"]').count() > 0:
                log("⚠️ 遇到拦截，尝试处理...")
                handle_cloudflare(page)
            time.sleep(1)

        if not new_invoice_url:
            log("❌ 未能进入发票页面，超时。")
            page.screenshot(path="renew_stuck_invoice.png")
            return False

        if page.url != new_invoice_url:
            page.goto(new_invoice_url)
        handle_cloudflare(page)
        page.screenshot(path="invoice_page.png")

        log("🔎 查找 'Pay' 按钮...")
        pay_btn = page.locator('a:has-text("Pay"):visible, button:has-text("Pay"):visible').first
        pay_btn.wait_for(state="visible", timeout=30000)
        pay_btn.click(force=True)
        log("✅ 'Pay' 按钮已点击。")

        time.sleep(5)
        page.goto(SERVICE_URL, wait_until="domcontentloaded", timeout=60000)
        handle_cloudflare(page)
        page.screenshot(path="renew_finished.png")
        return True

    except Exception as e:
        log(f"❌ 续费异常: {e}")
        page.screenshot(path="renew_error.png")
        return False

def main():
    if not COOKIE_VALUE and not (EMAIL and PASSWORD):
        log("❌ 缺少登录凭证")
        sys.exit(1)

    global SERVICE_URL

    with sync_playwright() as p:
        try:
            if IS_PROXY:
                log(f"⚙️ 代理已启用: {PROXY_SERVER}")
            else:
                log("🌐 直连模式（未使用代理）")
            
            current_ip = get_current_ip(PROXY_SERVER)
            log(f"🎯 当前出口IP: {current_ip}")

            log("🚀 启动浏览器...")
            browser = p.chromium.launch(
                channel="chrome",
                headless=False,
                args=['--no-sandbox', '--disable-blink-features=AutomationControlled', '--disable-infobars']
            )
            context = browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
                proxy={"server": PROXY_SERVER} if IS_PROXY else None
            )
            page = context.new_page()
            page.add_init_script(STEALTH_JS)

            if not login(page):
                sys.exit(1)

            server_id = get_server_id(page)
            if not server_id:
                log("❌ 无法获取 Server ID，退出。")
                sys.exit(1)
            SERVICE_URL = f"{BASE_URL}/service/{server_id}/manage"

            old_due = get_due_date(page)
            log(f"📆 续费前到期时间：{old_due}")

            renew_result = renew_service(page)

            new_due = old_due
            if renew_result == "NOT_TIME":
                log("⏳ 未到续期时间，目前无法续期")
                status = "⏳ 未到续期时间"
            elif renew_result is False:
                log("❌ 续费失败，脚本退出。")
                status = "❌ 续期失败"
            else:
                new_due = get_due_date(page)
                log(f"📆 续费后到期时间：{new_due}")
                status = "✅ 续期成功"

            send_telegram_notification(status, old_due, new_due)

            if renew_result == "NOT_TIME":
                sys.exit(0)
            elif renew_result is False:
                sys.exit(1)
            else:
                sys.exit(0)
        except Exception as e:
            log(f"❌ 浏览器启动出错: {e}")
            sys.exit(1)
        finally:
            if 'browser' in locals() and browser:
                browser.close()

if __name__ == "__main__":
    main()
