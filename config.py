# -*- coding: utf-8 -*-
"""
Sahibinden Ticari Araç Scraper - Yapılandırma Dosyası
======================================================
Tüm ayarlar bu dosyada merkezi olarak yönetilir.
"""

import os

# ============================================================
# PROJE DİZİN AYARLARI
# ============================================================
# Projenin kök dizini (bu dosyanın bulunduğu yer)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# İndirilen görsellerin kaydedileceği ana klasör
DATASET_DIR = os.path.join(BASE_DIR, "dataset")

# Log dosyasının yolu
LOG_FILE = os.path.join(BASE_DIR, "scraper.log")

# ============================================================
# HEDEF KATEGORİLER
# ============================================================
# Her kategori için: (klasör_adı, sahibinden URL'si)
# Sahibinden ticari araçlar alt kategorileri
KATEGORILER = {
    "kamyonet": "https://www.sahibinden.com/ticari-araclar-kamyonet",
    "minivan": "https://www.sahibinden.com/ticari-araclar-minivan-panelvan",
    "kamyon": "https://www.sahibinden.com/ticari-araclar-kamyon",
    "minibus": "https://www.sahibinden.com/ticari-araclar-minibus",
}

# ============================================================
# SCRAPING AYARLARI
# ============================================================
# Her kategoriden kaç sayfa taranacak (0 = tümü)
MAKS_SAYFA = 5

# Her ilandan hangi sıradaki fotoğraflar indirilecek (0-indeksli)
# 3., 4. ve 5. fotoğraflar = indeks 2, 3, 4
HEDEF_FOTO_INDEKSLERI = [2, 3, 4]

# Sayfalar arası minimum ve maksimum bekleme süresi (saniye)
MIN_BEKLEME = 3
MAKS_BEKLEME = 8

# İlan detay sayfasına giriş öncesi bekleme (saniye)
ILAN_MIN_BEKLEME = 2
ILAN_MAKS_BEKLEME = 5

# Görsel indirme arası bekleme (saniye)
INDIRME_MIN_BEKLEME = 1
INDIRME_MAKS_BEKLEME = 3

# Selenium sayfa yükleme zaman aşımı (saniye)
SAYFA_TIMEOUT = 30

# Başarısız isteklerde yeniden deneme sayısı
YENIDEN_DENEME = 3

# ============================================================
# TARAYICI AYARLARI
# ============================================================
# Chrome tarayıcısını görünür mı yoksa arka planda mı çalıştıracağız
# True = arka planda (headless), False = görünür pencere
HEADLESS = False

# Tarayıcı pencere boyutu
PENCERE_GENISLIK = 1920
PENCERE_YUKSEKLIK = 1080
