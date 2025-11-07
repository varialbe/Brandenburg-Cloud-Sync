# 🗂️ Brandenburg Cloud Folder Sync

<p align="center">
  <img src="https://i.imgur.com/4lS8eg5.jpeg" alt="Brandenburg Cloud Folder Sync Banner" width="820">
</p>

# 🗂️ Brandenburg Cloud Folder Sync


## 1. Was das Tool ist
**Brandenburg Cloud Folder Sync** ist ein Python-Tool mit GUI, das automatisch ganze Ordner in die [Schul-Cloud Brandenburg](https://brandenburg.cloud) hochlädt.  
Es loggt sich mit echten Schul-Zugangsdaten ein, holt intern die benötigten CSRF-Tokens, erzeugt signierte Upload-URLs (Presigned S3 URLs) und lädt die Dateien dann sicher direkt auf den Schul-Cloud-Speicher hoch.

Das Tool kann:
- sich automatisch einloggen  
- komplette Ordner durchsuchen (auch rekursiv)  
- Dateien anhand von Filterregeln hochladen  
- Fortschritt und Logs live anzeigen  
- optional mehrere Upload-Threads gleichzeitig nutzen  

---

## 2. Warum ich es entwickelt habe
Als Schüler wollte ich **den Cloud-Speicher meiner Schule wirklich nutzen**, anstatt dass er einfach leer herumliegt.  
Die offizielle Oberfläche ist langsam und unpraktisch – man kann keine ganzen Ordner hochladen, keine Synchronisation und keine Batch-Uploads machen.

Dieses Projekt zeigt, dass man mit ein bisschen technischem Wissen und Reverse-Engineering einen echten **praktischen Nutzen aus der Schul-Cloud** ziehen kann.  
Perfekt z. B. für:
- Backups von Schulprojekten  
- private Dokumente oder Fotos (mit Schulzugang sowieso verschlüsselt gespeichert)  
- einfach „freien Speicherplatz“ für Dinge, die man nicht verlieren will 😉  

---

## 3. File-Speed und Effizienz
Bei echten Tests wurden:
- **39 Dateien** (gesamt ca. **16 MB**)  
- in nur **32 Sekunden** hochgeladen  
- ≈ **0,5 MB/s** bzw. **1,2 Dateien pro Sekunde**

Das klingt vielleicht wenig, aber die Schul-Cloud nutzt S3-basierte Uploads mit Token-Authentifizierung – das ist völlig ausreichend für normale Nutzung.  
Mit Parallel-Uploads (Multithreading) wären sogar **1 MB/s +** locker möglich.

---

## 4. Hinweise & Sicherheit
Dieses Tool wurde **nur zu Lern- und Bildungszwecken** entwickelt.  
Es demonstriert, wie Web-Logins, CSRF-Tokens und signierte URLs technisch funktionieren.  
Es **soll keine Schul-Cloud-Nutzung automatisieren oder missbrauchen**, sondern lediglich zeigen, wie man als Schüler aus begrenzten Tools etwas Praktisches herausholen kann.  

> **Wichtiger Hinweis:**  
> Es wird dringend empfohlen, **alle hochzuladenden Dateien vorher in ein 7z-Archiv zu packen und mit einem Passwort zu verschlüsseln.**  
> Der Speicher ist ausschließlich mit einem gültigen Schul-Login zugänglich.

---

## 5. Technisches
- **Sprache:** Python 3  
- **GUI:** Tkinter (Dark Mode)  
- **Libraries:** `requests`, `bs4`, `tkinter`, `threading`  
- **Dateien:**
  - `upload.py` → Kernlogik für Login, CSRF und Upload  
  - `sync_gui.py` → Benutzeroberfläche mit Fortschrittsanzeige  

---

### 🚀 Optionaler Ausblick
Ein nächster Schritt wäre **Multithreading-Upload**, um parallele Requests an die S3-Server zu schicken.  
Das würde die Effizienz massiv steigern – theoretisch bis zur Maximalbandbreite der Internetleitung.

---

© 2025 – Educational Use Only  
Author: @varialbe 
