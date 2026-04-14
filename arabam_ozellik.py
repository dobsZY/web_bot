# -*- coding: utf-8 -*-
"""
Arabam.com İlan Özellik Toplayıcı (Hızlı - requests)
=====================================================
Mevcut dataset/kamyon_kamyonet/ klasöründeki ilan numaralarından
her ilanın detay sayfasını requests ile çeker, özellikleri ozellikler.txt'ye yazar.
Resimleri tekrar indirmez. Selenium kullanmaz — çok hızlı.

Kullanım:
    python arabam_ozellik.py
"""

import os
import sys
import time
import random
import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup

# ============================================================
# AYARLAR
# ============================================================

DATASET_DIR = "dataset"
KATEGORI = "kamyon_kamyonet"
OZELLIK_DOSYA = "ozellikler.txt"

# Hız ayarları
PARALEL = 8          # Aynı anda kaç ilan işlensin
MIN_BEKLEME = 0.2    # İstek arası min bekleme
MAKS_BEKLEME = 0.5   # İstek arası max bekleme
COOLDOWN_HER = 100   # Her 100 ilanda mola
COOLDOWN_SURE = 5    # 5 sn mola
YENIDEN_DENEME = 2

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
    "Referer": "https://www.arabam.com/",
}

# ============================================================
# LOG
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("arabam_ozellik")

# ============================================================
# ÖZELLİK ÇEKME
# ============================================================

def ilan_url(ilan_id: str) -> str:
    return f"https://www.arabam.com/ilan/{ilan_id}"


def ozellikleri_cek(ilan_id: str, session: requests.Session) -> dict | None:
    """Arabam.com ilan detay sayfasından özellikleri çek (requests + BS4)."""
    url = ilan_url(ilan_id)
    for deneme in range(YENIDEN_DENEME):
        try:
            r = session.get(url, timeout=15, headers=HEADERS)
            if r.status_code == 404 or (r.status_code == 200 and 'Sayfa Bulunamadı' in r.text[:500]):
                return None  # İlan silinmiş
            if r.status_code != 200:
                time.sleep(1)
                continue

            soup = BeautifulSoup(r.text, "lxml")
            veri = {}

            # Başlık
            h1 = soup.select_one("h1")
            veri["baslik"] = h1.get_text(strip=True) if h1 else ""

            # Fiyat
            fiyat_el = soup.select_one('[class*="price"]') or soup.select_one('[data-testid="desktopPrice"]')
            veri["fiyat"] = fiyat_el.get_text(strip=True) if fiyat_el else ""

            # Konum
            konum_el = soup.select_one('[class*="location"]')
            veri["konum"] = konum_el.get_text(strip=True) if konum_el else ""

            # Tarih
            tarih_el = soup.select_one('[class*="date"]')
            veri["tarih"] = tarih_el.get_text(strip=True) if tarih_el else ""

            # Özellik tablosu
            veri["ozellikler"] = {}

            # Pattern 1: property-key / property-value
            for row in soup.select('[class*="property"]'):
                spans = row.select("span")
                if len(spans) >= 2:
                    key = spans[0].get_text(strip=True)
                    val = spans[-1].get_text(strip=True)
                    if key and val and key != val:
                        veri["ozellikler"][key] = val

            # Pattern 2: dt/dd pairs
            for dt in soup.select("dt"):
                dd = dt.find_next_sibling("dd")
                if dd:
                    key = dt.get_text(strip=True)
                    val = dd.get_text(strip=True)
                    if key and val:
                        veri["ozellikler"][key] = val

            # Pattern 3: table rows
            for tr in soup.select("tr"):
                tds = tr.select("td, th")
                if len(tds) >= 2:
                    key = tds[0].get_text(strip=True)
                    val = tds[1].get_text(strip=True)
                    if key and val and key != val and len(key) < 50:
                        veri["ozellikler"][key] = val

            # Pattern 4: li içinde key-value
            for li in soup.select("li"):
                spans = li.select("span")
                if len(spans) >= 2:
                    key = spans[0].get_text(strip=True)
                    val = spans[-1].get_text(strip=True)
                    if key and val and key != val and len(key) < 50:
                        if key not in veri["ozellikler"]:
                            veri["ozellikler"][key] = val

            # Açıklama
            aciklama_el = (
                soup.select_one('[class*="detail-description"]') or
                soup.select_one('[class*="description"]') or
                soup.select_one('[id*="description"]')
            )
            veri["aciklama"] = aciklama_el.get_text(strip=True) if aciklama_el else ""

            # JSON-LD
            for script in soup.select('script[type="application/ld+json"]'):
                try:
                    import json
                    j = json.loads(script.string or "")
                    if isinstance(j, dict):
                        if j.get("name") and not veri["baslik"]:
                            veri["baslik"] = j["name"]
                        if j.get("brand"):
                            b = j["brand"]
                            if isinstance(b, dict):
                                veri["ozellikler"]["Marka"] = b.get("name", "")
                            elif isinstance(b, str):
                                veri["ozellikler"]["Marka"] = b
                        if j.get("offers") and isinstance(j["offers"], dict):
                            p = j["offers"].get("price", "")
                            c = j["offers"].get("priceCurrency", "")
                            if p:
                                veri["ozellikler"]["Fiyat (JSON)"] = f"{p} {c}".strip()
                except Exception:
                    pass

            return veri

        except requests.RequestException:
            if deneme < YENIDEN_DENEME - 1:
                time.sleep(1)
    return None


def txt_yaz(klasor: str, veri: dict) -> None:
    """Özellikleri txt dosyasına yaz."""
    dosya = os.path.join(klasor, OZELLIK_DOSYA)
    with open(dosya, "w", encoding="utf-8") as f:
        if veri.get("baslik"):
            f.write(f"Başlık: {veri['baslik']}\n")
        if veri.get("fiyat"):
            f.write(f"Fiyat: {veri['fiyat']}\n")
        if veri.get("konum"):
            f.write(f"Konum: {veri['konum']}\n")
        if veri.get("tarih"):
            f.write(f"Tarih: {veri['tarih']}\n")

        ozellikler = veri.get("ozellikler", {})
        if ozellikler:
            f.write("\n--- Özellikler ---\n")
            for k, v in ozellikler.items():
                f.write(f"{k}: {v}\n")

        if veri.get("aciklama"):
            f.write(f"\n--- Açıklama ---\n{veri['aciklama']}\n")


# ============================================================
# TEK İLAN İŞLE (thread'den çağrılır)
# ============================================================

def ilan_isle(ilan_id: str, klasor: str, session: requests.Session) -> tuple[str, bool, str]:
    """Tek bir ilanı işle. (ilan_id, basarili, mesaj) döner."""
    time.sleep(random.uniform(MIN_BEKLEME, MAKS_BEKLEME))
    veri = ozellikleri_cek(ilan_id, session)

    if veri is None:
        return (ilan_id, False, "sayfa yok/hata")

    if not veri.get("baslik") and not veri.get("ozellikler"):
        return (ilan_id, False, "özellik bulunamadı")

    txt_yaz(klasor, veri)
    ozet = veri.get("baslik", "?")[:40]
    oz_sayisi = len(veri.get("ozellikler", {}))
    return (ilan_id, True, f"{ozet} | {oz_sayisi} özellik")


# ============================================================
# ANA İŞLEM
# ============================================================

def calistir():
    kat_dir = os.path.join(DATASET_DIR, KATEGORI)
    if not os.path.isdir(kat_dir):
        log.error(f"Klasör bulunamadı: {kat_dir}")
        return

    tum_klasorler = sorted([
        d for d in os.listdir(kat_dir)
        if os.path.isdir(os.path.join(kat_dir, d)) and d.isdigit()
    ])

    eksik = []
    for ilan_id in tum_klasorler:
        txt_yol = os.path.join(kat_dir, ilan_id, OZELLIK_DOSYA)
        if not os.path.exists(txt_yol):
            eksik.append(ilan_id)

    toplam = len(tum_klasorler)
    zaten = toplam - len(eksik)
    log.info(f"Toplam {toplam} ilan, {zaten} zaten özellikli, {len(eksik)} işlenecek.")

    if not eksik:
        log.info("Tüm ilanların özellikleri mevcut!")
        return

    session = requests.Session()
    session.headers.update(HEADERS)

    basarili = 0
    hatali = 0
    islenen = 0

    # Paralel işleme
    log.info(f"{PARALEL} paralel thread ile başlıyor...")
    batch_size = COOLDOWN_HER

    for batch_start in range(0, len(eksik), batch_size):
        batch = eksik[batch_start:batch_start + batch_size]

        with ThreadPoolExecutor(max_workers=PARALEL) as pool:
            futures = {}
            for ilan_id in batch:
                klasor = os.path.join(kat_dir, ilan_id)
                futures[pool.submit(ilan_isle, ilan_id, klasor, session)] = ilan_id

            for f in as_completed(futures):
                islenen += 1
                ilan_id, ok, mesaj = f.result()
                if ok:
                    basarili += 1
                    if islenen % 10 == 0 or islenen <= 5:
                        log.info(f"  [{islenen}/{len(eksik)}] {ilan_id} ✓ {mesaj}")
                else:
                    hatali += 1
                    log.warning(f"  [{islenen}/{len(eksik)}] {ilan_id} ✗ {mesaj}")

        # Batch bitti, mola
        if batch_start + batch_size < len(eksik):
            log.info(f"  İlerleme: {islenen}/{len(eksik)} — {COOLDOWN_SURE}sn mola...")
            time.sleep(COOLDOWN_SURE)

    print("=" * 60)
    log.info(f"BİTTİ! {basarili} başarılı, {hatali} hatalı, toplam {islenen} işlendi.")


if __name__ == "__main__":
    calistir()
