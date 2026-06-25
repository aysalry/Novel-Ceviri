<div align="center">

<img src="app/gui/resources/logo.png" width="120" alt="Novel Çeviri logo" />

# Novel Çeviri

**Webnovel ve lightnovel'leri hızlıca Türkçeye (veya istediğin dile) çeviren, bağımsız bir masaüstü programı.**

[![Lisans](https://img.shields.io/badge/lisans-GPLv3-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows-lightgrey.svg)](#kurulum)
[![GUI](https://img.shields.io/badge/GUI-PyQt6-41cd52.svg)](https://pypi.org/project/PyQt6/)

</div>

---

## Ekran Görüntüleri

<div align="center">
<img src="screenshots/ceviri-kuyrugu.png" width="80%" alt="Çeviri kuyruğu ekranı" />
<br /><br />
<img src="screenshots/webden-al.png" width="80%" alt="Web'den roman indirme ekranı" />
<br /><br />
<img src="screenshots/ayarlar.png" width="80%" alt="Ayarlar ekranı" />
</div>

> Yukarıdaki görseller `screenshots/` klasörüne eklenmeyi bekliyor -- kendi ekran görüntülerini bu isimlerle (`ceviri-kuyrugu.png`, `webden-al.png`, `ayarlar.png`) o klasöre koyman yeterli.

## Özellikler

- **EPUB, TXT ve SRT** dosyalarını çevirir -- biçim, resim, CSS, altyazı zamanlaması bozulmadan korunur.
- **Google (Free), Microsoft Edge (Free), DeepL (Free/Pro) ve Gemini** motorları arasından seç; Gemini için isteğe bağlı "yaratıcılık" (temperature) ayarı.
- **Gerçek hız**: kısa paragrafları birleştirip istek sayısını azaltma, eşzamanlı istek gönderme, kalıcı önbellek (aynı paragrafı iki kez çevirmez) ve otomatik yeniden deneme bir arada.
- **Web'den roman indirme**: novelfire.net, novelight.net, novelbuddy.com ve "Madara" temalı birçok sitedeki romanları isimle arayıp doğrudan EPUB'a çevir. Tür/kategori bilgisi de gösterilir.
- **Kütüphane takibi**: indirdiğin romanları arka planda periyodik olarak kontrol eder, yeni bölüm çıkınca masaüstü bildirimi gönderir; yeni bölümleri var olan EPUB'una ekler (üzerine yazmaz).
- **Devam ettirilebilir indirme**: bağlantı kesilse veya iptal etsen de, daha önce inen bölümler diskte kalır.
- **Sözlük desteği**: karakter/yer adlarının her bölümde aynı şekilde çevrilmesini (ya da hiç çevrilmemesini) sağlar.
- **İki dilli çıktı**: orijinal metni çevirinin altında/üstünde tutma seçeneği.
- **Sade ama tatlı arayüz**: açık pastel ve karanlık tema, sistem tepsisi desteği, motor bağlantısını tek tıkla test etme.
- Çöken/hata veren bir şey olursa `%APPDATA%/NovelCeviri/app.log` dosyasında neyin yanlış gittiğini bulabilirsin.

## Kurulum

### Hazır .exe ile (Windows, önerilen)

[Releases](../../releases) sayfasından en son `NovelCeviri.exe` dosyasını indirip çalıştırman yeterli -- Python kurmana gerek yok.

### Kaynak koddan çalıştırma

```bash
git clone <bu-deponun-adresi>
cd "ceviri novel"
pip install -r requirements.txt
python main.py
```

Windows'ta konsol penceresi açılmadan çalıştırmak için `main.py` yerine `main.pyw` kullanabilirsin (çift tıklayarak veya `pythonw main.pyw` ile).

### Kendi .exe'ni build etmek

```bash
pip install pyinstaller
pyinstaller NovelCeviri.spec
```

Çıkan dosya `dist/NovelCeviri.exe` olur.

## Kullanım

1. **Çeviri Kuyruğu** sekmesinde "+ Dosya Ekle" ile EPUB/TXT/SRT dosyalarını ekle (ya da pencereye sürükle-bırak).
2. Çeviri motorunu ve hedef dili seç, "Çeviriyi Başlat"a bas.
3. Elindeki dosya yoksa **Web'den Al** sekmesinde roman adını ara, bölüm aralığını seç, "EPUB Oluştur"a bas -- "Çeviri kuyruğuna ekle" işaretliyse indirilen EPUB otomatik olarak çeviri kuyruğuna eklenir.
4. Motor/API anahtarı ayarlarını, hız ayarlarını ve görünümü **Araçlar > Ayarlar**'dan değiştirebilirsin; "Test Et" ile bir motorun gerçekten çalıştığını kaydetmeden önce doğrulayabilirsin.

## Teşekkürler ve Lisans

Bu proje, [bookfere.com](https://github.com/bookfere) tarafından geliştirilen açık kaynaklı **["Ebook Translator" Calibre eklentisinden](https://github.com/bookfere/Ebook-Translator-Calibre-Plugin)** (GPLv3) uyarlanmış bir çeviri motoru, önbellek ve içerik çıkarma mantığı kullanır; bu nedenle bu proje de **GPLv3** ile lisanslanmıştır (bkz. [LICENSE](LICENSE)).

Roman indirme özelliği, [dteviot](https://github.com/dteviot)'un **["WebToEpub"](https://github.com/dteviot/WebToEpub)** (GPLv3) ve [kodjodevf](https://github.com/kodjodevf)'in **["Mangayomi"](https://github.com/kodjodevf/mangayomi)** (Apache 2.0) projelerinden esinlenerek sıfırdan yazılmıştır.

## Sorumluluk Reddi

Bu araç yalnızca kendi sahip olduğun ya da telif hakkı içermeyen içerikleri çevirmek/indirmek için tasarlanmıştır. Üçüncü taraf sitelerden içerik çekerken o sitelerin kullanım şartlarına uymak kullanıcının sorumluluğundadır.
