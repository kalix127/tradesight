<div align="center">
    <h3 align="center" style="font-size: 35px">Tradesight</h3>
    <p>Converte i PDF Trade Republic in CSV/XLSX/JSON</p>
    <p align="center">
        <a href="README.it.md">🇮🇹 Versione italiana</a>
        &nbsp;•&nbsp;
        <a href="README.md">🇬🇧 Versione inglese</a>
        <br />
        <a href="https://github.com/kalix127/tradesight/issues/new" target="_blank">🐞 Segnala un bug</a>
        &nbsp;•&nbsp;
        <a href="https://github.com/kalix127/tradesight/issues/new" target="_blank">✨ Richiedi una feature</a>
    </p>
    <img src="./.github/readme/preview.gif" alt="KalixOS Preview" width="100%">
</div>

> Converte gli estratti conto Trade Republic in CSV usando un modello visivo su Ollama. Nato per PDF Trade Republic; altri layout potrebbero funzionare ma non sono supportati/testati.

## 📚 Indice

- [🚀 Panoramica](#-panoramica)
- [💻 Supporto Piattaforme](#-supporto-piattaforme)
- [⚠️ Avvertenze](#️-avvertenze)
- [🧰 Requisiti](#-requisiti)
- [🛠️ Installazione](#️-installazione-unix)
- [⚙️ Configurazione](#-configurazione)
- [▶️ Utilizzo](#️-utilizzo)
- [🤖 Modelli consigliati](#-modelli-consigliati)
- [📤 Output](#-output)
- [🛠️ Troubleshooting](#-troubleshooting)
- [📄 Licenza](#-licenza)

## 🚀 Panoramica

- Pipeline vision-first: rende ogni pagina PDF un'immagine, la migliora e chiede al modello visivo di restituire le righe della tabella.
- Flessibile per lingua: mantiene header/valori esattamente come nel PDF (niente traduzioni); funziona con le varianti locali di Trade Republic.
- Attento ai riepiloghi: salta overview conto/saldo, rollup e riepiloghi liquidità/market value; si concentra sulle tabelle transazioni.
- Un file per PDF (CSV, XLSX o JSON): `<nome_pdf>.<ext>` con tutte le righe nell'ordine originale delle colonne (header normalizzati in minuscolo).

## 💻 Supporto Piattaforme

| OS | Stato | Note |
| --- | --- | --- |
| Linux | Supportato / testato | Piattaforma principale di sviluppo |
| Windows | Supportato / testato | - |
| macOS (Apple Silicon) | Non ancora testato | In programma |

## ⚠️ Avvertenze

- Costruito e testato **solo su estratti Trade Republic**. Altre banche possono funzionare in parte con prompt adattati; nessuna garanzia.
- Utilità personale: nessuna garanzia; uso a proprio rischio.

## 🧰 Requisiti

1. Install Python 3.10+ from [python.org](https://www.python.org/downloads/windows/)
2. Install Git from [git-scm.com](https://git-scm.com/download/win)
3. Install Ollama from [ollama.com](https://ollama.com/download/windows)
4. Install Poppler (see OS-specific instructions below)

## 🛠️ Installazione (Unix/macOS)

```bash
git clone https://github.com/kalix127/tradesight.git
cd tradesight
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Installazione di Poppler

Poppler è richiesto per l'elaborazione PDF. Verifica di averlo installato chiamando `pdftoppm -h` nel tuo terminale.

**Ubuntu/Debian:**
```bash
sudo apt-get install poppler-utils
```

**Arch Linux:**
```bash
sudo pacman -S poppler
```

**macOS:**
```bash
brew install poppler
```

Esegui il setup per scegliere/scaricare un modello e creare `settings.json` (opzionale ma consigliato):
```bash
python3 setup.py
```

Assicurati che Ollama sia attivo:
```bash
ollama serve
```

## 🛠️ Installazione (Windows)

### Passaggi di installazione
```bash
git clone https://github.com/kalix127/tradesight.git
cd tradesight
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### Installazione di Poppler

Poppler è richiesto per l'elaborazione PDF.

**Windows:**
1. Scarica l'ultimo pacchetto poppler da [@oschwartz10612](https://github.com/oschwartz10612/poppler-windows/releases/) che è la più aggiornata
2. Sposta la directory estratta nella posizione desiderata sul tuo sistema
3. Aggiungi la directory `bin/` al tuo PATH
4. Testa che tutto sia andato bene aprendo cmd e assicurandoti di poter chiamare `pdftoppm -h`

### Configurazione setup
Esegui il wizard di setup per configurare e scaricare un modello:
```bash
python setup.py
```

Il setup rileverà automaticamente l'installazione di Ollama su Windows, anche se non è nel PATH.

### Avvia Ollama
Assicurati che Ollama sia in esecuzione prima di processare i PDF:
```bash
ollama serve
```

## ▶️ Utilizzo

### Esecuzione base
```bash
python3 main.py
```
- Legge tutti i PDF in `input_dir`.
- Scrive `<filename>.<ext>` in `output_dir`.

### Modalità debug
```bash
python3 main.py --debug
```
- Mostra risposte grezze del modello e info colonne; più lento ma utile per tuning.

### Partire da una pagina specifica (solo debug)
```bash
python3 main.py --debug --page 3
```
- Salta le pagine precedenti a quella indicata (1-based); utile per concentrarsi su una pagina problematica senza riprocessare tutto il PDF.

## ⚙️ Configurazione

Tutta la config è in `settings.json`. Chiavi:

| Chiave | Tipo | Default | Note |
| --- | --- | --- | --- |
| `input_dir` | string | `input` | Cartella per i PDF. |
| `output_dir` | string | `output` | Cartella per gli output. |
| `output_format` | string | `csv` | `csv` (default), `xlsx` o `json`; selezionabile dal setup. |
| `max_response_chars` | int | `8000` | Tronca/riprova se la risposta del modello supera questo numero di caratteri. |
| `max_tokens` | int | `8000` | Limite superiore passato a Ollama (`num_predict`) per contenere la lunghezza della generazione. |
| `save_page_images` | bool | `true` | Se true, salva i PNG delle pagine renderizzate in `<pdf>_images/` per debug. |
| `image.dpi` | int | `300` | DPI di render (alto = più nitido, più lento). |
| `image.brightness` | float | `1.5` | Fattore di luminosità. |
| `image.contrast` | float | `1.5` | Fattore di contrasto. |
| `image.scale` | float | `0.5` | Fattore di scala (1.0 = nessuna modifica; >1 upscaling, <1 downscaling); utile per numeri piccoli. |
| `parser.model` | string | `ministral-3:8b` | Nome modello in Ollama. |
| `parser.ollama_url` | string | `http://localhost:11434` | Endpoint Ollama. |
| `parser.temperature` | float | `0` | Randomness LLM (basso = più deterministico). |
| `parser.num_ctx` | int | `8192` | Finestra di contesto passata a Ollama (`num_ctx`). |
| `balance_tolerance` | float | `0.00` | Delta ammessa per la verifica del saldo; `0.00` = controllo rigido. |
| `include_error_column` | bool | `true` | Include la colonna `error` (consigliata; segnala righe con campi richiesti mancanti). |
| `include_balance_check_column` | bool | `false` | Include la colonna `balance_check` (mostra flag swapped/mismatch dalla verifica saldo; abilita via `settings.json`). |
| `prompts/system_prompt.txt` | file | modificabile | Prompt principale; puoi adattarlo a layout/lingue nuove. |

Puoi sovrascrivere modello/URL a runtime: `python3 main.py --model <nome> --ollama-url <url>`.

## 🤖 Modelli consigliati

- **Consigliato:** `ministral-3:8b` — massima accuratezza per PDF Trade Republic; ~6GB vRAM (o molta RAM con swap, più lento). Usa questo per evitare output disordinati.

## 📤 Output

- Un file per PDF solo nel formato scelto (`.csv`, `.xlsx` o `.json` con un array di righe).
- Header normalizzati in minuscolo ma nell’ordine del PDF; header duplicati solo per maiuscole/minuscole sono unificati.
- Le colonne importo (`in entrata`, `in uscita`, `saldo`) sono stringhe numeriche senza simboli di valuta.
- Se `include_error_column` è attivo (consigliato), `error = yes` indica campi obbligatori mancanti (data, tipo, descrizione, saldo e almeno uno tra in entrata/in uscita).
- Se `include_balance_check_column` è attivo, `balance_check` mostra `swapped`, `swapped_in_out` o `mismatch` quando interviene la verifica saldo.
- Le righe escludono overview/riepiloghi/liquidità/portfolio; rimangono solo le tabelle transazioni.


## 🛠️ Troubleshooting

- **Importi piccoli mancanti:** alza `image.dpi` (es. 550–600) e `image.scale` (es. 1.6–1.8); mantieni contrasto ≥1.3. Usa un modello più forte se disponibile.
- **Colonne errate/extra:** controlla che `system_prompt.txt` non sia stato modificato male; gli header sono mantenuti nell’ordine PDF e in minuscolo.
- **Righe di riepilogo presenti:** verifica che il PDF segua il layout Trade Republic; i blocchi liquidità/portfolio/overview dovrebbero essere saltati. Se il layout cambia, aggiorna `system_prompt.txt`.
- **Ollama non risponde:** assicurati che `ollama serve` sia in esecuzione e che il modello sia scaricato.

## 📄 Licenza

[MIT](./LICENSE)
