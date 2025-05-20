import os
import json
import hashlib
import requests
import re
from datetime import datetime
from time import sleep

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

API_BASE = "https://www.webhallen.com/api/productdiscovery/category/4661?page={page}&touchpoint=DESKTOP&totalProductCountSet=true&sortBy=latest"

DATA_FOLDER = "data"
SEEN_PRODUCTS_FILE = os.path.join(DATA_FOLDER, "seen_products.json")
AVAILABLE_PRODUCTS_FILE = os.path.join(DATA_FOLDER, "available_products.json")

def load_json(file):
    if os.path.exists(file):
        with open(file, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}

def save_json(file, data):
    os.makedirs(DATA_FOLDER, exist_ok=True)
    with open(file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def hash_product(prod):
    h = hashlib.sha256()
    h.update(str(prod.get("id")).encode())
    h.update(prod.get("mainTitle", "").encode())

    stock_data = prod.get("stock", {})
    if not isinstance(stock_data, dict):
        stock_data = {}

    h.update(str(stock_data.get("web", 0)).encode())
    return h.hexdigest()

def slugify(text):
    text = text.replace("&", "")
    text = text.replace(":", "")
    text = text.replace(".", "-")
    text = re.sub(r"[()]", "", text)
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"\s+", "-", text)
    return text

def is_preorder(product_url):
    try:
        r = requests.get(product_url, timeout=10)
        r.raise_for_status()
        text = r.text.lower()
        for keyword in ["förhandsboka", "förbeställ", "preorder"]:
            if keyword in text:
                return True
    except Exception as e:
        print(f"Fel vid preorder-check för {product_url}: {e}")
    return False

def send_discord_message(prod_id, prod_name, prod_url, event_type, price, image_url):
    color_map = {
        "new": 0x1ABC9C,
        "back_in_stock": 0xE67E22
    }
    color = color_map.get(event_type, 0x3498DB)

    data = {
        "embeds": [{
            "title": f"{'🎉 NY PRODUKT: ' if event_type == 'new' else '✅ PRODUKT TILLGÄNGLIG IGEN: '}{prod_name}",
            "url": prod_url,
            "description": f"💰 Pris: {price} kr",
            "color": color,
            "image": {"url": image_url},
            "footer": {"text": "Webhallen Product Monitor"},
            "timestamp": datetime.utcnow().isoformat()
        }]
    }
    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json=data, timeout=10)
        if resp.status_code != 204:
            print(f"Discord webhook fel: {resp.status_code} {resp.text}")
    except Exception as e:
        print(f"Discord webhook exception: {e}")

def main():
    seen_products = load_json(SEEN_PRODUCTS_FILE)
    available_products = load_json(AVAILABLE_PRODUCTS_FILE)

    page = 1
    all_products = []

    while True:
        api_url = API_BASE.format(page=page)
        print(f"Hämtar sida {page} från API...")
        r = requests.get(api_url, timeout=10)
        if r.status_code != 200:
            print(f"Fel vid API-anrop: {r.status_code}")
            break
        data = r.json()
        products = data.get("products", [])
        if not products:
            break
        all_products.extend(products)
        page += 1

    new_seen_products = {}
    new_available_products = {}

    for prod in all_products:
        prod_id = str(prod["id"])
        prod_name = prod.get("mainTitle", "Okänt namn")
        safe_name = slugify(prod_name)
        prod_url = f"https://www.webhallen.com/se/product/{prod_id}-{safe_name}"
        images = prod.get("images", [])
        image_url = images[0]["url"] if images else f"https://cdn.webhallen.com/images/product/{prod_id}?trim"

        
        release_ts = prod.get("release", {}).get("timestamp", 0)
        now_ts = datetime.utcnow().timestamp()
        is_released = release_ts <= now_ts

        stock_data = prod.get("stock", {})
        if not isinstance(stock_data, dict):
            stock_data = {}
        
        in_stock = stock_data.get("web", 0) > 0

        preorder = False
        if not is_released:
            preorder = is_preorder(prod_url)

        price = "Okänt"
        price_info = prod.get("price", {})
        if isinstance(price_info, dict):
            if "current" in price_info and isinstance(price_info["current"], dict) and "value" in price_info["current"]:
                price = price_info["current"]["value"]
            elif "price" in price_info:
                price = price_info["price"]
            elif "currentPrice" in price_info:
                price = price_info["currentPrice"]

        prod_hash = hash_product(prod)

        if prod_id not in seen_products:
            send_discord_message(prod_id, prod_name, prod_url, "new", price, image_url)
        else:
            prev_in_stock = available_products.get(prod_id, False)
            if not prev_in_stock and (in_stock or preorder):
                send_discord_message(prod_id, prod_name, prod_url, "back_in_stock", price, image_url)

        new_seen_products[prod_id] = prod_hash
        new_available_products[prod_id] = in_stock or preorder

        sleep(0.1)

    save_json(SEEN_PRODUCTS_FILE, new_seen_products)
    save_json(AVAILABLE_PRODUCTS_FILE, new_available_products)

if __name__ == "__main__":
    main()
