import re
import sqlite3
import time
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

DB_NAME = "google_repos.db"
BASE_URL = "https://github.com/orgs/google/repositories"


def init_db():
    """データベースとテーブルの初期化"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS repositories")
    cursor.execute("""
        CREATE TABLE repositories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            language TEXT,
            stars INTEGER
        )
    """)
    conn.commit()
    return conn


def parse_stars(star_text):
    """'1.2k' や '12,345' などのスター表記を整数に変換する"""
    text = star_text.strip().lower().replace(",", "")
    if not text:
        return 0
    if text.endswith("k"):
        return int(float(text[:-1]) * 1000)
    if text.endswith("m"):
        return int(float(text[:-1]) * 1000000)
    try:
        return int(text)
    except ValueError:
        return 0


def scrape_google_repos(conn):
    """PlaywrightでGitHubページを描画し、全ページスクレイピングしてDBに保存"""
    cursor = conn.cursor()
    page_num = 1
    total_saved = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        while True:
            url = f"{BASE_URL}?page={page_num}"
            print(f"Fetching page {page_num}: {url}")

            page.goto(url, wait_until="domcontentloaded")
            # リポジトリ一覧が描画されるまで待機
            try:
                page.wait_for_selector('a[href^="/google/"]', timeout=10000)
            except Exception:
                print("リポジトリ一覧が見つかりませんでした。処理を終了します。")
                break

            soup = BeautifulSoup(page.content(), "html.parser")

            # リポジトリの各行を取得
            repo_items = soup.select('div[data-testid="list-view-items"] > ul > li')
            if not repo_items:
                # 構造が変わっている場合のフォールバック（/google/リポジトリ名 へのリンクを含むli要素）
                repo_items = [
                    li for li in soup.select("li")
                    if li.select_one('a[href^="/google/"][data-testid]') or li.select_one('h3 a[href^="/google/"]')
                ]

            if not repo_items:
                print("これ以上リポジトリが見つかりませんでした。処理を終了します。")
                break

            for item in repo_items:
                # 1. リポジトリ名
                name_tag = item.select_one('a[href^="/google/"]')
                if not name_tag:
                    continue
                repo_name = name_tag.get_text(strip=True)

                # 2. 主要な言語
                lang_tag = item.select_one('span[itemprop="programmingLanguage"]')
                if not lang_tag:
                    # 言語丸アイコンの隣にあるテキストを取得
                    color_dot = item.select_one('span[style*="background-color"]')
                    if color_dot and color_dot.parent:
                        lang_tag = color_dot.parent.find("span", string=True)
                language = lang_tag.get_text(strip=True) if lang_tag else "None"

                # 3. スター数
                star_tag = item.select_one('a[href$="/stargazers"]')
                stars = parse_stars(star_tag.get_text()) if star_tag else 0

                cursor.execute(
                    "INSERT INTO repositories (name, language, stars) VALUES (?, ?, ?)",
                    (repo_name, language, stars),
                )
                total_saved += 1

            conn.commit()
            print(f"Page {page_num} 完了（累計 {total_saved} 件保存）")

            # 「Next」ボタンの有効確認
            next_btn = soup.select_one('a[rel="next"], a[aria-label="Next Page"]')
            if not next_btn or next_btn.get("aria-disabled") == "true":
                print("最終ページに到達しました。")
                break

            page_num += 1
            # 課題要件：1秒待機
            time.sleep(1)

        browser.close()


def display_data(conn):
    """保存したデータをSELECT文で取得して表示"""
    cursor = conn.cursor()
    print("\n--- 保存されたリポジトリ一覧（先頭20件を表示） ---")
    cursor.execute("SELECT id, name, language, stars FROM repositories LIMIT 20")
    rows = cursor.fetchall()

    for row in rows:
        print(f"ID: {row[0]} | リポジトリ名: {row[1]} | 言語: {row[2]} | スター数: {row[3]}")

    cursor.execute("SELECT COUNT(*) FROM repositories")
    count = cursor.fetchone()[0]
    print(f"\n合計保存件数: {count} 件")


if __name__ == "__main__":
    connection = init_db()
    try:
        scrape_google_repos(connection)
        display_data(connection)
    finally:
        connection.close()