import subprocess
import sys
import json
import platform
import shutil
import time
import os
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm, IntPrompt
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from const import (
    PROJECT_NAME,
    AUTHOR,
    DEFAULT_RECOMMENDED_MODELS,
    MODEL_MEMORY_HINTS,
    DEFAULT_TEMPERATURE,
    DEFAULT_MAX_RESPONSE_CHARS,
    DEFAULT_MAX_TOKENS,
    DEFAULT_NUM_CTX,
    DEFAULT_OUTPUT_FORMAT,
    OUTPUT_FORMAT_CHOICES,
    DEFAULT_BALANCE_TOLERANCE,
    DEFAULT_INCLUDE_ERROR_COLUMN,
    DEFAULT_INCLUDE_BALANCE_CHECK_COLUMN,
)

console = Console()

def get_ollama_executable():
    """Get the Ollama executable path, works on all platforms."""
    # Check if ollama is in PATH first
    ollama_path = shutil.which('ollama')
    if ollama_path:
        return ollama_path

    # On Windows, check common installation paths
    if platform.system() == "Windows":
        common_paths = [
            os.path.expandvars(r"%ProgramFiles%\Ollama\ollama.exe"),
            os.path.expandvars(r"%LocalAppData%\Programs\Ollama\ollama.exe"),
            os.path.expandvars(r"%AppData%\Ollama\ollama.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Ollama\ollama.exe"),
        ]

        for path in common_paths:
            if os.path.exists(path):
                return path

    # Return None if not found
    return None

def check_ollama_installation():
    ollama_path = get_ollama_executable()
    if not ollama_path:
        console.print("[red]Ollama not found[/red]")
        return False

    try:
        result = subprocess.run([ollama_path, '--version'], capture_output=True, text=True, timeout=5)
        version = result.stdout.strip()
        console.print(f"[green]Ollama installed: {version}[/green]")
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        console.print("[red]Ollama not found[/red]")
        return False

def check_curl():
    return shutil.which('curl') is not None

def install_ollama():
    console.print("[info]Installing Ollama...[/info]")

    if platform.system() == "Windows":
        console.print("[yellow]Windows detected. To install Ollama on Windows:[/yellow]")
        console.print("\n1. Download Ollama from: [blue]https://ollama.com/download/windows[/blue]")
        console.print("2. Run the installer")
        console.print("3. After installation, the setup will automatically detect Ollama\n")

        # Check if Ollama is already installed
        ollama_path = get_ollama_executable()
        if ollama_path:
            console.print(f"[green]Ollama is already installed at: {ollama_path}[/green]")
            if not shutil.which('ollama'):
                console.print("[yellow]Note: Ollama is not in your PATH. You can still use Tradesight.[/yellow]")
            return True

        if Confirm.ask("Open Ollama download page in browser?"):
            import webbrowser
            webbrowser.open("https://ollama.com/download/windows")

        return False

    if not check_curl():
        console.print("[red]curl is required to install Ollama. Please install curl first.[/red]")
        console.print("[yellow]On Ubuntu/Debian: sudo apt-get install curl[/yellow]")
        console.print("[yellow]On macOS: brew install curl[/yellow]")
        return False

    install_script = "curl -fsSL https://ollama.com/install.sh | sh"

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            progress.add_task("Installing Ollama...", total=None)

            subprocess.run(
                install_script,
                shell=True,
                check=True,
                capture_output=True
            )

        console.print("[green]Ollama installed successfully[/green]")
        return True
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Installation failed: {e}[/red]")
        return False

def check_model(model_name):
    ollama_path = get_ollama_executable()
    if not ollama_path:
        return False

    try:
        result = subprocess.run([ollama_path, 'list'], capture_output=True, text=True, timeout=5)
        return model_name in result.stdout
    except:
        return False


def ensure_ollama_running():
    """try to ensure the ollama service is reachable."""
    ollama_path = get_ollama_executable()
    if not ollama_path:
        return False

    try:
        result = subprocess.run([ollama_path, 'list'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            return True
    except Exception:
        pass

    # try to start the service if available
    try:
        subprocess.Popen([ollama_path, 'serve'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(3)
        result = subprocess.run([ollama_path, 'list'], capture_output=True, text=True, timeout=5)
        return result.returncode == 0
    except Exception:
        return False

def download_model(model_name):
    ollama_path = get_ollama_executable()
    if not ollama_path:
        console.print("[red]Ollama not found. Cannot download model.[/red]")
        return False

    console.print(f"[info]Downloading {model_name}...[/info]")
    console.print("[yellow]This may take several minutes depending on your internet connection.[/yellow]")

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task(f"Downloading {model_name}...", total=None)

            result = subprocess.run(
                [ollama_path, 'pull', model_name],
                check=True,
                capture_output=True
            )

        console.print(f"[green]{model_name} downloaded successfully[/green]")
        return True
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Download failed: {e}[/red]")
        return False

def create_settings(
    model_name: str,
    output_format: str,
    save_images: bool,
    include_error_column: bool,
    include_balance_check_column: bool,
):
    """Create or update settings.json"""
    settings_path = Path("settings.json")

    fmt = (output_format or DEFAULT_OUTPUT_FORMAT).lower()
    if fmt not in OUTPUT_FORMAT_CHOICES:
        fmt = DEFAULT_OUTPUT_FORMAT

    if settings_path.exists():
        console.print("[info]Updating existing settings.json[/info]")
        with open(settings_path, 'r') as f:
            settings = json.load(f)
    else:
        console.print("[info]Creating new settings.json[/info]")
        settings = {
            "input_dir": "input",
            "output_dir": "output",
            "output_format": fmt,
            "image": {
                "dpi": 300,
                "brightness": 1.5,
                "contrast": 1.5,
                "scale": 0.5
            },
            "parser": {
                "model": model_name,
                "ollama_url": "http://localhost:11434",
                "temperature": DEFAULT_TEMPERATURE,
                "num_ctx": DEFAULT_NUM_CTX,
            },
            "max_response_chars": DEFAULT_MAX_RESPONSE_CHARS,
            "max_tokens": DEFAULT_MAX_TOKENS,
            "balance_tolerance": DEFAULT_BALANCE_TOLERANCE,
            "include_error_column": DEFAULT_INCLUDE_ERROR_COLUMN,
            "include_balance_check_column": DEFAULT_INCLUDE_BALANCE_CHECK_COLUMN,
            "save_page_images": True,
        }

    settings["input_dir"] = settings.get("input_dir", "input")
    settings["output_dir"] = settings.get("output_dir", "output")
    settings["output_format"] = fmt

    # update with vision model settings
    parser_settings = settings.get("parser", {})
    settings["parser"] = {
        "model": model_name,
        "ollama_url": parser_settings.get("ollama_url", "http://localhost:11434"),
        "temperature": parser_settings.get("temperature", DEFAULT_TEMPERATURE),
        "num_ctx": parser_settings.get("num_ctx", DEFAULT_NUM_CTX),
    }

    settings["image"] = {
        "dpi": settings.get("image", {}).get("dpi", 300),
        "brightness": settings.get("image", {}).get("brightness", 1.5),
        "contrast": settings.get("image", {}).get("contrast", 1.5),
        "scale": settings.get("image", {}).get("scale", 0.5)
    }
    settings["max_response_chars"] = settings.get("max_response_chars", DEFAULT_MAX_RESPONSE_CHARS)
    settings["max_tokens"] = settings.get("max_tokens", DEFAULT_MAX_TOKENS)
    settings["balance_tolerance"] = settings.get("balance_tolerance", DEFAULT_BALANCE_TOLERANCE)
    settings["include_error_column"] = bool(
        include_error_column if include_error_column is not None else settings.get("include_error_column", DEFAULT_INCLUDE_ERROR_COLUMN)
    )
    settings["include_balance_check_column"] = bool(
        include_balance_check_column
        if include_balance_check_column is not None
        else settings.get("include_balance_check_column", DEFAULT_INCLUDE_BALANCE_CHECK_COLUMN)
    )
    settings["save_page_images"] = bool(save_images if save_images is not None else settings.get("save_page_images", True))

    # remove ocr section if exists
    settings.pop("ocr", None)

    with open(settings_path, 'w') as f:
        json.dump(settings, f, indent=2)

    console.print(f"[green]Settings updated for {model_name}[/green]")


def list_local_models():
    """Return (models, error_message) where models is a list of (name, size)."""
    ollama_path = get_ollama_executable()
    if not ollama_path:
        return [], "Ollama not found"

    try:
        result = subprocess.run(
            [ollama_path, 'list'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode != 0:
            return [], result.stderr.strip() or "ollama list failed"

        models = []
        lines = result.stdout.strip().splitlines()
        # skip header line if present
        if lines and lines[0].lower().startswith("name"):
            lines = lines[1:]

        for line in lines:
            tokens = line.split()
            if len(tokens) >= 3:
                name = tokens[0]
                size = tokens[2]
            elif len(tokens) >= 2:
                name = tokens[0]
                size = tokens[1]
            else:
                continue
            models.append((name, size))
        return models, None
    except Exception as e:
        return [], str(e)

def install_dependencies():
    """Install required Python packages"""
    console.print("[info]Installing Python dependencies...[/info]")

    try:
        subprocess.run([
            sys.executable, "-m", "pip", "install", "-r", "requirements.txt"
        ], check=True)
        console.print("[green]Dependencies installed[/green]")
        return True
    except subprocess.CalledProcessError:
        console.print("[red]Failed to install dependencies[/red]")
        return False

def check_poppler():
    """check if poppler-utils is installed (required for pdf2image)"""
    if platform.system() == "Linux":
        if shutil.which("pdftoppm") and shutil.which("pdftocairo"):
            return True
        else:
            console.print("[yellow]poppler-utils not found. This is required for PDF to image conversion.[/yellow]")
            console.print("[yellow]On Ubuntu/Debian: sudo apt-get install poppler-utils[/yellow]")
            console.print("[yellow]On CentOS/RHEL: sudo yum install poppler-utils[/yellow]")
            return False
    elif platform.system() == "Darwin":  # macos
        if shutil.which("pdftoppm"):
            return True
        else:
            console.print("[yellow]poppler not found. Please install via Homebrew:[/yellow]")
            console.print("[yellow]brew install poppler[/yellow]")
            return False
    else:
        # windows or other - pdf2image might use different method
        return True

def main():
    """main interactive setup"""
    console.print(Panel.fit(
        f"[bold blue]{PROJECT_NAME} by {AUTHOR}[/bold blue]\n"
        "This wizard will set up your environment for PDF-to-CSV processing",
        title="Welcome"
    ))

    console.print(f"[green]Python {sys.version.split()[0]} detected[/green]")

    console.print("\n[bold]System Dependencies[/bold]")
    if not check_poppler():
        if not Confirm.ask("Continue anyway? (You may need to install poppler manually)"):
            sys.exit(1)

    console.print("\n[bold]Ollama Installation[/bold]")
    ollama_installed = check_ollama_installation()
    if not ollama_installed:
        if Confirm.ask("Ollama not found. Install now?"):
            if not install_ollama():
                console.print("[red]Setup cancelled[/red]")
                sys.exit(1)
        else:
            console.print("[yellow]Please install Ollama manually before continuing[/yellow]")
            sys.exit(1)

    console.print("\n[bold]Ollama Service[/bold]")
    if not ensure_ollama_running():
        console.print("[yellow]Could not verify Ollama service. Please ensure 'ollama serve' is running.[/yellow]")

    console.print("\n[bold]Vision Model Selection[/bold]")
    recommended_models = DEFAULT_RECOMMENDED_MODELS
    output_format_default = DEFAULT_OUTPUT_FORMAT
    if Path("settings.json").exists():
        try:
            with open("settings.json", "r", encoding="utf-8") as f:
                cfg = json.load(f)
                recommended_models = cfg.get("recommended_models", recommended_models)
                output_format_default = str(cfg.get("output_format", output_format_default)).lower()
        except Exception:
            pass
    recommended_model = recommended_models[0] if recommended_models else DEFAULT_RECOMMENDED_MODELS[0]

    local_models, list_error = list_local_models()
    table = Table(title="Available Vision Models (local Ollama)")
    table.add_column("#", style="white", justify="right")
    table.add_column("Model", style="cyan")
    table.add_column("Memory (est)", style="magenta")
    table.add_column("Source", style="white")

    choices = []

    seen = set()
    rows_display = []

    if local_models:
        for name, size in local_models:
            if name in seen:
                continue
            seen.add(name)
            mem = MODEL_MEMORY_HINTS.get(name, size or "?")
            rows_display.append((name, mem, "installed"))

    for name in recommended_models:
        if name in seen:
            continue
        seen.add(name)
        mem_hint = MODEL_MEMORY_HINTS.get(name, "light")
        rows_display.append((name, mem_hint, "not installed"))

    if not rows_display:
        for name in DEFAULT_RECOMMENDED_MODELS:
            if name in seen:
                continue
            seen.add(name)
            mem_hint = MODEL_MEMORY_HINTS.get(name, "light")
            rows_display.append((name, mem_hint, "not installed"))

    for idx, (name, mem, source) in enumerate(rows_display, start=1):
        table.add_row(str(idx), name, mem, source)
        choices.append(name)

    if list_error:
        console.print(f"[yellow]Could not list local models ({list_error}). If Ollama is not running, start it and rerun setup.[/yellow]")

    console.print(table)

    # offer pulling the recommended model on first setup
    settings_exists = Path("settings.json").exists()
    if not settings_exists and not check_model(recommended_model):
        if Confirm.ask(f"Pull recommended model {recommended_model}? (downloads via ollama pull)"):
            download_model(recommended_model)
            if recommended_model not in choices:
                choices.insert(0, recommended_model)
                # re-render table with new entry at top
                table = Table(title="Available Vision Models (local Ollama)")
                table.add_column("#", style="white", justify="right")
                table.add_column("Model", style="cyan")
                table.add_column("Memory (est)", style="magenta")
                table.add_column("Source", style="white")
                for idx, name in enumerate(choices, start=1):
                    table.add_row(str(idx), name, MODEL_MEMORY_HINTS.get(name, "?"), "pulled" if name == recommended_model else "installed")
                    console.print(table)

    default_idx = 1
    model_idx = IntPrompt.ask(
        f"Select vision model [1-{len(choices)}] or 0 for custom",
        default=default_idx,
        choices=[str(i) for i in range(0, len(choices) + 1)]
    )

    if int(model_idx) == 0:
        model = Prompt.ask("Enter custom model name (as known to Ollama)", default=recommended_model)
        if model not in choices:
            choices.insert(0, model)
    else:
        model = choices[int(model_idx) - 1]

    available_formats = list(OUTPUT_FORMAT_CHOICES)
    if output_format_default not in available_formats:
        output_format_default = DEFAULT_OUTPUT_FORMAT

    console.print("\n[bold]Output Format[/bold]")
    for idx, fmt in enumerate(available_formats, start=1):
        console.print(f"{idx}) {fmt}")

    default_fmt_idx = available_formats.index(output_format_default) + 1
    fmt_choice = IntPrompt.ask(
        f"Select output format [1-{len(available_formats)}]",
        default=default_fmt_idx,
        choices=[str(i) for i in range(1, len(available_formats) + 1)]
    )
    output_format = available_formats[int(fmt_choice) - 1]

    if not check_model(model):
        if Confirm.ask(f"{model} not found. Download now? (This may take several minutes)"):
            if not download_model(model):
                console.print("[red]Setup cancelled[/red]")
                sys.exit(1)
    else:
        console.print(f"[green]{model} is already installed[/green]")

    console.print("\n[bold]Debugging Aids[/bold]")
    save_images_default = True
    include_error_default = DEFAULT_INCLUDE_ERROR_COLUMN
    include_balance_check_default = DEFAULT_INCLUDE_BALANCE_CHECK_COLUMN
    if Path("settings.json").exists():
        try:
            with open("settings.json", "r", encoding="utf-8") as f:
                cfg = json.load(f)
                save_images_default = bool(cfg.get("save_page_images", True))
                include_error_default = bool(cfg.get("include_error_column", DEFAULT_INCLUDE_ERROR_COLUMN))
                include_balance_check_default = bool(
                    cfg.get("include_balance_check_column", DEFAULT_INCLUDE_BALANCE_CHECK_COLUMN)
                )
        except Exception:
            pass
    save_images = Confirm.ask(
        "Save page images sent to the vision model? (stored under output/<pdf>_images)",
        default=save_images_default
    )
    include_error_column = Confirm.ask(
        "Include 'error' column? (recommended; flags rows missing required fields)",
        default=include_error_default,
    )
    include_balance_check_column = include_balance_check_default

    create_settings(
        model,
        output_format,
        save_images,
        include_error_column,
        include_balance_check_column,
    )

    console.print("\n[bold]Python Dependencies[/bold]")
    if not Path("requirements.txt").exists():
        console.print("[red]requirements.txt not found[/red]")
        if not Confirm.ask("Continue anyway?"):
            sys.exit(1)
    else:
        install_dependencies()

    console.print("\n[bold]Creating Directories[/bold]")
    for dirname in ["input", "output"]:
        Path(dirname).mkdir(exist_ok=True)
        console.print(f"[green]{dirname}/ directory created[/green]")

    console.print(Panel.fit(
        f"[bold green]Setup Complete![/bold green]\n\n"
        f"Model: {model}\n"
        f"Settings: settings.json\n"
        f"Run: python main.py\n\n"
        f"[italic]Place PDF files in the 'input/' directory to get started[/italic]",
        title="Ready to Process PDFs"
    ))

if __name__ == "__main__":
    main()
