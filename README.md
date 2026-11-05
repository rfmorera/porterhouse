# porterhouse

Toma el Excel de saldos (`Book-Uruguay.xlsx`), interpreta sus hojas y envía a la
API de MondayCall cada saldo como una revisión de **net worth manual**, con la
fecha que figura en el Excel. Solo envía lo que todavía no se mandó: lo ya
enviado queda registrado en `data/ledger.json` (la "DB" de la prueba de
concepto, versionada en este repo).

## Requisitos

- Python 3.11+
- La API debe aceptar `date` en `POST/PATCH /transactions/net-worth/manual`
  (PR `backend_api` "Allow a date on manual net worth revisions").

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
```

Variables de entorno (`.env` o el entorno):

| Variable | Uso |
| --- | --- |
| `MONDAYCALL_JWT` | Token del usuario. Se envía como `X-Authorization: Bearer <jwt>`. |
| `MONDAYCALL_API_URL` | Gateway de la API. Default `https://api-dev.moneycall.io`; prod es `https://api.moneycall.io`. |
| `PORTERHOUSE_LEDGER` | Ruta del registro de lo enviado. Default `data/ledger.json`. |
| `PORTERHOUSE_RATES` | Caché de cotizaciones UYU/USD. Default `data/rates.json`. |
| `PORTERHOUSE_SHEETS` | Mapeo de hojas. Default `sheets.json`. |

## Uso

Interfaz web (archivo, campo para el token, log en vivo):

```bash
python -m porterhouse serve
```

Abrir <http://127.0.0.1:8765>. El token del formulario tiene prioridad sobre
`MONDAYCALL_JWT`; si el campo queda vacío se usa el del entorno. La casilla
"Solo simular" viene marcada: muestra todo lo que se enviaría sin llamar a la
API. Desmarcala para enviar de verdad.

Línea de comandos:

```bash
python -m porterhouse sync Book-Uruguay.xlsx --dry-run
python -m porterhouse sync Book-Uruguay.xlsx
python -m porterhouse sync Book-Uruguay.xlsx --rate 40.25
```

Después de una corrida real, commiteá `data/ledger.json` y `data/rates.json`
para que la próxima corrida (en cualquier máquina) sepa qué ya se envió.

## Cómo se interpreta el Excel

Cada hoja se mapea en `sheets.json` a un ítem manual (nombre, `type`,
`subtype`, moneda, ícono). Dentro de la hoja se busca la fila con los
encabezados `Nombre | Monto | Descripcion | Fecha`; las filas siguientes son los
datos.

- **`balance`** (hojas "Estado"): cada fila es el saldo de la cuenta en esa
  fecha. Se envía una revisión por fecha. Si dos filas repiten la fecha, vale la
  última.
- **`cumulative`** (`Inversiones`, `Prestamos`): cada fila es un aporte (o un
  retiro si es negativo). Se agrupa por `Nombre`, se ordena por fecha y se
  acumula, así el saldo en cada fecha es la suma de lo transferido hasta ese
  día. Cada nombre es un ítem distinto (`Inversión Gletir`, `Préstamo Ruben`).
  `overrides` permite cambiar tipo o ícono para un nombre (Binance → crypto).
- **Moneda**: las hojas marcadas `UYU` se convierten a USD con la cotización
  del día del registro (dólar billete BCU, promedio compra/venta; si BCU no
  responde se intenta `currency-api` de jsdelivr). Las cotizaciones se cachean
  en `data/rates.json`, que se puede editar a mano. `--rate` fuerza una
  cotización fija.
- **Supuestos** que conviene revisar en `sheets.json`: `Efectivo` y
  `Prestamos` se tratan como USD; `Mercado Pago` como UYU.

Filas que se omiten con un aviso en el log: sin fecha, con fecha futura, con
fecha inválida (año menor a 2000 o texto no reconocido, p. ej. `31/08/204`), o
con monto no numérico. Un saldo negativo se envía como 0 porque la API no
acepta montos negativos.

Las fechas como texto se interpretan primero como `dd/mm/aaaa` y, si eso no es
posible, como `mm/dd/aaaa`.

## Qué se envía

Por cada ítem con revisiones pendientes:

1. Si no está en `ledger.json` se busca por nombre en `GET /transactions/net-worth/`
   para reutilizar un ítem ya creado; si no existe se crea con
   `POST /transactions/net-worth/manual` usando la primera revisión y su fecha.
2. Cada revisión restante va con `PATCH /transactions/net-worth/manual/<id>`
   y `{"amount": <usd>, "date": <aaaa-mm-dd>}`.
3. Tras cada llamada exitosa se actualiza `ledger.json`, así una corrida
   interrumpida retoma donde quedó.

Una revisión se considera pendiente si su fecha no está en el ledger o si el
monto en USD cambió. Las filas borradas del Excel no se eliminan de la API.

## Tests

```bash
pytest
```
