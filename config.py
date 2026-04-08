# -*- coding: utf-8 -*-
"""
Arabam.com Ticari Araç Fotoğraf Scraper - Yapılandırma
=======================================================
"""

import os

# ============================================================
# PROJE DİZİN AYARLARI
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATASET_DIR = os.path.join(BASE_DIR, "dataset")
LOG_FILE = os.path.join(BASE_DIR, "scraper.log")

# ============================================================
# HEDEF KATEGORİLER (arabam.com)
# ============================================================
KATEGORILER = {
    "kamyon_kamyonet": "https://www.arabam.com/ikinci-el/ticari-arac/kamyon-kamyonet?take=50",
}

# Sayfa başına ilan sayısı (take parametresi)
SAYFA_BASINA_ILAN = 50

# ============================================================
# SCRAPING AYARLARI
# ============================================================
# Her kategoriden kaç sayfa taranacak (0 = tümü)
MAKS_SAYFA = 0

# Her ilandan ilk 6 fotoğraf (0-indeksli: 0,1,2,3,4,5)
HEDEF_FOTO_INDEKSLERI = [0, 1, 2, 3, 4, 5]

# Sayfalar arası bekleme (saniye) — arabam.com agresif değil
MIN_BEKLEME = 1
MAKS_BEKLEME = 2

# İlan detay sayfası bekleme
ILAN_MIN_BEKLEME = 1
ILAN_MAKS_BEKLEME = 2

# Görsel indirme arası bekleme (paralel indirme kullanılıyor)
INDIRME_MIN_BEKLEME = 0.3
INDIRME_MAKS_BEKLEME = 0.8

# Cooldown: Her N ilandan sonra mola
COOLDOWN_ILAN_SAYISI = 50
COOLDOWN_MIN = 10    # 10 sn
COOLDOWN_MAKS = 20   # 20 sn

SAYFA_TIMEOUT = 30
YENIDEN_DENEME = 3

# ============================================================
# TARAYICI AYARLARI
# ============================================================
HEADLESS = False
PENCERE_GENISLIK = 1920
PENCERE_YUKSEKLIK = 1080
