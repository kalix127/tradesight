PROJECT_NAME = "Tradesight"
AUTHOR = "@kalix127"

# setup defaults
DEFAULT_RECOMMENDED_MODELS = ["ministral-3:8b"]
MODEL_MEMORY_HINTS = {
    "ministral-3:8b": "~6GB vRAM",
}
DEFAULT_OUTPUT_FORMAT = "csv"
OUTPUT_FORMAT_CHOICES = ("csv", "xlsx", "json")
OUTPUT_EXTENSIONS = {
    "csv": "csv",
    "xlsx": "xlsx",
    "json": "json",
}
DEFAULT_TEMPERATURE = 0.0
DEFAULT_MAX_RESPONSE_CHARS = 8000
DEFAULT_MAX_TOKENS = 8000
DEFAULT_NUM_CTX = 8192
DEFAULT_BALANCE_TOLERANCE = "0.00"
DEFAULT_INCLUDE_ERROR_COLUMN = True
DEFAULT_INCLUDE_BALANCE_CHECK_COLUMN = False
DEFAULT_VISION_EXTRACTION_PROMPT = (
    'Return JSON object {"rows": [...]} with all transaction table rows. Use table headers in the original language but '
    "normalize header keys to lowercase, keep their order, avoid duplicates that only differ by case, do not split data, "
    "include only one running balance column if present, skip summary/overview tables (account/balance overviews, "
    "product/opening/closing balance rollups, liquidity/market-value summaries), and do not leave amount/balance cells empty - "
    "read multi-line rows as single rows and fill all numeric columns."
)

# parsing markers
ISIN_KEY = "isin"
UNITS_MARKERS = {"units", "unità", "unit", "stk", "stück", "shares", "qty", "quantity", "nominale"}
PRICE_MARKERS = {"price", "price per unit", "preis", "kurs pro stück", "prezzo per unità"}
MARKET_VALUE_MARKERS = {"market value", "marketvalue", "valore di mercato", "kurswert", "valeur de marche", "valor de mercado"}

# payload keys/markers
ROW_KEYS_OF_INTEREST = ("rows", "entries", "records", "lines", "items", "transactions", "trades")
BALANCE_KEYS = ("balance", "saldo", "account_balance", "running_balance")
PRODUCT_HEADER_MARKERS = {
    "product",
    "produkt",
    "prodotto",
    "konto",
    "conto",
    "account",
    "cashkonto",
}
BALANCE_ROLLUP_MARKERS = {
    "opening balance",
    "opening",
    "anfangssaldo",
    "saldo iniziale",
    "initial balance",
    "closing balance",
    "closing",
    "endsaldo",
    "saldo finale",
}
LIQUIDITY_MARKERS = {
    "liquidity",
    "cash overview",
    "barmittel",
    "barmittelübersicht",
    "panoramica del saldo",
    "balance overview",
    "trust accounts",
    "conti fiduciari",
    "treuhandkonten",
    "money market",
    "geldmarktfonds",
    "fondi del mercato monetario",
}
