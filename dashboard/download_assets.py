import os
import urllib.request
import re

def download_file(url, path):
    print(f"Downloading {url} to {path}")
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'})
    with urllib.request.urlopen(req) as response, open(path, 'wb') as out_file:
        out_file.write(response.read())

os.makedirs("assets/fonts", exist_ok=True)
os.makedirs("assets/css", exist_ok=True)

# 1. Download Boxicons
boxicons_css_url = "https://unpkg.com/boxicons@2.1.4/css/boxicons.min.css"
download_file(boxicons_css_url, "assets/css/boxicons.min.css")
for ext in ["woff2", "woff", "ttf"]:
    font_url = f"https://unpkg.com/boxicons@2.1.4/fonts/boxicons.{ext}"
    download_file(font_url, f"assets/fonts/boxicons.{ext}")

# 2. Download Google Fonts CSS
gf_url = "https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;800&family=Outfit:wght@400;700&display=swap"
print(f"Downloading Google Fonts CSS from {gf_url}")
req = urllib.request.Request(gf_url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'})
with urllib.request.urlopen(req) as response:
    css_content = response.read().decode('utf-8')

# Find all font URLs in CSS
urls = re.findall(r'url\((https://fonts\.gstatic\.com/s/[^)]+)\)', css_content)
for url in set(urls):
    filename = url.split('/')[-1]
    download_file(url, f"assets/fonts/{filename}")
    # Replace in CSS
    css_content = css_content.replace(url, f"../fonts/{filename}")

with open("assets/css/fonts.css", 'w') as f:
    f.write(css_content)

print("Done downloading assets!")
