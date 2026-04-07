# Sahibinden Ticari Araç Fotoğraf Scraper

Sahibinden.com üzerindeki ticari araç ilanlarından arka cephe fotoğraflarını otomatik olarak indirerek bir **Computer Vision** veri seti oluşturan Python botudur.

## Özellikler

- **Anti-bot atlatma**: `undetected-chromedriver`, User-Agent rotasyonu, rastgele fare hareketleri, rastgele bekleme süreleri
- **Otomatik sayfalandırma**: Kategori sayfalarında pagination takibi
- **Akıllı fotoğraf seçimi**: Her ilanın 3., 4. ve 5. fotoğraflarını hedefler (arka cephe görselleri)
- **Yüksek çözünürlük**: Thumbnail yerine orijinal boyutlu görselleri indirir
- **Sınıflandırılmış kayıt**: Görseller `dataset/<kategori>/` yapısında düzenlenir
- **Hata toleransı**: Kapsamlı try-except ile kesintisiz çalışma
- **Detaylı loglama**: Hem konsol hem dosya logları

## Proje Yapısı

```
web_bot/
├── config.py          # Tüm ayarlar (URL'ler, bekleme süreleri, vs.)
├── scraper.py         # Ana bot kodu
├── requirements.txt   # Python bağımlılıkları
├── scraper.log        # Çalışma logları (otomatik oluşur)
├── README.md          # Bu dosya
└── dataset/           # İndirilen görseller (otomatik oluşur)
    ├── kamyonet/
    ├── minivan/
    ├── kamyon/
    └── minibus/
```

## Kurulum (Adım Adım)

### 1. Gereksinimler

- **Python 3.9+** yüklü olmalı
- **Google Chrome** tarayıcısı yüklü olmalı (undetected-chromedriver otomatik olarak uygun ChromeDriver'ı indirir)

### 2. Sanal Ortam Oluşturma (Önerilen)

```bash
cd web_bot
python -m venv venv

# Windows:
venv\Scripts\activate

# macOS/Linux:
source venv/bin/activate
```

### 3. Bağımlılıkları Yükleme

```bash
pip install -r requirements.txt
```

### 4. Ayarları Düzenleme

`config.py` dosyasını açıp ihtiyacınıza göre düzenleyin:

| Ayar | Açıklama | Varsayılan |
|------|----------|------------|
| `KATEGORILER` | Taranacak kategoriler ve URL'leri | 4 kategori |
| `MAKS_SAYFA` | Her kategoriden kaç sayfa taranacak | `5` |
| `HEDEF_FOTO_INDEKSLERI` | Hangi sıradaki fotoğraflar indirilecek | `[2, 3, 4]` (3., 4., 5.) |
| `HEADLESS` | Tarayıcı arka planda mı çalışsın | `False` |
| `MIN_BEKLEME` / `MAKS_BEKLEME` | Sayfalar arası bekleme (saniye) | `3` / `8` |

### 5. Botu Çalıştırma

```bash
python scraper.py
```

Bot çalışırken:
- Chrome penceresi açılacak (HEADLESS=False ise)
- Kategoriler sırayla taranacak
- İlan linkleri toplanacak
- Her ilana girilerek hedef fotoğraflar indirilecek
- İlerleme konsola ve `scraper.log` dosyasına yazılacak

### 6. Durdurmak İçin

`Ctrl + C` ile güvenli şekilde durdurabilirsiniz. Bot özet istatistikleri gösterecektir.

## Çıktı Formatı

İndirilen dosyalar şu isimlendirme standardıyla kaydedilir:

```
dataset/kamyonet/1234567_3.jpg   # İlan no: 1234567, 3. fotoğraf
dataset/kamyonet/1234567_4.jpg   # İlan no: 1234567, 4. fotoğraf
dataset/kamyonet/1234567_5.jpg   # İlan no: 1234567, 5. fotoğraf
```

## Önemli Notlar

- **Yasal Sorumluluk**: Bu araç yalnızca eğitim ve araştırma amaçlıdır. Web scraping yaparken hedef sitenin kullanım koşullarına uymanız sizin sorumluluğunuzdadır.
- **Rate Limiting**: Siteye aşırı yük bindirmemek için bekleme süreleri eklenmiştir. Bunları azaltmayın.
- **Cloudflare**: Site Cloudflare koruması kullanıyorsa, ilk açılışta CAPTCHA çözmeniz gerekebilir (HEADLESS=False modunda).
- **Sayfa Yapısı Değişiklikleri**: Sahibinden arayüzünü güncellerse CSS seçicilerinin güncellenmesi gerekebilir.
