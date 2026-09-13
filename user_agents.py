"""
Генератор случайных User-Agent и заголовков для обхода rate limiting
"""
import random

# Максимально возможная вариативность User-Agent
USER_AGENTS = [
    # Chrome Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    
    # Chrome macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_1_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    
    # Chrome Linux
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Fedora; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    
    # Firefox Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 Firefox/130.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:129.0) Gecko/20100101 Firefox/129.0",
    "Mozilla/5.0 (Windows NT 11.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
    
    # Firefox macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:132.0) Gecko/20100101 Firefox/132.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:131.0) Gecko/20100101 Firefox/131.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13.6; rv:132.0) Gecko/20100101 Firefox/132.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.0; rv:132.0) Gecko/20100101 Firefox/132.0",
    
    # Firefox Linux
    "Mozilla/5.0 (X11; Linux x86_64; rv:132.0) Gecko/20100101 Firefox/132.0",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:132.0) Gecko/20100101 Firefox/132.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0",
    
    # Safari macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15",
    
    # Edge Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0",
    
    # Edge macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0",
    
    # Opera Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 OPR/117.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 OPR/116.0.0.0",
    
    # Opera macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 OPR/117.0.0.0",
    
    # Brave Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Brave/1.61",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Brave/1.60",
    
    # Vivaldi
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Vivaldi/6.5.3206.63",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Vivaldi/6.5.3206.63",
    
    # Mobile Chrome Android
    "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; SM-A546B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36",
    
    # Mobile Safari iOS
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPad; CPU OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1",
]

# Дополнительная вариативность для Chrome
CHROME_VERSIONS = [
    "131.0.0.0", "130.0.0.0", "129.0.0.0", "128.0.0.0",
    "131.0.6778.86", "130.0.6723.117", "129.0.6668.100",
]

# Версии Firefox
FIREFOX_VERSIONS = ["132.0", "131.0", "130.0", "129.0", "128.0"]

# Версии Safari
SAFARI_VERSIONS = ["18.1", "18.0", "17.6", "17.5"]

# Платформы
PLATFORMS = [
    '"Windows"', '"macOS"', '"Linux"', '"Android"',
]

# Языки
ACCEPT_LANGUAGES = [
    "en-US,en;q=0.9",
    "en-GB,en;q=0.9",
    "en-US,en;q=0.9,ru;q=0.8",
    "ru-RU,ru;q=0.9,en;q=0.8",
    "de-DE,de;q=0.9,en;q=0.8",
    "fr-FR,fr;q=0.9,en;q=0.8",
    "es-ES,es;q=0.9,en;q=0.8",
    "it-IT,it;q=0.9,en;q=0.8",
    "pt-BR,pt;q=0.9,en;q=0.8",
    "ja-JP,ja;q=0.9,en;q=0.8",
    "zh-CN,zh;q=0.9,en;q=0.8",
    "ko-KR,ko;q=0.9,en;q=0.8",
]

# Accept headers
ACCEPT_HEADERS = [
    "*/*",
    "application/json, text/plain, */*",
    "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
]


def get_random_headers():
    """
    Генерировать случайные заголовки для каждого запроса
    
    Returns:
        dict: Словарь с HTTP заголовками
    """
    user_agent = random.choice(USER_AGENTS)
    
    # Определяем тип браузера из User-Agent
    is_chrome = "Chrome" in user_agent and "Edg" not in user_agent and "OPR" not in user_agent
    is_firefox = "Firefox" in user_agent
    is_safari = "Safari" in user_agent and "Chrome" not in user_agent
    
    headers = {
        "Accept": random.choice(ACCEPT_HEADERS),
        "Accept-Language": random.choice(ACCEPT_LANGUAGES),
        "Referer": "https://peek.tg/search",
        "Origin": "https://peek.tg",
        "User-Agent": user_agent,
        "Cache-Control": random.choice(["no-cache", "max-age=0"]),
    }
    
    # Добавляем Accept-Encoding с вариативностью
    encodings = ["gzip", "deflate", "br"]
    if random.random() > 0.3:  # 70% шанс добавить zstd
        encodings.append("zstd")
    random.shuffle(encodings)
    headers["Accept-Encoding"] = ", ".join(encodings)
    
    # Специфичные заголовки для Chrome/Edge/Opera
    if is_chrome:
        chrome_ver = random.choice(["128", "129", "130", "131"])
        platform = random.choice(PLATFORMS)
        
        headers.update({
            "Sec-Ch-Ua": f'"Google Chrome";v="{chrome_ver}", "Chromium";v="{chrome_ver}", "Not_A Brand";v="24"',
            "Sec-Ch-Ua-Mobile": random.choice(["?0", "?1"]) if "Mobile" in user_agent else "?0",
            "Sec-Ch-Ua-Platform": platform,
            "Sec-Fetch-Dest": random.choice(["empty", "document"]),
            "Sec-Fetch-Mode": random.choice(["cors", "navigate"]),
            "Sec-Fetch-Site": random.choice(["same-origin", "cross-site"]),
        })
    
    # Специфичные заголовки для Firefox
    elif is_firefox:
        headers.update({
            "DNT": random.choice(["1", None]),
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "TE": "trailers",
        })
        # Удаляем None значения
        headers = {k: v for k, v in headers.items() if v is not None}
    
    # Иногда добавляем дополнительные заголовки
    if random.random() > 0.5:
        headers["Connection"] = "keep-alive"
    
    if random.random() > 0.7:
        headers["Upgrade-Insecure-Requests"] = "1"
    
    return headers


def get_random_user_agent():
    """
    Получить случайный User-Agent
    
    Returns:
        str: User-Agent строка
    """
    return random.choice(USER_AGENTS)


if __name__ == "__main__":
    # Тест генерации заголовков
    print("=" * 80)
    print("ТЕСТ ГЕНЕРАЦИИ СЛУЧАЙНЫХ ЗАГОЛОВКОВ")
    print("=" * 80)
    
    print(f"\n📊 Доступно {len(USER_AGENTS)} различных User-Agent")
    print(f"📊 Доступно {len(ACCEPT_LANGUAGES)} языков")
    
    print("\n🎲 Примеры сгенерированных заголовков:\n")
    
    for i in range(5):
        print(f"\n--- Пример {i+1} ---")
        headers = get_random_headers()
        for key, value in headers.items():
            print(f"{key}: {value}")