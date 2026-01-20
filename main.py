import json
import pandas as pd
from pathlib import Path
import ollama
from pdf2image import convert_from_path, pdfinfo_from_path
from dataclasses import dataclass
from typing import List, Optional, Callable
import re
import time
from rich.console import Console
from rich.theme import Theme
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
import signal
import sys
import base64
from io import BytesIO
import gc
from PIL import Image, ImageEnhance
from const import (
    PROJECT_NAME,
    AUTHOR,
    ISIN_KEY,
    UNITS_MARKERS,
    PRICE_MARKERS,
    MARKET_VALUE_MARKERS,
    ROW_KEYS_OF_INTEREST,
    BALANCE_KEYS,
    PRODUCT_HEADER_MARKERS,
    BALANCE_ROLLUP_MARKERS,
    LIQUIDITY_MARKERS,
    DEFAULT_VISION_EXTRACTION_PROMPT,
    DEFAULT_OUTPUT_FORMAT,
    OUTPUT_FORMAT_CHOICES,
    OUTPUT_EXTENSIONS,
    DEFAULT_TEMPERATURE,
    DEFAULT_MAX_RESPONSE_CHARS,
    DEFAULT_MAX_TOKENS,
    DEFAULT_NUM_CTX,
)

current_model = None
ollama_url = None

def cleanup_and_exit(signum=None, frame=None):
    """cleanup function to unload ollama model and exit"""
    global current_model, ollama_url

    console.print("\n[yellow]warning: interrupt received, cleaning up...[/yellow]")

    if current_model and ollama_url:
        try:
            console.print(f"[info]unloading model {current_model} from memory...[/info]")
            client = ollama.Client(host=ollama_url)
            # use generate command with empty prompt to stop the model
            client.generate(model=current_model, prompt='', keep_alive=0)
            console.print("[green]model unloaded successfully[/green]")
        except Exception as e:
            console.print(f"[yellow]warning: could not unload model: {str(e)[:50]}...[/yellow]")

    console.print("[info]goodbye![/info]")
    sys.exit(0)

signal.signal(signal.SIGINT, cleanup_and_exit)
signal.signal(signal.SIGTERM, cleanup_and_exit)

custom_theme = Theme({
    "info": "cyan",
    "warning": "yellow",
    "error": "bold red",
    "success": "bold green",
    "progress": "blue",
    "processing": "magenta",
    "brand": "bold blue",
    "metric": "bright_cyan"
})

console = Console(theme=custom_theme)
BRAND_NAME = f"{PROJECT_NAME} by {AUTHOR}"

def parse_args(argv: list[str]):
    """Simple argument parser."""
    debug_mode = '--debug' in argv
    model_override = None
    url_override = None
    start_page = None

    if '--model' in argv:
        try:
            model_override = argv[argv.index('--model') + 1]
        except (ValueError, IndexError):
            console.print("[warning]--model flag provided without a value; ignoring.[/warning]")

    if '--ollama-url' in argv:
        try:
            url_override = argv[argv.index('--ollama-url') + 1]
        except (ValueError, IndexError):
            console.print("[warning]--ollama-url flag provided without a value; ignoring.[/warning]")

    if '--page' in argv:
        try:
            start_page = int(argv[argv.index('--page') + 1])
        except (ValueError, IndexError):
            console.print("[warning]--page flag provided without a valid number; ignoring.[/warning]")

    return debug_mode, model_override, url_override, start_page

@dataclass
class PageData:
    rows: List[dict]


def close_open_json_structures(json_str: str) -> str:
    """Balance unclosed { or [ tokens in a JSON-like string."""
    stack = []
    in_string = False
    escape_next = False

    for char in json_str:
        if escape_next:
            escape_next = False
            continue
        if char == '\\':
            escape_next = True
            continue
        if char == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == '{':
            stack.append('}')
        elif char == '[':
            stack.append(']')
        elif char in ('}', ']') and stack:
            stack.pop()

    # append missing closing braces/brackets in reverse order
    return json_str + ''.join(reversed(stack))


def trim_to_root_object(json_str: str) -> str:
    """Trim any leading/trailing text outside the first balanced root object."""
    brace_count = 0
    start = None
    end = None
    in_string = False
    escape_next = False

    for idx, char in enumerate(json_str):
        if escape_next:
            escape_next = False
            continue
        if char == '\\':
            escape_next = True
            continue
        if char == '"' and not escape_next:
            in_string = not in_string
        if in_string:
            continue
        if char == '{':
            if brace_count == 0:
                start = idx
            brace_count += 1
        elif char == '}':
            brace_count -= 1
            if brace_count == 0 and start is not None:
                end = idx + 1
                break

    if start is not None and end is not None:
        return json_str[start:end]
    return json_str


def normalize_payload_structure(data: any) -> Optional[dict]:
    """Normalize various model payload shapes into a dict with a unified rows list."""
    if isinstance(data, list):
        # treat bare lists as the rows payload
        return {"rows": data}

    if not isinstance(data, dict):
        return None

    rows: list = []

    # prefer explicit rows-like keys
    for key in ("rows", "entries", "records", "lines", "items"):
        if isinstance(data.get(key), list):
            rows.extend(data.get(key, []))

    # backwards compatibility: merge transactions/trades if present
    if isinstance(data.get("transactions"), list):
        rows.extend(data.get("transactions", []))
    if isinstance(data.get("trades"), list):
        rows.extend(data.get("trades", []))

    data["rows"] = rows
    return data


def score_payload(data: dict) -> int:
    """Rough score to pick the most complete parse."""
    if not isinstance(data, dict):
        return 0
    return len(data.get("rows", []))


def try_parse_json_with_repair(json_str: str) -> tuple[Optional[dict], Optional[str]]:
    """Attempt to parse JSON using several repair strategies and return best result."""
    candidates = [
        ("raw", json_str),
        ("trimmed_root", trim_to_root_object(json_str)),
        ("balanced", close_open_json_structures(json_str)),
    ]

    best_data = None
    best_label = None
    best_score = -1

    for label, candidate in candidates:
        try:
            parsed = json.loads(candidate)
            normalized = normalize_payload_structure(parsed)
            if not normalized:
                continue
            score = score_payload(normalized)
            if score > best_score:
                best_score = score
                best_data = normalized
                best_label = label
        except json.JSONDecodeError:
            continue

    return best_data, best_label


def extract_objects_from_section(section_text: str) -> List[dict]:
    """Parse a list of JSON objects from a truncated array section."""
    cleaned = section_text.strip()
    cleaned = cleaned.rstrip(',')  # remove trailing comma in array
    cleaned = re.sub(r',\s*([\]}])', r'\1', cleaned)  # remove trailing commas before closing

    objects = []
    # split loosely on object boundaries
    parts = re.split(r'}\s*,\s*{', cleaned)
    for idx, part in enumerate(parts):
        part = part.strip()
        if not part:
            continue
        if not part.startswith('{'):
            part = '{' + part
        if not part.endswith('}'):
            part = part + '}'
        try:
            obj = json.loads(part)
            if isinstance(obj, dict):
                objects.append(obj)
        except Exception:
            # skip malformed object; continue salvaging others
            continue
    return objects


def slice_array_section(content: str, key: str) -> Optional[str]:
    """Slice out the array section for a given key, tolerating missing closing bracket."""
    key_pos = content.find(f'"{key}"')
    if key_pos == -1:
        return None
    start_bracket = content.find('[', key_pos)
    if start_bracket == -1:
        return None

    in_string = False
    escape_next = False
    depth = 0
    end_pos = None
    for idx in range(start_bracket, len(content)):
        char = content[idx]
        if escape_next:
            escape_next = False
            continue
        if char == '\\':
            escape_next = True
            continue
        if char == '"' and not escape_next:
            in_string = not in_string
        if in_string:
            continue
        if char == '[':
            depth += 1
        elif char == ']':
            depth -= 1
            if depth == 0:
                end_pos = idx + 1
                break

    # if no closing bracket, take until end; extract_objects_from_section will repair each object.
    if end_pos is None:
        end_pos = len(content)

    return content[start_bracket:end_pos]


def salvage_partial_payload(content: str, debug_mode: bool = False) -> Optional[dict]:
    """Fallback: extract row arrays even if the JSON root is broken."""
    payload = {"rows": []}
    found_any = False

    for key in ROW_KEYS_OF_INTEREST:
        section = slice_array_section(content, key)
        if section:
            found_any = True
            inner = section.lstrip('[').rstrip(']')
            payload["rows"].extend(extract_objects_from_section(inner))

    if found_any:
        if debug_mode:
            console.print("[debug]Salvaged partial payload from malformed JSON[/debug]")
        return payload
    return None


def is_balance_key(key: str) -> bool:
    return key.lower() in BALANCE_KEYS


def is_summary_row(row: dict) -> bool:
    """Identify summary/overview rows (product + opening/closing balance rollups)."""
    keys = set(row.keys())
    has_product = any(k in PRODUCT_HEADER_MARKERS for k in keys)
    has_rollup = any(k in BALANCE_ROLLUP_MARKERS for k in keys)
    # liquidity/market-value style summary: isin + units + price + market value
    has_isin = ISIN_KEY in keys
    has_units = any(k in UNITS_MARKERS for k in keys)
    has_price = any(k in PRICE_MARKERS for k in keys)
    has_market_value = any(k in MARKET_VALUE_MARKERS for k in keys)
    has_liquidity_marker = any(k in LIQUIDITY_MARKERS for k in keys)

    liquidity_block = has_isin and (has_units or has_price or has_market_value or has_liquidity_marker)
    return (has_product and has_rollup) or liquidity_block


DESCRIPTION_NULL_RE = re.compile(r"\s*null$")


def is_description_key(key: str) -> bool:
    key = key.lower()
    return "descrizione" in key or "description" in key


def strip_trailing_null(value: str) -> str:
    return DESCRIPTION_NULL_RE.sub("", value).rstrip()


def is_value_present(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def row_has_error(row: dict) -> bool:
    required_fields = ("data", "tipo", "descrizione")
    for key in required_fields:
        if not is_value_present(row.get(key)):
            return True

    balance_value = None
    for key in row.keys():
        if is_balance_key(key):
            balance_value = row.get(key)
            break
    if not is_value_present(balance_value):
        return True

    in_entrata_present = is_value_present(row.get("in entrata"))
    in_uscita_present = is_value_present(row.get("in uscita"))
    if not (in_entrata_present or in_uscita_present):
        return True

    return False


class OutputWriter:
    """Append rows to CSV/Excel/JSON; rewrites tabular files if schema expands."""

    def __init__(self, path: Path, fmt: str):
        self.path = Path(path)
        self.format = fmt
        self.columns: list[str] = []
        self.path.parent.mkdir(exist_ok=True)

    def _update_columns(self, rows: List[dict]) -> bool:
        changed = False
        for row in rows:
            for key in row.keys():
                if key not in self.columns:
                    self.columns.append(key)
                    changed = True
        return changed

    def _pad_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        for col in self.columns:
            if col not in df.columns:
                df[col] = None
        return df[self.columns]

    def _write_json(self, rows: List[dict], debug_mode: bool = False):
        try:
            existing: list = []
            if self.path.exists():
                try:
                    with open(self.path, "r", encoding="utf-8") as f:
                        existing = json.load(f)
                    if not isinstance(existing, list):
                        existing = []
                except Exception:
                    existing = []

            combined = existing + rows
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(combined, f, ensure_ascii=False, indent=2)
        except Exception as e:
            console.print(f"[warning]Failed to write JSON: {str(e)[:120]}[/warning]")
            if debug_mode:
                console.print(f"[debug]Offending rows: {rows}[/debug]")

    def _write_csv(self, df_new: pd.DataFrame, new_cols: bool, debug_mode: bool = False):
        if self.path.exists() and new_cols:
            try:
                existing = pd.read_csv(self.path)
                existing = self._pad_dataframe(existing)
                combined = pd.concat([existing, df_new], ignore_index=True)
                combined.to_csv(self.path, index=False, encoding="utf-8")
                if debug_mode:
                    console.print(f"[debug]Rewrote {self.path.name} with new columns: {self.columns}[/debug]")
            except Exception as e:
                console.print(f"[warning]Failed to rewrite CSV on schema change: {str(e)[:120]}[/warning]")
        elif not self.path.exists():
            df_new.to_csv(self.path, index=False, encoding="utf-8")
        else:
            df_new.to_csv(self.path, mode="a", index=False, header=False, encoding="utf-8")

    def _write_excel(self, df_new: pd.DataFrame, debug_mode: bool = False):
        try:
            if self.path.exists():
                existing = pd.read_excel(self.path)
                existing = self._pad_dataframe(existing)
                combined = pd.concat([existing, df_new], ignore_index=True)
            else:
                combined = df_new
            combined = self._pad_dataframe(combined)
            combined.to_excel(self.path, index=False, engine="openpyxl")
        except Exception as e:
            console.print(f"[warning]Failed to write Excel file: {str(e)[:120]}[/warning]")
            if debug_mode:
                console.print(f"[debug]Columns: {self.columns}[/debug]")

    def write_rows(self, rows: List[dict], debug_mode: bool = False):
        if not rows:
            return

        new_cols = self._update_columns(rows)

        if self.format == "json":
            self._write_json(rows, debug_mode=debug_mode)
            return

        df_new = pd.DataFrame(rows)
        df_new = self._pad_dataframe(df_new)

        if self.format == "csv":
            self._write_csv(df_new, new_cols, debug_mode=debug_mode)
        elif self.format == "xlsx":
            self._write_excel(df_new, debug_mode=debug_mode)
        else:
            console.print(f"[warning]Unsupported output format '{self.format}'; skipping write.[/warning]")

VISION_PROMPT_PATH = Path("prompts/system_prompt.txt")
DEFAULT_VISION_PROMPT_PATH = Path("prompts/default_system_prompt.txt")
_vision_prompt_cache: dict[str, str] = {}


def get_vision_prompt(prompt_path: str | Path | None = None) -> str:
    """Return the vision system prompt, preferring external files."""
    cached = _vision_prompt_cache.get("value")
    if cached:
        return cached

    primary_path = Path(prompt_path) if prompt_path else VISION_PROMPT_PATH
    fallback_path = DEFAULT_VISION_PROMPT_PATH

    for path in (primary_path, fallback_path):
        if path.exists():
            try:
                text = path.read_text(encoding="utf-8").strip()
                if text:
                    _vision_prompt_cache["value"] = text
                    return text
                console.print(f"[warning]System prompt file {path} is empty; trying fallback...[/warning]")
            except Exception as e:
                console.print(f"[warning]Could not read system prompt file {path}: {str(e)[:80]}[/warning]")

    _vision_prompt_cache["value"] = DEFAULT_VISION_EXTRACTION_PROMPT
    return DEFAULT_VISION_EXTRACTION_PROMPT

def convert_page_to_image(
    pdf_path: str,
    page_num: int,
    dpi: int = 300,
    brightness: float = 1.5,
    contrast: float = 1.5,
    scale: float = 0.5,
    save_path: Path | str | None = None,
    debug_mode: bool = False,
) -> str:
    """Convert PDF page to base64 encoded image; optionally save the processed PNG"""
    try:
        images = convert_from_path(
            pdf_path,
            first_page=page_num + 1,
            last_page=page_num + 1,
            dpi=dpi,
            fmt='png'
        )

        if not images:
            return ""

        # enhance contrast/brightness to help ocr/vision with faint numbers
        enhanced = preprocess_image_for_ocr(images[0], brightness=brightness, contrast=contrast)

        # optional upscaling to help small numerals
        if scale and scale != 1.0:
            try:
                new_size = (int(enhanced.width * scale), int(enhanced.height * scale))
                enhanced = enhanced.resize(new_size, resample=Image.Resampling.LANCZOS)
            except Exception as e:
                console.print(f"[warning]Could not upscale image: {str(e)[:80]}[/warning]")

        working_image = enhanced
        max_mb = 10
        while True:
            buffered = BytesIO()
            working_image.save(buffered, format="PNG", optimize=True)
            img_size = buffered.tell() / (1024 * 1024)
            if debug_mode:
                console.print(f"[debug]Page {page_num + 1} image size: {img_size:.2f}MB[/debug]")

            if img_size <= max_mb or min(working_image.size) < 800:
                break

            console.print(f"[warning]Page {page_num + 1} image is {img_size:.1f}MB; downscaling to reduce load[/warning]")
            try:
                new_size = (int(working_image.width * 0.85), int(working_image.height * 0.85))
                working_image = working_image.resize(new_size, resample=Image.Resampling.LANCZOS)
            except Exception as e:
                console.print(f"[warning]Could not downscale large page: {str(e)[:80]}[/warning]")
                break

        if save_path:
            try:
                Path(save_path).parent.mkdir(parents=True, exist_ok=True)
                working_image.save(save_path, format="PNG")
            except Exception as e:
                console.print(f"[warning]Could not save page image: {str(e)[:80]}[/warning]")

        buffered.seek(0)
        return base64.b64encode(buffered.getvalue()).decode('utf-8')

    except Exception as e:
        console.print(f"[error]Failed to convert page {page_num + 1} to image: {str(e)[:100]}[/error]")
        return ""

def extract_with_vision_llm(
    image_base64: str,
    model: str = "ministral-3:8b",
    ollama_url: str = "http://localhost:11434",
    temperature: float = DEFAULT_TEMPERATURE,
    max_retries: int = 2,
    request_timeout: float | None = 120,
    max_tokens: int | None = None,
    num_ctx: int | None = None,
    debug_mode: bool = False,
    page_num: int | None = None,
    max_response_chars: int | None = None,
    heartbeat: Callable | None = None,
) -> PageData:
    """Extract financial data using vision LLM with retry logic"""
    def extract_response_text(payload: object) -> str:
        if isinstance(payload, dict):
            return payload.get("response", "")
        return getattr(payload, "response", "")

    client_kwargs = {"host": ollama_url}
    if request_timeout is not None:
        client_kwargs["timeout"] = request_timeout
    client = ollama.Client(**client_kwargs)

    for attempt in range(max_retries):
        try:
            system_prompt = get_vision_prompt()
            page_label = f" for page {page_num + 1}" if page_num is not None else ""
            console.print(f"[processing]Calling vision model{page_label} (attempt {attempt + 1}/{max_retries})...[/processing]")
            content_parts: list[str] = []
            streamed = False
            content_length = 0
            start_ts = time.time()
            deadline = start_ts + request_timeout if request_timeout else None

            generate_kwargs = {
                'model': model,
                'prompt': system_prompt,
                'images': [image_base64],
                'options': {
                    'temperature': temperature,
                    **({'num_predict': max_tokens} if max_tokens is not None else {}),
                    **({'num_ctx': num_ctx} if num_ctx is not None else {}),
                },
            }

            try:
                response_iter = client.generate(**generate_kwargs, stream=True)
                streamed = True
            except TypeError:
                # streaming unsupported; fall back to non-stream (length guard will run after completion)
                response = client.generate(**generate_kwargs)
                content = extract_response_text(response)

            if streamed:
                truncated_due_to_length = False
                last_heartbeat = time.time()
                for chunk in response_iter:
                    if deadline and time.time() > deadline:
                        console.print(f"[warning]Vision call{page_label} exceeded {request_timeout}s; aborting and retrying page[/warning]")
                        raise TimeoutError("Vision call timed out")

                    part = extract_response_text(chunk)
                    if part:
                        content_parts.append(part)
                        content_length += len(part)
                        if max_response_chars is not None and content_length > max_response_chars:
                            console.print(f"[warning]Response length exceeded {max_response_chars} chars; truncating and attempting parse[/warning]")
                            truncated_due_to_length = True
                            break
                    if heartbeat and (time.time() - last_heartbeat) >= 1:
                        try:
                            heartbeat()
                        except Exception:
                            pass
                        last_heartbeat = time.time()
                content = "".join(content_parts)
                if truncated_due_to_length and max_response_chars is not None:
                    content = content[:max_response_chars]

            duration = time.time() - start_ts
            if duration > 60:
                console.print(f"[warning]Vision call{page_label} took {duration:.1f}s; consider lowering DPI/scale or model load[/warning]")
            else:
                console.print(f"[success]Vision call{page_label} completed in {duration:.1f}s[/success]")

            if debug_mode:
                console.print(f"[debug]Response length: {len(content)} chars[/debug]")
                console.print(f"[debug]Response preview:\n{content[:1000]}...\n[/debug]")

            if max_response_chars is not None and len(content) > max_response_chars:
                console.print(f"[warning]Response length {len(content)} exceeds threshold {max_response_chars}; retrying page[/warning]")
                if attempt < max_retries - 1:
                    continue
                else:
                    raise json.JSONDecodeError("Response too long", content, 0)

            if debug_mode and attempt == 0:
                console.print(f"[debug]First attempt - response length: {len(content)} chars[/debug]")
                console.print(f"[debug]Raw response:\n{content[:500]}...[/debug]")

            json_str = None

            # extract json from response using multiple strategies
            if '```json' in content:
                json_start = content.find('```json') + 7
                json_end = content.find('```', json_start)
                if json_end > json_start:
                    json_str = content[json_start:json_end].strip()
            elif '```' in content:
                lines = content.split('\n')
                in_code_block = False
                code_lines = []
                for line in lines:
                    if line.strip().startswith('```'):
                        in_code_block = not in_code_block
                        continue
                    if in_code_block:
                        code_lines.append(line)
                if code_lines:
                    json_str = '\n'.join(code_lines).strip()

            # find first complete json object to avoid extra data errors
            if not json_str:
                brace_count = 0
                first_brace = None
                json_end = None
                in_string = False
                escape_next = False

                for i, char in enumerate(content):
                    if escape_next:
                        escape_next = False
                        continue
                    if char == '\\':
                        escape_next = True
                        continue
                    if char == '"' and not escape_next:
                        in_string = not in_string
                        continue
                    if not in_string:
                        if char == '{':
                            if brace_count == 0:
                                first_brace = i
                            brace_count += 1
                        elif char == '}':
                            brace_count -= 1
                            if brace_count == 0 and first_brace is not None:
                                json_end = i + 1
                                break

                if first_brace is not None and json_end is not None:
                    potential_json = content[first_brace:json_end]
                    json_str = potential_json.strip()

            # regex fallback for malformed json
            if not json_str:
                try:
                    json_pattern = r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
                    matches = re.findall(json_pattern, content, re.DOTALL)

                    for match in matches:
                        try:
                            test_data = json.loads(match)
                            if isinstance(test_data, dict):
                                json_str = match
                                if debug_mode:
                                    console.print(f"[debug]Found valid JSON using regex fallback[/debug]")
                                break
                        except Exception:
                            continue
                except Exception as e:
                    if debug_mode:
                        console.print(f"[debug]Regex fallback failed: {e}[/debug]")

            # clean and fix json issues
            if json_str:
                original_json = json_str

                # basic cleanup
                json_str = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', json_str)

                # remove common problematic patterns
                json_str = re.sub(r',\s*}', '}', json_str)  # remove trailing commas
                json_str = re.sub(r',\s*\]', ']', json_str)  # remove trailing commas in arrays

                # fix missing commas between properties
                json_str = re.sub(r'"\n\s*"', '",\n      "', json_str)
                json_str = re.sub(r'}\n\s*"', '},\n      "', json_str)

                # only fix decimals if needed (avoid over-fixing)
                if re.search(r':\s*\d+,\d+', json_str):
                    json_str = re.sub(r':\s*(\d+),(\d{2})(?=\D)', r': \1.\2', json_str)

                if original_json != json_str and debug_mode and attempt == 0:
                    console.print("[debug]Applied basic JSON fixes[/debug]")

            # parse json with repair attempts for truncated model output
            if json_str:
                data, parse_label = try_parse_json_with_repair(json_str)

                if data is None:
                    # last-ditch salvage: extract object lists from partial arrays
                    data = salvage_partial_payload(json_str, debug_mode=debug_mode) or salvage_partial_payload(content, debug_mode=debug_mode)

                if data is None:
                    if attempt == 0 and debug_mode:
                        console.print("[debug]No JSON structure found in response[/debug]")
                    raise json.JSONDecodeError("No JSON found in response", content, 0)

                if debug_mode and parse_label:
                    console.print(f"[debug]Parsed payload using '{parse_label}' strategy[/debug]")
            else:
                if attempt == 0 and debug_mode:
                    console.print("[debug]No JSON structure found in response[/debug]")
                raise json.JSONDecodeError("No JSON found in response", content, 0)

            # process unified rows (no transactions/trades split)
            processed_rows = []
            chosen_balance_key = None

            raw_rows = data.get("rows", [])
            for row in raw_rows:
                if isinstance(row, str):
                    continue
                if not isinstance(row, dict):
                    continue

                processed_row = {}
                for key, value in row.items():
                    if key is None:
                        continue
                    norm_key = str(key).strip().lower()
                    if not norm_key:
                        continue

                    target_key = norm_key
                    if is_balance_key(norm_key):
                        if chosen_balance_key is None:
                            chosen_balance_key = norm_key
                        target_key = chosen_balance_key
                        if target_key in processed_row:
                            continue

                    if isinstance(value, str):
                        cleaned_value = value.strip()
                        if is_description_key(norm_key):
                            cleaned_value = strip_trailing_null(cleaned_value)
                        processed_row[target_key] = cleaned_value
                    else:
                        processed_row[target_key] = value if value is not None else None
                if processed_row and not is_summary_row(processed_row):
                    processed_row["error"] = "yes" if row_has_error(processed_row) else ""
                    processed_rows.append(processed_row)

            return PageData(rows=processed_rows)

        except TimeoutError:
            if attempt < max_retries - 1:
                continue
            console.print("[red]Vision call timed out; giving up on this page[/red]")
            return PageData(rows=[])

        except json.JSONDecodeError as e:
            if debug_mode:
                console.print(f"[warning]JSON parsing failed: {str(e)[:80]}... retrying page[/warning]")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            else:
                console.print("[red]Failed to extract data after all retries[/red]")
                return PageData(rows=[])

        except Exception as e:
            if debug_mode:
                console.print(f"[warning]Processing error: {str(e)[:80]}... retrying page[/warning]")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            else:
                console.print("[red]Failed to process page after retries[/red]")
                return PageData(rows=[])

    return PageData(rows=[])


def preprocess_image_for_ocr(image, brightness: float = 1.0, contrast: float = 1.0):
    """Lightweight image enhancement to make text pop for OCR/LLM vision."""
    try:
        img = image.convert("RGB")
        if brightness != 1.0:
            img = ImageEnhance.Brightness(img).enhance(brightness)
        if contrast != 1.0:
            img = ImageEnhance.Contrast(img).enhance(contrast)
        return img
    except Exception as e:
        console.print(f"[warning]Could not preprocess image: {str(e)[:80]}[/warning]")
        return image

def get_pdf_page_count(pdf_path: str) -> int:
    """Get the number of pages in a PDF without rendering every page."""
    try:
        info = pdfinfo_from_path(pdf_path)
        pages = int(info.get("Pages", 0))
        if pages > 0:
            return pages
    except Exception as e:
        console.print(f"[warning]Could not read PDF info for {pdf_path}: {str(e)[:80]}[/warning]")

    # fallback: render first page only to verify readability
    try:
        images = convert_from_path(pdf_path, first_page=1, last_page=1, dpi=150)
        if images:
            return len(images)
    except Exception as e:
        console.print(f"[error]Could not count pages in {pdf_path}: {str(e)[:100]}[/error]")
    return 0

def resolve_output_format(config_value: str | None) -> str:
    """Validate and normalize output_format from config."""
    fmt = str(config_value or DEFAULT_OUTPUT_FORMAT).lower()
    if fmt not in OUTPUT_FORMAT_CHOICES:
        console.print(f"[warning]Unsupported output_format '{config_value}'; defaulting to {DEFAULT_OUTPUT_FORMAT}[/warning]")
        return DEFAULT_OUTPUT_FORMAT
    return fmt


def sanitize_positive_limit(value: int | None, default_value: int, label: str) -> int:
    """Ensure limits are positive integers; fall back to default otherwise."""
    try:
        if value is not None:
            int_value = int(value)
            if int_value > 0:
                return int_value
    except (TypeError, ValueError):
        pass

    console.print(f"[warning]{label} must be a positive integer; using default {default_value}[/warning]")
    return default_value


def process_single_pdf(
    pdf_path: str,
    config: dict,
    output_dir: Path,
    output_format: str,
    debug_mode: bool = False,
    start_page: int | None = None,
    max_response_chars: int | None = None,
    max_tokens: int | None = None,
    num_ctx: int | None = None,
) -> tuple[int, list[str]]:
    """Process a single PDF file using vision LLM and write incrementally to disk"""
    global current_model, ollama_url

    model = config.get('parser', {}).get('model', 'ministral-3:8b')
    ollama_url = config.get('parser', {}).get('ollama_url', 'http://localhost:11434')
    temperature = config.get('parser', {}).get('temperature', DEFAULT_TEMPERATURE)
    image_cfg = config.get('image', {})
    dpi = image_cfg.get('dpi', 300)
    brightness = image_cfg.get('brightness', 1.5)
    contrast = image_cfg.get('contrast', 1.5)
    scale = image_cfg.get('scale', 0.5)
    pdf_name = Path(pdf_path).stem
    save_images = bool(config.get("save_page_images", True))
    images_dir = None
    if save_images:
        images_dir = output_dir / f"{pdf_name}_images"
        images_dir.mkdir(parents=True, exist_ok=True)

    current_model = model

    extension = OUTPUT_EXTENSIONS.get(output_format, "csv")
    output_path = output_dir / f'{pdf_name}.{extension}'
    writer = OutputWriter(output_path, output_format)

    num_pages = get_pdf_page_count(pdf_path)
    if num_pages == 0:
        console.print(f"[error]Could not read PDF: {pdf_path}[/error]")
        return 0, []

    console.print(f"\n[brand]Processing: {pdf_name}.pdf[/brand]")
    console.print(f"[info]Model: {model} | Temperature: {temperature} | Context: {num_ctx} | Pages: {num_pages} | DPI: {dpi} | Format: {output_format}[/info]")

    def format_eta(seconds: float | None) -> str:
        if seconds is None or seconds < 0:
            return "--:--"
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=40),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TextColumn("-"),
        TextColumn("[cyan]{task.fields[page]}"),
        TextColumn("-"),
        TimeElapsedColumn(),
        TextColumn("-"),
        TextColumn("ETA {task.fields[eta]}"),
        console=console
    ) as progress:

        task = progress.add_task(
            "Processing pages...",
            total=num_pages,
            page="Page 0/0",
            eta="--:--"
        )

        start_time = time.time()
        total_rows = 0
        page_durations: list[float] = []
        last_eta_sec: list[float | None] = [None]

        start_idx = max((start_page or 1) - 1, 0)

        for page_num in range(num_pages):
            progress.update(task, page=f"Page {page_num + 1}/{num_pages}")
            page_start = time.time()

            if page_num < start_idx:
                progress.update(
                    task,
                    description="Skipping page...",
                    advance=1,
                    eta="--:--",
                )
                continue

            progress.update(task, description="Converting to image...")
            save_path = images_dir / f"page_{page_num + 1}.png" if images_dir else None
            def heartbeat():
                elapsed_sec = time.time() - start_time
                completed = len(page_durations)
                remaining_pages = max(num_pages - completed - 1, 0)
                if completed > 0:
                    avg_per_page = sum(page_durations) / completed
                else:
                    avg_per_page = elapsed_sec / max(page_num, 1)
                new_eta = avg_per_page * remaining_pages
                eta_sec = new_eta
                if last_eta_sec[0] is not None:
                    eta_sec = 0.7 * last_eta_sec[0] + 0.3 * new_eta
                last_eta_sec[0] = eta_sec
                progress.update(task, eta=format_eta(eta_sec), elapsed=format_eta(elapsed_sec))

            image_base64 = convert_page_to_image(
                pdf_path,
                page_num,
                dpi,
                brightness=brightness,
                contrast=contrast,
                scale=scale,
                save_path=save_path,
                debug_mode=debug_mode,
            )

            if not image_base64:
                progress.advance(task)
                continue

            progress.update(task, description="Analyzing with vision LLM...")
            page_data = extract_with_vision_llm(
                image_base64,
                model=model,
                ollama_url=ollama_url,
                temperature=temperature,
                max_retries=3,
                debug_mode=debug_mode,
                page_num=page_num,
                max_response_chars=max_response_chars,
                max_tokens=max_tokens,
                num_ctx=num_ctx,
                heartbeat=heartbeat,
            )

            writer.write_rows(page_data.rows, debug_mode=debug_mode)

            total_rows += len(page_data.rows)

            pages_done = page_num + 1
            elapsed_sec = time.time() - start_time
            avg_per_page = elapsed_sec / pages_done if pages_done else 0
            remaining_pages = num_pages - pages_done
            eta_sec = avg_per_page * remaining_pages if remaining_pages > 0 else 0
            page_durations.append(time.time() - page_start)
            if last_eta_sec[0] is not None:
                eta_sec = 0.7 * last_eta_sec[0] + 0.3 * eta_sec
            last_eta_sec[0] = eta_sec

            progress.update(
                task,
                description=f"Processing pages...",
                advance=1,
                eta=format_eta(eta_sec),
                elapsed=format_eta(elapsed_sec)
            )

            del image_base64
            del page_data
            gc.collect()

    return total_rows, writer.columns

def main(
    model_override: str | None = None,
    url_override: str | None = None,
    debug_mode: bool = False,
    start_page: int | None = None,
):
    """Main execution function"""
    global current_model, ollama_url

    if debug_mode:
        console.print("[warning]Debug mode enabled - showing raw responses[/warning]")

    try:
        with open('settings.json', 'r', encoding='utf-8') as f:
            config = json.load(f)
    except FileNotFoundError:
        console.print("[error]Error: settings.json not found[/error]")
        console.print("[info]Run 'python setup.py' to create configuration[/info]")
        return
    except json.JSONDecodeError as e:
        console.print(f"[error]Error parsing settings.json: {e}[/error]")
        return

    parser_cfg = config.setdefault('parser', {})
    if model_override:
        parser_cfg['model'] = model_override
        console.print(f"[info]Using model override: {model_override}[/info]")
    if url_override:
        parser_cfg['ollama_url'] = url_override
        console.print(f"[info]Using Ollama URL override: {url_override}[/info]")

    if start_page is not None and not debug_mode:
        console.print("[error]--page can only be used together with --debug[/error]")
        return

    output_format = resolve_output_format(config.get("output_format"))
    max_response_chars = sanitize_positive_limit(
        config.get("max_response_chars", DEFAULT_MAX_RESPONSE_CHARS),
        DEFAULT_MAX_RESPONSE_CHARS,
        "max_response_chars",
    )
    max_tokens = sanitize_positive_limit(
        config.get("max_tokens", DEFAULT_MAX_TOKENS),
        DEFAULT_MAX_TOKENS,
        "max_tokens",
    )
    num_ctx = sanitize_positive_limit(
        config.get("parser", {}).get("num_ctx", DEFAULT_NUM_CTX),
        DEFAULT_NUM_CTX,
        "parser.num_ctx",
    )

    input_dir = Path(config.get('input_dir', 'input'))
    if not input_dir.exists():
        console.print(f"[error]Input directory not found: {input_dir}[/error]")
        return

    pdf_files = list(set(input_dir.glob('*.pdf')) | set(input_dir.glob('*.PDF')))
    if not pdf_files:
        console.print(f"[warning]No PDF files found in {input_dir}[/warning]")
        return

    console.print(f"\n[brand]{BRAND_NAME}[/brand]")
    console.print(f"[info]Found {len(pdf_files)} PDF file(s)[/info]")

    total_rows = 0

    for pdf_path in sorted(pdf_files):
        pdf_name = pdf_path.stem
        output_dir = Path(config.get('output_dir', 'output'))
        output_dir.mkdir(exist_ok=True)
        extension = OUTPUT_EXTENSIONS.get(output_format, "csv")
        rows_path = output_dir / f'{pdf_name}.{extension}'

        rows_count, columns = process_single_pdf(
            pdf_path,
            config,
            output_dir,
            output_format,
            debug_mode,
            start_page,
            max_response_chars,
            max_tokens,
            num_ctx,
        )

        if rows_count > 0:
            console.print(f"[success]Saved {rows_count} rows to {rows_path.name}[/success]")
            if debug_mode:
                console.print(f"[debug]Columns found: {columns}[/debug]")
            total_rows += rows_count
        else:
            console.print(f"[warning]No rows found in {pdf_name}.pdf[/warning]")

    console.print(f"\n[brand]Processing Complete![/brand]")
    console.print(f"[metric]Total Rows: {total_rows}[/metric]")

    if current_model and ollama_url:
        try:
            console.print(f"\n[info]Unloading model {current_model} from memory...[/info]")
            client = ollama.Client(host=ollama_url)
            client.generate(model=current_model, prompt='', keep_alive=0)
            console.print("[green]Model unloaded successfully[/green]")
        except Exception as e:
            console.print(f"[yellow]Warning: Could not unload model: {str(e)[:50]}...[/yellow]")

    console.print("\n[success]All done![/success]")

def run_setup():
    """Run setup.py module"""
    from pathlib import Path
    import subprocess
    import sys

    setup_path = Path(__file__).parent / 'setup.py'
    if not setup_path.exists():
        console.print("[error]setup.py not found![/error]")
        return False

    # if settings already exist, don't clobber the user's chosen model/config
    if (Path(__file__).parent / 'settings.json').exists():
        return True

    try:
        # run setup.py as subprocess to let the user pick a model interactively
        result = subprocess.run(
            [sys.executable, str(setup_path)],
            capture_output=True,
            text=True,
            timeout=60  # 1 minute timeout
        )

        if result.returncode == 0:
            console.print("[success]Setup completed successfully[/success]")
            return True
        else:
            console.print("[error]Setup failed[/error]")
            if result.stderr:
                console.print(f"[error]Error: {result.stderr[:200]}...[/error]")
            return False
    except subprocess.TimeoutExpired:
        console.print("[error]Setup timed out[/error]")
        return False
    except Exception as e:
        console.print(f"[error]Error running setup: {str(e)}[/error]")
        return False

if __name__ == "__main__":
    debug_mode, model_override, url_override, start_page = parse_args(sys.argv)

    # run setup if settings are missing to keep the onboarding flow smooth
    try:
        with open('settings.json', 'r'):
            pass
    except FileNotFoundError:
        console.print("[info]No settings found. Running setup...[/info]")
        if not run_setup():
            console.print("[error]Setup failed. Exiting.[/error]")
            sys.exit(1)

    main(model_override=model_override, url_override=url_override, debug_mode=debug_mode, start_page=start_page)
