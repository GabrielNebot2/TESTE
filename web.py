import re
import requests
from bs4 import BeautifulSoup
import pandas as pd

URL = "https://www.feirasdobrasil.com.br/demo2026/cal2026.asp?mes_evento=janeiro&pagina=1"
OUTPUT_FILE = "feiras_janeiro_2026.csv"


def fetch_html(url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        )
    }
    last_error = None

    for trust_env in (True, False):
        try:
            session = requests.Session()
            session.trust_env = trust_env
            response = session.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            return response.text
        except requests.RequestException as exc:
            last_error = exc

    raise RuntimeError(f"Falha ao baixar página: {last_error}")


def clean_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_field(text: str, label: str, next_labels: list[str]) -> str:
    boundary = "|".join(re.escape(item) for item in next_labels)
    pattern = re.compile(rf"{re.escape(label)}\s*(.*?)(?=\s*(?:{boundary})|$)", re.IGNORECASE)
    match = pattern.search(text)
    return clean_text(match.group(1)) if match else ""


def parse_eventos(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    eventos = []

    for name_cell in soup.select("td.verdana25_cinza"):
        nome_evento = clean_text(" ".join(name_cell.stripped_strings))
        if not nome_evento:
            continue

        table = name_cell.find_parent("table")
        if table is None:
            continue

        details_cells = table.select("td.verdana20_cinza")
        details_cell = next(
            (
                cell
                for cell in details_cells
                if "Data:" in " ".join(cell.stripped_strings)
                and "Cidade/UF:" in " ".join(cell.stripped_strings)
            ),
            None,
        )
        if details_cell is None:
            continue

        details_text = clean_text(" ".join(details_cell.stripped_strings))
        if "Data:" not in details_text:
            continue

        labels = [
            "Tamanho:",
            "Segmento:",
            "Acesso ao Evento:",
            "Mês:",
            "Data:",
            "Local:",
            "Cidade/UF:",
            "Promotor:",
            "Tel:",
        ]

        eventos.append(
            {
                "nome_evento": nome_evento,
                "periodicidade": extract_field(details_text, "", ["Tamanho:"]),
                "tamanho": extract_field(details_text, "Tamanho:", labels[1:]),
                "segmento": extract_field(details_text, "Segmento:", labels[2:]),
                "acesso": extract_field(details_text, "Acesso ao Evento:", labels[3:]),
                "mes": extract_field(details_text, "Mês:", labels[4:]),
                "data": extract_field(details_text, "Data:", labels[5:]),
                "local": extract_field(details_text, "Local:", labels[6:]),
                "cidade_uf": extract_field(details_text, "Cidade/UF:", labels[7:]),
                "promotor": extract_field(details_text, "Promotor:", labels[8:]),
                "telefone": extract_field(details_text, "Tel:", []),
            }
        )

    return eventos


def main() -> None:
    html = fetch_html(URL)
    eventos = parse_eventos(html)

    df = pd.DataFrame(eventos)
    df.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")

    print(f"Extração concluída. Total de eventos: {len(eventos)}")
    print(f"Arquivo CSV: {OUTPUT_FILE}")
    if not eventos:
        print("Diagnóstico: nenhum evento encontrado com os seletores atuais.")


if __name__ == "__main__":
    main()
