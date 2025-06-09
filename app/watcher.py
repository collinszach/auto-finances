# watcher.py

import os
import time
import shutil
import csv
import ollama
from pathlib import Path
from datetime import datetime
import dotenv

load_dotenv()

# --- Configuration ---
INCOMING_DIR = Path("~/Finances/Documents/Incoming").expanduser()
PROCESSED_DIR = Path("~/Finances/Documents/Processed").expanduser()
FAILED_DIR = Path("~/Finances/Documents/Failed").expanduser()
LOG_FILE = Path("~/Finances/Documents/watcher_log.csv").expanduser()
OLLAMA_MODEL = "llama3"  # Change to match your installed model
STANDARD_HEADERS = ["transaction_date", "description", "amount", "category", "card"]
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

# --- Utilities ---
def normalize_csv_via_ollama(raw_csv: str, card_name: str):
    prompt = f"""
You are a financial transaction normalizer.
Given raw CSV data from a credit card statement, return only valid transaction rows in CSV format with the headers:
transaction_date, description, amount, category, card

Requirements:
- Dates must be ISO format: YYYY-MM-DD
- Amount must be numeric, no currency symbols
- Card must be set to: {card_name}
- No introductory/explanatory text. Just CSV output.

Here is the raw data:
{raw_csv}
"""
    response = ollama.chat(model=OLLAMA_MODEL, messages=[{"role": "user", "content": prompt}], options={"base_url": OLLAMA_BASE_URL})
    return response['message']['content']

def validate_csv(content: str) -> bool:
    reader = csv.DictReader(content.splitlines())
    return set(STANDARD_HEADERS).issubset(set(reader.fieldnames))

def log_event(filename, status, message=""):
    with open(LOG_FILE, "a") as log:
        log.write(f"{datetime.now()},{filename},{status},{message}\n")

def process_file(file_path: Path):
    card_name = file_path.stem.split("_")[0].lower()
    lock_file = file_path.with_suffix(".processed")

    if lock_file.exists():
        return  # Already handled

    try:
        raw = file_path.read_text()
        normalized = normalize_csv_via_ollama(raw, card_name)

        if "transaction_date" not in normalized.splitlines()[0].lower():
            raise ValueError("Ollama response missing headers")

        if validate_csv(normalized):
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            out_path = PROCESSED_DIR / f"{file_path.stem}_normalized_{timestamp}.csv"
            out_path.write_text(normalized)

            shutil.move(file_path, PROCESSED_DIR / f"raw_{file_path.name}")
            lock_file.touch()
            log_event(file_path.name, "processed")
            print(f"✅ Processed: {file_path.name}")
        else:
            raise ValueError("Validation failed: CSV headers missing or incorrect")

    except Exception as e:
        shutil.move(file_path, FAILED_DIR / file_path.name)
        log_event(file_path.name, "failed", str(e))
        print(f"❌ Failed: {file_path.name} — {e}")

# --- Main Loop ---
def main():
    print("📡 Watching for new CSV files in Incoming...")
    INCOMING_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    FAILED_DIR.mkdir(parents=True, exist_ok=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.touch(exist_ok=True)

    while True:
        for file in INCOMING_DIR.glob("*.csv"):
            process_file(file)
        time.sleep(30)

if __name__ == "__main__":
    main()
